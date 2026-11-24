"""Fiverr transport: plain curl_cffi with chrome TLS. No browser, no login,
no token. Every call goes out the way a visitor opens a link in the address
bar (the navigation headers of the site's own page request), carrying one
cookie: logged_out_currency=USD.

What the site is (seen 2026-11-21): server-rendered pages that carry their
data as JSON in <script id="perseus-initial-props">, and a few JSON routes.
In front of both sits a bot manager that judges the TLS fingerprint first:

  * a current chrome fingerprint is let in from every exit tried, a stale
    one is refused everywhere. `impersonate="chrome"` of curl_cffi 0.17.0
    (chrome 152) passes; the same call from curl_cffi 0.16.3 (chrome 150)
    was refused on every try, on four exits (2026-11-21).
  * the JSON routes are refused when sent as the page's own script sends
    them (x-requested-with, sec-fetch-mode: cors) without a cookie a real
    browser earned. Opened as a navigation they answer without any cookie.
  * a refusal is HTTP 403 with the page "It needs a human touch" (or a
    small JSON naming a captcha script). A link refused on one exit stays
    refused there for minutes while it passes on another, so every retry
    of a call rides the next exit of its ladder.
  * nothing is carried from one request to the next: the cookies an answer
    sets are dropped, so each request is a first visit.

  * an address can be turned against as a whole: a laptop's own address,
    after about 150 calls in 40 minutes, was refused on every page and
    JSON route (2026-11-23). So after FIVERR_HOLD_AFTER_REFUSALS refusals
    in a row the first exit of a ladder is set aside for
    FIVERR_BLOCK_HOLD_S seconds and calls start on the exit behind it.

Two exit ladders (config, "--- fiverr ---"):
  pages and JSON   FIVERR_EXIT (the server's own IP: 27 of 27 tries passed
                   from the pod), then FIVERR_FALLBACK_EXITS
  listings         FIVERR_LISTING_EXIT (the India gateway exit), then
                   FIVERR_LISTING_FALLBACK_EXITS (Indian residential, then a
                   datacenter exit). A visitor from India is shown no
                   promoted gigs; from the US, GB, DE, FR, AU, CA, SG, BR and
                   JP 20 of every 48 rows are ads that repeat on every page
                   and push organic rows off the page numbers. So the
                   datacenter exit answers a shorter page (its ads are left
                   out), which api.py returns without keeping it.

Upstream surfaces:
  /search/gigs?query=&page=&filter=<sort>&ref=<filters>&sub_category=&nested_sub_category=
  /categories/<category>/<sub-category>?page=&filter=&ref=&nested_sub_category=
        a listing page, 48 rows. `ref` holds the filters as
        name:value,value|name:value. A page past the end answers 200 with
        no rows; far past it, 404.
  /<username>/<slug>        a gig page. An unknown slug answers the seller's
                            page, an unknown seller the home page (both 200).
  /<username>               a seller page; 404 for an unknown name. An
                            agency seller redirects to /agencies/<slug>.
  /gig_page/api/fetch_reviews/<gig id>?gig_id=&sort_by=&filter_by=&average_valuation_value=
                            &last_star_rating_id=&last_review_id=&last_score=
        5 reviews a call (page_size is ignored). An unknown id answers
        {"dynamicTranslations": {}}.
  /reviews/freelancer_reviews/<username>?sort_by=
        the first 5 reviews of a seller with the rating summary and the
        seller's numeric id; 404 {"error": "user_not_found"}.
  /reviews/fetch_freelancer_reviews/<user id>?sort_by=&last_...=
        the next 5.
  /categories/new_categories_tree_json, /categories/navigation_config
        the category tree (names, slugs) and its ids.
  /search/omnibox?query=    search suggestions.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  FiverrUpstreamError  transport failure / 5xx / unreadable answer   retryable
  FiverrBlocked        403 / 429 / the bot manager's page            retryable on the next exit
  FiverrBadRequest     upstream 400                                  never retried
  FiverrNotFound       404                                           never retried
"""
import json
import threading
import time
from urllib.parse import quote, urlencode

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from fiverr.refs import SITE
from scraper_utils import retry, sessions
from scraper_utils.pages import page_title as _page_title

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 30        # a page is 1.5 - 3 MB before compression
GATEWAY_TIMEOUT = 20     # a gateway try gets 29 s at most: give up early and move on
JSON_TIMEOUT = 20

PAGE = "page"            # gig and seller pages, the JSON routes
LISTING = "listing"      # search and category pages

# The headers of the site's own page request (Chrome, 2026-11-21). The session
# adds user-agent, the sec-ch-ua hints, accept-language and accept-encoding.
# logged_out_currency fixes the visitor's currency: without it prices, the
# budget filter and review price ranges follow the exit's country.
NAVIGATION_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,image/webp,"
               "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"),
    "priority": "u=0, i",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "cookie": "logged_out_currency=USD",
}

