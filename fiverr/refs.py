"""Reference resolvers, link builders and the token tables for /fiverr/*.

ONE param per input: `gig` accepts a gig link or its `seller/slug` path
(the reviews endpoint also a numeric gig id), `seller` a username or a
profile link, `category` a category link or its `category/sub-category`
path. Resolvers raise ValueError with a message for the caller (RefField
turns it into a 400).

How the site names its records (seen 2026-11-21):
  * a gig lives at /<username>/<slug> and has a numeric id inside its page.
    The id cannot be turned into a link: /gigs/<id> redirects to a search.
  * a seller lives at /<username>; an agency seller redirects to
    /agencies/<agency slug>.
  * a listing lives at /categories/<category>/<sub-category>, a nested
    sub-category at /categories/<category>/<sub-category>/<nested slug>
    (or the query param nested_sub_category=<id>). A third segment the
    site does not know is ignored: it answers the sub-category.
"""
import re
from urllib.parse import parse_qsl, urlparse

SITE = "https://www.fiverr.com"

# First path segments that are pages of the site, never a username.
RESERVED = frozenset("""
    categories search gigs pro agencies users reviews gig_page seller_page support resources
    legal-portal cp stores start_selling hire content pages login join logo-maker business
    community forum blog news partnerships jobs certified neo go s l v2 v4 api activities
    recommendations portfolio sellers seller buyers inbox orders checkout cart press
    terms_of_service privacy-policy intellectual-property-policy sitemap about
""".split())

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{1,59}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,199}$")
_GIG_ID_RE = re.compile(r"^[0-9]{1,15}$")
_ATTRIBUTE_NAME_RE = re.compile(r"^[a-z0-9_]{1,60}$")
_ATTRIBUTE_VALUE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")

# The page size of a listing and how deep the site lets a visitor page (2026-11-21).
LISTING_PAGE_SIZE = 48
SEARCH_MAX_PAGE = 11       # 10 full pages and one of 20 rows: 500 gigs a search
CATEGORY_MAX_PAGE = 21     # 21 full pages: 1,008 gigs a category; page 22 answers 404
PRICE_CEILING = 50000      # the site's own upper bound of the budget filter, in USD

# sort: the public value -> the site's `filter` param. The site also names
# price_asc / price_desc, but the rows it answers for them are not in price
# order (2026-11-21), so they are not offered.
SORTS = {"relevance": "auto", "best_selling": "rating", "newest": "new"}
SORT_NAMES = {token: name for name, token in SORTS.items()}

# seller_level: the public value -> the token of the site's filter.
SELLER_LEVELS = {"top_rated": "top_rated_seller", "level_2": "level_two_seller",
                 "level_1": "level_one_seller", "new": "na"}
# Every spelling of a level the site's pages use -> the public value.
LEVEL_NAMES = {
    "top_rated_seller": "top_rated", "level_trs": "top_rated",
    "level_two_seller": "level_2", "level_two": "level_2",
    "level_one_seller": "level_1", "level_one": "level_1",
    "na": "new", "new_seller": "new", "": "new", "no_level": "new",
}
# A language level as a number (listing rows) and as a word (gig and seller pages).
LANGUAGE_LEVELS = {1: "basic", 2: "conversational", 3: "fluent", 4: "native_or_bilingual",
                   "BASIC": "basic", "CONVERSATIONAL": "conversational", "FLUENT": "fluent",
                   "NATIVE_OR_BILINGUAL": "native_or_bilingual"}
DELIVERY_TIMES = ("1", "3", "7")    # days: the site's own three choices
REVIEW_SORTS = {"relevant": "relevant", "recent": "recent"}

# Filters that have a param of their own (or that the site ignores): not accepted in `attributes`.
OWN_PARAMS = {
    "seller_level": "seller_level", "seller_location": "seller_country", "seller_language": "seller_language",
    "delivery_time": "delivery_time", "gig_price_range": "min_price / max_price", "price_buckets": "min_price / max_price",
    "pro": "pro", "is_seller_online": "online", "has_hourly": "hourly", "is_agency": "agency",
    "leaf_category": "sub_category", "sub_category": "sub_category", "nested_sub_category": "nested_sub_category",
}
# The site lists this filter but answers the unfiltered list for it (2026-11-21).
IGNORED_FILTERS = frozenset({"service_offerings", "pricing_factor"})


def _host_is_fiverr(url):
    host = (urlparse(url).hostname or "").lower()
    return host == "fiverr.com" or host.endswith(".fiverr.com")


def _as_url(value):
    """A pasted link with or without its scheme -> a URL; None for a bare value."""
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if re.match(r"^([a-z0-9-]+\.)*fiverr\.com(/|$|\?)", value, re.I):
        return "https://" + value
    return None


def _segments(value):
    """(path segments, query dict) of a fiverr.com link or a bare path."""
    url = _as_url(value)
    if url is None:
        if "://" in value or re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+/", value, re.I):
            raise ValueError("Must be a fiverr.com link.")
        path, _, query = value.partition("?")
        return [s for s in path.split("/") if s], dict(parse_qsl(query))
    if not _host_is_fiverr(url):
        raise ValueError("Must be a fiverr.com link.")
    parsed = urlparse(url)
    return [s for s in parsed.path.split("/") if s], dict(parse_qsl(parsed.query))


def _username(value):
    name = value.lower()
    if name in RESERVED or not _USERNAME_RE.match(name):
        raise ValueError(f"'{value}' is not a Fiverr username.")
    return name