BLOCK_TITLE = "It needs a human touch"
_BLOCK_MARKERS = ('"blockscript"', "px-captcha", "captcha.px-cdn.net", "it needs a human touch")
_PAGE_DATA = 'id="perseus-initial-props"'      # a gig, seller or listing page carries its data; the bot manager's page has none


class FiverrUpstreamError(UpstreamError):
    """Transport failure, 5xx or an answer that cannot be read — retryable."""


class FiverrBlocked(FiverrUpstreamError, Blocked):
    """403 / 429 or the bot manager's page — retried on the next exit."""


class FiverrBadRequest(BadRequest):
    """The site rejected the parameters (HTTP 400) — never retried."""


class FiverrNotFound(NotFound):
    """No such gig, seller, category or page — never retried."""


# ---- sessions and exits ---------------------------------------------------------------

# One curl session per request thread and exit (a curl handle must not be
# shared across threads). A session carries nothing: no cookie is kept.
_local = threading.local()
_SESSIONS_PER_THREAD = 4


def _exits(kind):
    """The exit ladder of a kind of call: its configured exit, then the exits behind it."""
    if kind == LISTING:
        ladder = [config.FIVERR_LISTING_EXIT, *config.FIVERR_LISTING_FALLBACK_EXITS]
    else:
        ladder = [config.FIVERR_EXIT, *config.FIVERR_FALLBACK_EXITS]
    return [exit_ or "direct" for exit_ in ladder]


def _session(exit_):
    return sessions.keyed(sessions.thread_store(_local), exit_,
                          lambda: egress.exit_session(exit_, impersonate=IMPERSONATE), _SESSIONS_PER_THREAD)


def _drop_session(exit_):
    """Close the thread's session on `exit_` so the next call there starts on a fresh address."""
    sessions.drop_keyed(sessions.thread_store(_local), exit_)


# Process-wide, per kind of call: the run of refusals on the ladder's first exit, and
# until when that exit is set aside for every thread.
_hold_lock = threading.Lock()
_holds = {}


def _first_step(kind):
    """The ladder step a call starts on: 1 while the first exit is set aside, else 0."""
    hold = _holds.get(kind)
    return 1 if hold and time.time() < hold["until"] and len(_exits(kind)) > 1 else 0


def _refused_on_first_exit(kind):
    """One more refusal on the ladder's first exit. After config.FIVERR_HOLD_AFTER_REFUSALS
    in a row the exit is set aside for config.FIVERR_BLOCK_HOLD_S seconds: the site turns
    against an address for minutes, and every call would pay a refused try first."""
    with _hold_lock:
        hold = _holds.setdefault(kind, {"refusals": 0, "until": 0.0})
        hold["refusals"] += 1
        if hold["refusals"] < config.FIVERR_HOLD_AFTER_REFUSALS:
            return
        hold["refusals"] = 0
        hold["until"] = time.time() + config.FIVERR_BLOCK_HOLD_S
    exits = _exits(kind)
    if len(exits) > 1:
        print(f"fiverr: exit {exits[0]!r} refused {config.FIVERR_HOLD_AFTER_REFUSALS} calls in a row, "
              f"{kind} calls start on {exits[1]!r} for {config.FIVERR_BLOCK_HOLD_S} s", flush=True)


def _passed_on_first_exit(kind):
    hold = _holds.get(kind)
    if hold and hold["refusals"]:
        with _hold_lock:
            hold["refusals"] = 0


def reset_holds():
    """Tests: no exit is set aside."""
    with _hold_lock:
        _holds.clear()


def _retrying(fn, kind):
    """fn(exit) under the shared retry policy: only FiverrUpstreamError
    (Blocked included) is retried, each retry on the next exit of the
    ladder (the last one again once the ladder is used up); NotFound and
    BadRequest surface at once. A call starts on the second exit while the
    first one is set aside."""
    state = {"step": _first_step(kind), "exit": None}

    def once():
        exits = _exits(kind)
        step = min(state["step"], len(exits) - 1)
        state["exit"] = exits[step]
        try:
            answer = fn(state["exit"])
        except (FiverrNotFound, FiverrBadRequest):
            if step == 0:
                _passed_on_first_exit(kind)     # the site's own answer: the exit was let in
            raise
        if step == 0:
            _passed_on_first_exit(kind)
        return answer

    def failed(error):
        print(f"fiverr: exit {state['exit']!r} failed: {error}", flush=True)
        _drop_session(state["exit"])
        if state["step"] == 0 and isinstance(error, FiverrBlocked):
            _refused_on_first_exit(kind)
        state["step"] += 1

    return retry.run(once, config, FiverrUpstreamError, failed)