def resolve_gig(value):
    """A gig link or `seller/slug` -> 'seller/slug'."""
    value = (value or "").strip()
    segments, _ = _segments(value)
    if len(segments) == 2 and segments[0].lower() not in RESERVED and _SLUG_RE.match(segments[1]):
        return f"{_username(segments[0])}/{segments[1].lower()}"
    raise ValueError("Must be a Fiverr gig link (https://www.fiverr.com/<seller>/<gig-slug>) "
                     "or its <seller>/<gig-slug> path.")


def resolve_gig_or_id(value):
    """A numeric gig id, a gig link or `seller/slug` -> the id as text, or 'seller/slug'."""
    value = (value or "").strip()
    if _GIG_ID_RE.match(value):
        return value
    try:
        return resolve_gig(value)
    except ValueError:
        raise ValueError("Must be a numeric gig id, a Fiverr gig link "
                         "(https://www.fiverr.com/<seller>/<gig-slug>) or its <seller>/<gig-slug> path.")


def is_gig_id(gig):
    return bool(_GIG_ID_RE.match(gig or ""))


def resolve_seller(value):
    """A username or a profile link -> the username; an agency link -> 'agencies/<slug>'.
    A gig link names its seller too."""
    value = (value or "").strip().lstrip("@")
    segments, _ = _segments(value)
    if segments and segments[0].lower() == "agencies" and len(segments) == 2 and _SLUG_RE.match(segments[1]):
        return f"agencies/{segments[1].lower()}"
    if segments and segments[0].lower() == "users" and len(segments) >= 2:
        segments = segments[1:2]
    if 1 <= len(segments) <= 2 and segments[0].lower() not in RESERVED:
        return _username(segments[0])
    raise ValueError("Must be a Fiverr username or a profile link (https://www.fiverr.com/<username>).")


def resolve_category(value):
    """A category link or its path -> 'category/sub-category' or
    'category/sub-category/nested-sub-category'."""
    value = (value or "").strip()
    segments, _ = _segments(value)
    if segments and segments[0].lower() == "categories":
        segments = segments[1:]
    segments = [s.lower() for s in segments]
    if "buy" in segments[1:2]:
        raise ValueError("A filtered landing page (/categories/<category>/buy/...) is not a listing: "
                         "pass <category>/<sub-category> and use the filter params.")
    if len(segments) == 1:
        raise ValueError("A top category has no gig list of its own: pass <category>/<sub-category>, "
                         "for example graphics-design/creative-logo-design (see /fiverr/categories/list).")
    if 2 <= len(segments) <= 3 and all(_SLUG_RE.match(s) for s in segments):
        return "/".join(segments)
    raise ValueError("Must be a Fiverr category link (https://www.fiverr.com/categories/<category>/<sub-category>) "
                     "or its <category>/<sub-category> path; a nested sub-category is a third segment.")


def resolve_attributes(value):
    """'style:retro,logo_type:mascot,logo_type:emblem' -> {'style': ['retro'],
    'logo_type': ['mascot', 'emblem']}: the category's own filters, by the
    names and values the listing answers under `attributes`."""
    chosen = {}
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, option = part.partition(":")
        name, option = name.strip().lower(), option.strip()
        if not sep or not _ATTRIBUTE_NAME_RE.match(name) or not _ATTRIBUTE_VALUE_RE.match(option):
            raise ValueError("Must be name:value pairs separated by commas, for example "
                             "style:retro,logo_type:mascot (names and values come from `attributes` of a listing answer).")
        if name in OWN_PARAMS:
            raise ValueError(f"'{name}' has a param of its own: {OWN_PARAMS[name]}.")
        if name in IGNORED_FILTERS:
            raise ValueError(f"Fiverr does not filter by '{name}'.")
        values = chosen.setdefault(name, [])
        if option not in values:
            values.append(option)
    if not chosen:
        raise ValueError("Must be name:value pairs separated by commas, for example style:retro.")
    if len(chosen) > 10:
        raise ValueError("At most 10 attributes.")
    return {name: chosen[name] for name in sorted(chosen)}


# ---- links ------------------------------------------------------------------------

def gig_link(path):
    """'/seller/slug?x=1' or 'seller/slug' -> the gig's link, without tracking params."""
    path = (path or "").split("?")[0].strip("/")
    return f"{SITE}/{path}" if path else None


def seller_link(username):
    return f"{SITE}/{username}" if username else None


def agency_link(slug):
    return f"{SITE}/agencies/{slug}" if slug else None


def category_link(*slugs):
    slugs = [s for s in slugs if s]
    return f"{SITE}/categories/{'/'.join(slugs)}" if slugs else None


def site_link(path):
    """A path of the site ('/categories/x?source=y') -> its link, without the query."""
    path = (path or "").split("?")[0]
    return SITE + path if path.startswith("/") else None


# ---- the review cursor --------------------------------------------------------------

_CURSOR_RE = re.compile(r"^([0-9a-f]{24})~(-?[0-9]+(?:\.[0-9]+)?(?:e-?[0-9]+)?)$")


def review_cursor(review_id, score):
    """The cursor after a review: its id and the site's own ordering score."""
    return f"{review_id}~{score if score is not None else 0}"


def resolve_cursor(value):
    """A `next_cursor` of a reviews answer, checked -> the same text."""
    value = (value or "").strip()
    if not _CURSOR_RE.match(value):
        raise ValueError("Must be the next_cursor of a previous answer.")
    return value


def cursor_params(cursor):
    """A cursor -> the three params Fiverr's reviews calls page with ({} for no cursor).
    Without the score the site answers no rows."""
    if not cursor:
        return {}
    review_id, score = _CURSOR_RE.match(cursor).groups()
    return {"last_star_rating_id": review_id, "last_review_id": review_id, "last_score": score}