# ---- one request ---------------------------------------------------------------------

def is_block(status, text):
    """The bot manager's answer: 403 / 429, or its page / JSON under any status. The same
    words inside a real answer are not a block: a review's text or the query a JSON route
    echoes, a gig's title in the head of its page."""
    if status in (403, 429):
        return True
    text = text or ""
    head = text[:6000].lower()
    if head.lstrip()[:1] in ("{", "["):     # a JSON answer: the bot manager's names its captcha script
        return '"blockscript"' in head
    return any(marker in head for marker in _BLOCK_MARKERS) and _PAGE_DATA not in text


def classify(status, text, label):
    """The body of a 200. Otherwise the site's own error: a block -> FiverrBlocked,
    404 -> FiverrNotFound, 400 -> FiverrBadRequest, anything else -> FiverrUpstreamError."""
    if is_block(status, text):
        raise FiverrBlocked(f"HTTP {status} (refused) for {label}")
    if status == 200:
        return text
    if status in (404, 410):
        raise FiverrNotFound(f"{label} not found")
    if status == 400:
        raise FiverrBadRequest(f"Fiverr rejected the request for {label}: {(text or '')[:120]}")
    raise FiverrUpstreamError(f"HTTP {status} for {label}")


def _url(path, params=None):
    query = urlencode([(k, v) for k, v in (params or {}).items() if v not in (None, "")], quote_via=quote)
    return SITE + path + ("?" + query if query else "")


def _get(path, params, label, kind, as_json=False):
    url = _url(path, params)

    def once(exit_):
        sess = _session(exit_)
        sess.cookies.clear()        # every request is a first visit: nothing an answer set is sent back
        timeout = GATEWAY_TIMEOUT if config.gateway_exit(exit_) else (JSON_TIMEOUT if as_json else PAGE_TIMEOUT)
        try:
            resp = sess.get(url, headers=NAVIGATION_HEADERS, timeout=timeout)
        except Exception as e:
            raise FiverrUpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
        text = classify(resp.status_code, resp.text, label)
        if not as_json:
            return text
        try:
            return json.loads(text)
        except ValueError:
            raise FiverrBlocked(f"a page ({_page_title(text)[:60]!r}) where JSON was expected for {label}")

    return _retrying(once, kind)


def fetch_page(path, params=None, label=None, kind=PAGE):
    """The HTML of a page of the site."""
    return _get(path, params, label or path, kind)


def fetch_json(path, params=None, label=None):
    """A JSON route of the site, opened as a navigation -> the decoded answer."""
    return _get(path, params, label or path, PAGE, as_json=True)


# ---- the surfaces ----------------------------------------------------------------------

def fetch_search(params):
    """A search result page (HTML). `params`: query, page, filter, ref, sub_category, nested_sub_category."""
    return fetch_page("/search/gigs", params, f"search {params.get('query')!r}", LISTING)


def fetch_category(category, params):
    """A category listing page (HTML). `category` is 'category/sub-category'."""
    return fetch_page(f"/categories/{category}", params, f"category {category}", LISTING)


def fetch_gig(gig):
    """A gig page (HTML). `gig` is 'seller/slug'."""
    return fetch_page(f"/{gig}", None, f"gig {gig}")


def fetch_seller(seller):
    """A seller page (HTML). `seller` is a username or 'agencies/<slug>'."""
    return fetch_page(f"/{seller}", None, f"seller {seller}")


def fetch_gig_reviews(gig_id, params):
    """5 reviews of a gig (JSON). `params`: sort_by, filter_by, average_valuation_value and the cursor's three."""
    return fetch_json(f"/gig_page/api/fetch_reviews/{gig_id}", {"gig_id": gig_id, **params}, f"reviews of gig {gig_id}")


def fetch_seller_reviews_head(username, params):
    """The first 5 reviews of a seller with the rating summary and the seller's id (JSON)."""
    return fetch_json(f"/reviews/freelancer_reviews/{quote(username)}", params, f"reviews of seller {username}")


def fetch_seller_reviews(user_id, params):
    """5 more reviews of a seller, after a cursor (JSON)."""
    return fetch_json(f"/reviews/fetch_freelancer_reviews/{user_id}", params, f"reviews of seller {user_id}")


def fetch_category_tree():
    """The category tree: names, slugs and links (JSON)."""
    return fetch_json("/categories/new_categories_tree_json", None, "the category tree")


def fetch_category_ids():
    """The navigation menu: the numeric ids of categories, sub-categories and nested ones (JSON)."""
    return fetch_json("/categories/navigation_config", None, "the category ids")


def fetch_suggestions(query):
    """Search suggestions for the start of a query (JSON)."""
    return fetch_json("/search/omnibox", {"query": query}, f"suggestions for {query!r}")
