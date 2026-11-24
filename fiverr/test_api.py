"""Offline tests for the transport (fiverr/fetch.py: reading an answer, the
exit ladders) and for the endpoint logic (fiverr/api.py), with the network
and the cache replaced by fakes (the answers are the fixtures).

    python -m pytest fiverr/test_api.py -q
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from cache import DontCache  # noqa: E402
from fiverr import api, fetch, parsers, refs  # noqa: E402
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError  # noqa: E402
from scraper_utils.testing import hosted_only  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
PROPS = '<html><script type="application/json" id="perseus-initial-props">\n%s\n</script></html>'


def raw(name):
    opener = gzip.open if name.endswith(".gz") else open
    with opener(os.path.join(FX, name), "rt", encoding="utf-8") as f:
        return f.read()


def fixture(name):
    return json.loads(raw(name))


def page(name):
    """A page's data block, back inside a page."""
    return PROPS % raw(name)


@pytest.fixture(autouse=True)
def no_exit_set_aside():
    fetch.reset_holds()
    yield
    fetch.reset_holds()


# ---- the transport: reading an answer ------------------------------------------------------

def test_error_classes_follow_the_shared_taxonomy():
    assert issubclass(fetch.FiverrBlocked, Blocked) and issubclass(fetch.FiverrBlocked, fetch.FiverrUpstreamError)
    assert issubclass(fetch.FiverrUpstreamError, UpstreamError)
    assert issubclass(fetch.FiverrNotFound, NotFound) and issubclass(fetch.FiverrBadRequest, BadRequest)


def test_classify():
    assert fetch.classify(200, "<html>ok</html>", "x") == "<html>ok</html>"
    blocked = raw("blocked_page.html")
    for status in (403, 200):       # the bot manager's page is a block under any status
        with pytest.raises(fetch.FiverrBlocked):
            fetch.classify(status, blocked, "x")
    with pytest.raises(fetch.FiverrBlocked):
        fetch.classify(403, '{"altBlockScript":"https://captcha.px-cloud.net/x/captcha.js","blockScript":"y"}', "x")
    with pytest.raises(fetch.FiverrBlocked):
        fetch.classify(429, "", "x")
    with pytest.raises(fetch.FiverrNotFound):
        fetch.classify(404, raw("page_not_found_404.html"), "seller zz")
    with pytest.raises(fetch.FiverrBadRequest):
        fetch.classify(400, '{"error":"bad"}', "x")
    with pytest.raises(fetch.FiverrUpstreamError):
        fetch.classify(502, "", "x")
    assert not fetch.is_block(200, raw("gig_page_1500855.html.gz"))


def test_the_bot_managers_words_inside_a_real_answer_are_not_a_block():
    # the suggestions route echoes the query
    for query in ("it needs a human touch", "px-captcha"):
        body = json.dumps({"query": query, "suggestions": [], "users_suggestions": []})
        assert fetch.classify(200, body, "x") == body
    reviews = fixture("gig_reviews_page_1.json")
    reviews["reviews"][0]["comment"] = "The AI draft was flat. It needs a human touch, and she gave it one."
    assert not fetch.is_block(200, json.dumps(reviews))
    # a gig page writes the gig's title in its head
    gig_page = raw("gig_page_1500855.html.gz")
    assert "<title>Logo designing by Rejyms" in gig_page[:6000]
    assert not fetch.is_block(200, gig_page.replace("<title>Logo designing", "<title>It needs a human touch: logo designing", 1))
    # the bot manager's own JSON and page still are, under any status
    assert fetch.is_block(200, '{"appId":"PXK3bezZfO","blockScript":"/K3bezZfO/captcha/captcha.js"}')
    assert fetch.is_block(200, raw("blocked_page.html"))


def test_calls_go_out_as_a_navigation_in_usd():
    headers = fetch.NAVIGATION_HEADERS
    assert headers["sec-fetch-mode"] == "navigate" and headers["sec-fetch-dest"] == "document"
    assert headers["cookie"] == "logged_out_currency=USD"
    assert "x-requested-with" not in headers and "user-agent" not in headers and "accept-language" not in headers


class Answer:
    def __init__(self, status=200, text=""):
        self.status_code, self.text = status, text


class Wire:
    """fetch's sessions replaced: answers in order, every request recorded with its exit."""

    def __init__(self, monkeypatch, *answers):
        self.answers, self.sent, self.dropped = list(answers), [], []
        wire = self

        class Session:
            def __init__(self, exit_):
                self.exit, self.cookies = exit_, {"seen": "1"}

            def get(self, url, headers=None, timeout=None):
                wire.sent.append({"exit": self.exit, "url": url, "headers": headers, "timeout": timeout,
                                  "cookies": dict(self.cookies)})
                answer = wire.answers.pop(0)
                if isinstance(answer, Exception):
                    raise answer
                return answer

        monkeypatch.setattr(fetch, "_session", Session)
        monkeypatch.setattr(fetch, "_drop_session", self.dropped.append)
        monkeypatch.setattr(fetch.retry.time, "sleep", lambda seconds: None)


def test_urls_and_params(monkeypatch):
    wire = Wire(monkeypatch, Answer(text="a"), Answer(text="b"), Answer(text="c"), Answer(text='{"reviews": []}'),
                Answer(text='{"suggestions": []}'))
    fetch.fetch_search({"query": "logo design", "page": 2, "ref": "seller_level:top_rated_seller,na|delivery_time:3",
                        "filter": "new", "sub_category": None})
    fetch.fetch_category("graphics-design/creative-logo-design", {"page": None})
    fetch.fetch_gig("logocraftz/create-modern-logo")
    assert fetch.fetch_gig_reviews("417735249", {"sort_by": "recent", "filter_by": None}) == {"reviews": []}
    assert fetch.fetch_suggestions("web dev") == {"suggestions": []}
    urls = [s["url"] for s in wire.sent]
    assert urls[0] == ("https://www.fiverr.com/search/gigs?query=logo%20design&page=2"
                       "&ref=seller_level%3Atop_rated_seller%2Cna%7Cdelivery_time%3A3&filter=new")
    assert urls[1] == "https://www.fiverr.com/categories/graphics-design/creative-logo-design"
    assert urls[2] == "https://www.fiverr.com/logocraftz/create-modern-logo"
    assert urls[3] == "https://www.fiverr.com/gig_page/api/fetch_reviews/417735249?gig_id=417735249&sort_by=recent"
    assert urls[4] == "https://www.fiverr.com/search/omnibox?query=web%20dev"
    assert all(s["headers"] is fetch.NAVIGATION_HEADERS for s in wire.sent)
    assert all(s["cookies"] == {} for s in wire.sent)       # nothing an earlier answer set is sent back


@hosted_only
def test_a_refusal_moves_down_the_ladder(monkeypatch):
    monkeypatch.setattr(config, "FIVERR_EXIT", "direct")
    monkeypatch.setattr(config, "FIVERR_FALLBACK_EXITS", ("gateway", "datacenter"))
    monkeypatch.setattr(config, "FIVERR_LISTING_EXIT", "gateway:in")
    monkeypatch.setattr(config, "FIVERR_LISTING_FALLBACK_EXITS", ("in", "datacenter"))
    wire = Wire(monkeypatch, Answer(403, raw("blocked_page.html")), ConnectionError("cut"), Answer(text="gig"))
    assert fetch.fetch_gig("a/b") == "gig"
    assert [s["exit"] for s in wire.sent] == ["direct", "gateway", "datacenter"]
    assert wire.dropped == ["direct", "gateway"]
    assert wire.sent[1]["timeout"] == fetch.GATEWAY_TIMEOUT and wire.sent[0]["timeout"] == fetch.PAGE_TIMEOUT
    # a listing rides its own ladder; once it is used up the last exit is tried again
    wire = Wire(monkeypatch, *[Answer(403, raw("blocked_page.html"))] * config.MAX_RETRIES)
    with pytest.raises(fetch.FiverrBlocked):
        fetch.fetch_search({"query": "logo"})
    expected = ["gateway:in", "in", "datacenter"] + ["datacenter"] * config.MAX_RETRIES
    assert [s["exit"] for s in wire.sent] == expected[:config.MAX_RETRIES]


@hosted_only
def test_a_bad_minute_on_the_india_exits_answers_from_the_datacenter_exit(monkeypatch):
    assert fetch._exits(fetch.LISTING) == ["gateway:in", "in", "datacenter"]        # the service's own ladder
    blocked = Answer(403, raw("blocked_page.html"))
    wire = Wire(monkeypatch, blocked, blocked, Answer(text=page("search_with_promoted_rows.json.gz")))
    props = parsers.page_props(fetch.fetch_search({"query": "logo"}))
    assert [s["exit"] for s in wire.sent] == ["gateway:in", "in", "datacenter"]
    assert len(parsers.parse_listing(props, 1, 11)["results"]) == 28                # a shorter page, not a 502
    # while the India gateway is set aside the walk starts on residential and still ends on the datacenter exit
    monkeypatch.setattr(config, "FIVERR_HOLD_AFTER_REFUSALS", 1)
    wire = Wire(monkeypatch, blocked, Answer(text="in"), blocked, Answer(text="datacenter"))
    assert fetch.fetch_search({"query": "first"}) == "in"
    assert fetch.fetch_search({"query": "second"}) == "datacenter"
    assert [s["exit"] for s in wire.sent] == ["gateway:in", "in", "in", "datacenter"]


@hosted_only
def test_an_exit_refused_in_a_row_is_set_aside(monkeypatch):
    monkeypatch.setattr(config, "FIVERR_EXIT", "direct")
    monkeypatch.setattr(config, "FIVERR_FALLBACK_EXITS", ("gateway", "datacenter"))
    monkeypatch.setattr(config, "FIVERR_HOLD_AFTER_REFUSALS", 2)
    monkeypatch.setattr(config, "FIVERR_BLOCK_HOLD_S", 600)
    blocked = Answer(403, raw("blocked_page.html"))
    wire = Wire(monkeypatch, blocked, Answer(text="a"), blocked, Answer(text="b"), Answer(text="c"), blocked, Answer(text="d"))
    assert [fetch.fetch_gig("a/b"), fetch.fetch_gig("a/c")] == ["a", "b"]
    assert [s["exit"] for s in wire.sent] == ["direct", "gateway", "direct", "gateway"]
    # two refusals in a row: the next calls start on the gateway, and walk on from there
    assert fetch.fetch_gig("a/d") == "c" and fetch.fetch_seller("x") == "d"
    assert [s["exit"] for s in wire.sent[4:]] == ["gateway", "gateway", "datacenter"]
    # the listing ladder is counted on its own, and the hold ends
    wire = Wire(monkeypatch, Answer(text="listing"))
    fetch.fetch_search({"query": "logo"})
    assert wire.sent[0]["exit"] == config.FIVERR_LISTING_EXIT
    monkeypatch.setattr(fetch.time, "time", lambda: 10 ** 10)
    wire = Wire(monkeypatch, Answer(text="e"))
    fetch.fetch_gig("a/e")
    assert wire.sent[0]["exit"] == "direct"


@hosted_only
def test_a_pass_ends_the_run_of_refusals_and_other_failures_do_not_count(monkeypatch):
    monkeypatch.setattr(config, "FIVERR_EXIT", "direct")
    monkeypatch.setattr(config, "FIVERR_FALLBACK_EXITS", ("gateway",))
    monkeypatch.setattr(config, "FIVERR_HOLD_AFTER_REFUSALS", 2)
    blocked = Answer(403, raw("blocked_page.html"))
    wire = Wire(monkeypatch, blocked, Answer(text="a"), Answer(text="b"), ConnectionError("cut"), Answer(text="c"),
                blocked, Answer(text="d"), Answer(text="e"))
    for gig in ("a/a", "a/b", "a/c", "a/d", "a/e"):
        fetch.fetch_gig(gig)
    assert [s["exit"] for s in wire.sent] == ["direct", "gateway", "direct", "direct", "gateway", "direct", "gateway", "direct"]


@hosted_only
def test_a_not_found_answer_ends_the_run_of_refusals(monkeypatch):
    monkeypatch.setattr(config, "FIVERR_EXIT", "direct")
    monkeypatch.setattr(config, "FIVERR_FALLBACK_EXITS", ("gateway",))
    monkeypatch.setattr(config, "FIVERR_HOLD_AFTER_REFUSALS", 2)
    blocked = Answer(403, raw("blocked_page.html"))
    wire = Wire(monkeypatch, blocked, Answer(text="a"), Answer(404, raw("page_not_found_404.html")), blocked,
                Answer(text="b"), Answer(text="c"))
    fetch.fetch_gig("a/a")
    with pytest.raises(fetch.FiverrNotFound):       # the site's own answer on the first exit: it was let in
        fetch.fetch_seller("zzqqnotaseller98765")
    fetch.fetch_gig("a/b")
    fetch.fetch_gig("a/c")
    assert [s["exit"] for s in wire.sent] == ["direct", "gateway", "direct", "direct", "gateway", "direct"]


def test_not_found_and_bad_request_are_final(monkeypatch):
    wire = Wire(monkeypatch, Answer(404, raw("page_not_found_404.html")))
    with pytest.raises(fetch.FiverrNotFound):
        fetch.fetch_seller("zzqqnotaseller98765")
    assert len(wire.sent) == 1 and wire.dropped == []
    wire = Wire(monkeypatch, Answer(400, "{}"))
    with pytest.raises(fetch.FiverrBadRequest):
        fetch.fetch_gig_reviews("1", {})
    assert len(wire.sent) == 1


def test_a_page_where_json_was_expected_is_retried(monkeypatch):
    wire = Wire(monkeypatch, Answer(200, "<html><title>Login to Fiverr</title></html>"), Answer(text=raw("gig_reviews_none.json")))
    assert fetch.fetch_gig_reviews("516722324", {})["total_count"] == 0
    assert len(wire.sent) == 2
    assert fetch.fetch_json  # a 404 with a JSON body stays a NotFound
    wire = Wire(monkeypatch, Answer(404, raw("seller_reviews_not_found.json")))
    with pytest.raises(fetch.FiverrNotFound):
        fetch.fetch_seller_reviews_head("zzqqnotaseller98765", {})


# ---- the endpoints ---------------------------------------------------------------------------

class Site:
    """api.py's upstream calls answered from the fixtures; cached_call in memory."""

    def __init__(self, monkeypatch):
        self.calls, self.store = [], {}
        self.search = page("search_page_1.json.gz")
        self.category = page("category_page_1.json.gz")
        self.gig = page("gig_417735249.json.gz")
        self.seller = page("seller_pro_many_gigs.json.gz")
        self.gig_reviews = [fixture("gig_reviews_page_1.json"), fixture("gig_reviews_page_2.json"),
                            fixture("gig_reviews_last_page.json")]
        self.seller_head = fixture("seller_reviews_first_page.json")
        self.seller_next = [fixture("seller_reviews_page_2.json"), fixture("gig_reviews_last_page.json")]
        for name in ("fetch_search", "fetch_category", "fetch_gig", "fetch_seller", "fetch_gig_reviews",
                     "fetch_seller_reviews_head", "fetch_seller_reviews", "fetch_category_tree", "fetch_category_ids",
                     "fetch_suggestions"):
            monkeypatch.setattr(fetch, name, getattr(self, name))
        monkeypatch.setattr(api, "cached_call", self.cache)

    def cache(self, namespace, data, fn, ttl):
        key = (namespace, json.dumps(data, sort_keys=True, default=str))
        if key not in self.store:
            result = fn(**data)
            if isinstance(result, DontCache):       # answered, not stored (cache.cached_call)
                return result.data
            self.store[key] = result
        return self.store[key]

    def _answer(self, value):
        if isinstance(value, Exception):
            raise value
        return value

    def fetch_search(self, params):
        self.calls.append(("search", params))
        return self._answer(self.search)

    def fetch_category(self, category, params):
        self.calls.append(("category", category, params))
        return self._answer(self.category)

    def fetch_gig(self, gig):
        self.calls.append(("gig", gig))
        return self._answer(self.gig)

    def fetch_seller(self, seller):
        self.calls.append(("seller", seller))
        return self._answer(self.seller)

    def fetch_gig_reviews(self, gig_id, params):
        self.calls.append(("gig_reviews", gig_id, params))
        return self._answer(self.gig_reviews.pop(0))

    def fetch_seller_reviews_head(self, username, params):
        self.calls.append(("seller_head", username, params))
        return self._answer(self.seller_head)

    def fetch_seller_reviews(self, user_id, params):
        self.calls.append(("seller_reviews", user_id, params))
        return self._answer(self.seller_next.pop(0))

    def fetch_category_tree(self):
        self.calls.append(("tree",))
        return fixture("categories_tree.json")

    def fetch_category_ids(self):
        self.calls.append(("ids",))
        return self._answer(fixture("categories_navigation_config.json.gz"))

    def fetch_suggestions(self, query):
        self.calls.append(("suggestions", query))
        return fixture("suggestions_logo.json")


SEARCH = {"query": "logo design", "page": 1, "sort": None, "seller_level": None, "seller_country": None,
          "seller_language": None, "delivery_time": None, "min_price": None, "max_price": None, "pro": None,
          "online": None, "hourly": None, "agency": None, "attributes": None, "sub_category": None,
          "nested_sub_category": None}
CATEGORY = {k: v for k, v in SEARCH.items() if k not in ("query", "sub_category")}


def test_search_answer_and_cache(monkeypatch):
    site = Site(monkeypatch)
    answer = api.gigs_search(**SEARCH)
    assert list(answer)[:3] == ["query", "corrected_query", "sort"]
    assert answer["query"] == "logo design" and answer["corrected_query"] is None and len(answer["results"]) == 48
    assert answer["pagination"] == {"page": 1, "items_per_page": 48, "total_pages": 11, "total_count": 169355}
    assert site.calls == [("search", {"query": "logo design", "sub_category": None, "source": None, "ref": None,
                                      "filter": None, "nested_sub_category": None, "page": None})]
    api.gigs_search(**SEARCH)
    assert len(site.calls) == 1


def test_search_sends_every_filter_as_the_site_does(monkeypatch):
    site = Site(monkeypatch)
    site.search = page("search_attributes.json.gz")
    api.gigs_search(**{**SEARCH, "sort": "rating", "seller_level": ["top_rated_seller", "na"], "seller_country": ["US", "GB"],
                       "seller_language": ["es"], "delivery_time": "3", "min_price": 20.0, "pro": True, "online": True,
                       "hourly": True, "agency": True, "attributes": {"logo_type": ["mascot", "emblem"], "style": ["retro"]},
                       "sub_category": 49, "page": 2})
    params = site.calls[0][1]
    assert params["ref"] == ("seller_level:top_rated_seller,na|seller_location:US,GB|seller_language:es|delivery_time:3"
                             "|gig_price_range:20,50000|pro:any|is_seller_online:true|has_hourly:true|is_agency:true"
                             "|logo_type:mascot,emblem|style:retro")
    assert params["filter"] == "rating" and params["page"] == 2 and params["sub_category"] == 49
    assert params["source"] == "drop_down_filters"
    site.calls.clear()
    api.gigs_search(**{**SEARCH, "max_price": 50.0, "attributes": {"style": ["retro"]}})
    assert site.calls[0][1]["ref"] == "gig_price_range:0,50|style:retro"


def test_an_attribute_fiverr_ignores_is_a_400(monkeypatch):
    site = Site(monkeypatch)
    site.search = page("search_attribute_unknown.json.gz")
    with pytest.raises(BadRequest, match="'notastyle' is not a value of 'style'. It takes: flat_minimalist, modern, retro"):
        api.gigs_search(**{**SEARCH, "attributes": {"style": ["notastyle"]}})
    with pytest.raises(BadRequest, match="no filter 'foo'. It takes: file_format, logo_type, style"):
        api.gigs_search(**{**SEARCH, "attributes": {"foo": ["bar"]}})


@pytest.mark.parametrize("answer", ["search_no_result.json.gz",                 # a visitor from India: no rows, no filters
                                    "search_no_result_promoted_only.json.gz"])  # elsewhere: nothing but ads
def test_attributes_on_a_search_with_no_result_answer_the_empty_list(monkeypatch, answer):
    site = Site(monkeypatch)
    site.search = page(answer)
    result = api.gigs_search(**{**SEARCH, "query": "zxqvwkjh pqlmzt", "attributes": {"style": ["retro"]}})
    assert result["results"] == [] and result["pagination"]["total_count"] == 0
    assert result["pagination"]["total_pages"] == 0 and result["corrected_query"] == "zxqvwkjh permit"
    assert site.calls[0][1]["ref"] == "style:retro"


def test_attributes_on_a_page_past_the_end_answer_the_empty_list(monkeypatch):
    site = Site(monkeypatch)
    site.search = site.category = page("search_past_end.json.gz")
    assert api.gigs_search(**{**SEARCH, "attributes": {"style": ["retro"]}, "page": 9})["results"] == []
    assert api.categories_gigs(category="graphics-design/creative-logo-design",
                               **{**CATEGORY, "attributes": {"style": ["retro"]}, "page": 9})["results"] == []


def test_a_page_with_ads_is_answered_but_not_kept(monkeypatch):
    monkeypatch.setattr(config, "FIVERR_LISTING_FALLBACK_EXITS", ("in", "datacenter"))
    site = Site(monkeypatch)
    site.search = site.category = page("search_with_promoted_rows.json.gz")
    answer = api.gigs_search(**SEARCH)
    assert len(answer["results"]) == 28 and all(r["id"] for r in answer["results"])
    api.gigs_search(**SEARCH)
    assert len(site.calls) == 2                     # the next call asks for the full page
    site.search = page("search_page_1.json.gz")
    assert len(api.gigs_search(**SEARCH)["results"]) == 48
    api.gigs_search(**SEARCH)
    assert len(site.calls) == 3                     # the full page is kept
    site.calls.clear()
    for _ in range(2):
        assert len(api.categories_gigs(category="graphics-design/creative-logo-design", **CATEGORY)["results"]) == 28
    assert len(site.calls) == 2


def test_a_copy_with_no_ad_free_exit_keeps_its_pages(monkeypatch):
    monkeypatch.setattr(config, "FIVERR_LISTING_FALLBACK_EXITS", ())
    site = Site(monkeypatch)
    site.search = page("search_with_promoted_rows.json.gz")
    for _ in range(2):
        assert len(api.gigs_search(**SEARCH)["results"]) == 28
    assert len(site.calls) == 1


def test_search_pages_past_the_end_are_empty(monkeypatch):
    site = Site(monkeypatch)
    answer = api.gigs_search(**{**SEARCH, "page": 12})
    assert answer["results"] == [] and answer["pagination"]["page"] == 12 and site.calls == []   # Fiverr stops at 11
    site.search = fetch.FiverrNotFound("search not found")
    assert api.gigs_search(**{**SEARCH, "query": "rare", "page": 4})["results"] == []
    with pytest.raises(NotFound):
        api.gigs_search(**{**SEARCH, "query": "other"})
    site.search = page("search_past_end.json.gz")
    assert api.gigs_search(**{**SEARCH, "query": "third", "page": 3})["pagination"]["total_count"] == 0


def test_search_no_result_and_unknown_sub_category(monkeypatch):
    site = Site(monkeypatch)
    site.search = page("search_no_result.json.gz")
    answer = api.gigs_search(**{**SEARCH, "query": "zxqvwkjh pqlmzt"})
    assert answer["results"] == [] and answer["corrected_query"] == "zxqvwkjh permit"
    assert answer["pagination"]["total_pages"] == 0
    with pytest.raises(NotFound, match="sub_category 999999 not found"):
        api.gigs_search(**{**SEARCH, "sub_category": 999999})
    site.search = page("search_page_1.json.gz")
    with pytest.raises(NotFound, match="nested_sub_category 2609 not found"):
        api.gigs_search(**{**SEARCH, "sub_category": 49, "nested_sub_category": 2609})


def test_a_listing_in_another_currency_is_an_upstream_error(monkeypatch):
    site = Site(monkeypatch)
    props = fixture("search_page_1.json.gz")
    props["currency"]["name"] = "INR"
    site.search = PROPS % json.dumps(props)
    with pytest.raises(UpstreamError, match="another currency"):
        api.gigs_search(**SEARCH)


def test_category_gigs(monkeypatch):
    site = Site(monkeypatch)
    answer = api.categories_gigs(category="graphics-design/creative-logo-design", **CATEGORY)
    assert "query" not in answer and answer["sub_category"]["slug"] == "creative-logo-design"
    assert answer["pagination"]["total_pages"] == 21 and len(answer["results"]) == 48
    assert site.calls[0][:2] == ("category", "graphics-design/creative-logo-design")
    assert api.categories_gigs(category="graphics-design/creative-logo-design", **{**CATEGORY, "page": 22})["results"] == []
    assert len(site.calls) == 1
    site.category = page("category_nested.json.gz")
    nested = api.categories_gigs(category="programming-tech/website-development/wordpress-development", **CATEGORY)
    assert nested["nested_sub_category"]["id"] == 2609


def test_unknown_categories_are_404(monkeypatch):
    site = Site(monkeypatch)
    site.category = page("category_unknown.json.gz")            # the category's landing page
    with pytest.raises(NotFound, match="category graphics-design/not-a-real-one not found"):
        api.categories_gigs(category="graphics-design/not-a-real-one", **CATEGORY)
    site.category = page("category_page_1.json.gz")             # a third segment Fiverr ignores
    with pytest.raises(NotFound, match="'nope' is not a nested sub-category"):
        api.categories_gigs(category="graphics-design/creative-logo-design/nope", **CATEGORY)
    site.category = fetch.FiverrNotFound("gone")
    with pytest.raises(NotFound):
        api.categories_gigs(category="zz/yy", **CATEGORY)


def test_gig_details_and_not_found(monkeypatch):
    site = Site(monkeypatch)
    gig = api.gigs_details(gig="logocraftz/create-modern-minimalist-business-logo-design")
    assert gig["id"] == 417735249 and gig["seller"]["full_name"] == "Logo Craftz"
    api.gigs_details(gig="logocraftz/create-modern-minimalist-business-logo-design")
    assert len(site.calls) == 1
    for not_a_gig in ("gig_not_found_seller_page.json.gz", "gig_not_found_home_page.json.gz"):
        site.gig = page(not_a_gig)
        with pytest.raises(NotFound, match="gig logocraftz/nope not found"):
            api.gigs_details(gig="logocraftz/nope")
    monkeypatch.setattr(config, "FIVERR_RETURN_FULL_NAME", False)
    site.gig = page("gig_417735249.json.gz")
    assert api.gigs_details(gig="logocraftz/again")["seller"]["full_name"] is None


def test_gig_reviews_chain_five_a_call(monkeypatch):
    site = Site(monkeypatch)
    answer = api.gigs_reviews(gig="417735249", sort="relevant", limit=10, cursor=None, stars=None, business_only=None)
    assert list(answer) == ["gig_id", "sort", "stars", "is_business_only", "total_count", "count", "reviews", "next_cursor"]
    assert answer["gig_id"] == 417735249 and answer["count"] == 10 and answer["total_count"] == 394
    assert len({r["id"] for r in answer["reviews"]}) == 10
    assert answer["next_cursor"] == "6aa79f1118ced544118572f1~0.510236"
    assert site.calls[0] == ("gig_reviews", "417735249", {"sort_by": "relevant", "filter_by": None, "average_valuation_value": None})
    assert site.calls[1][2]["last_review_id"] == "6aa2aa3fb0246a7e6cffa232" and site.calls[1][2]["last_score"] == "0.70956004"
    assert [c[0] for c in site.calls] == ["gig_reviews", "gig_reviews"]        # a numeric id needs no gig page


def test_gig_reviews_cut_inside_a_page_and_end_of_list(monkeypatch):
    site = Site(monkeypatch)
    answer = api.gigs_reviews(gig="417735249", sort="relevant", limit=7, cursor=None, stars=4, business_only=True)
    assert answer["count"] == 7 and answer["stars"] == 4 and answer["is_business_only"] is True
    assert site.calls[0][2]["filter_by"] == "business,breakdown" and site.calls[0][2]["average_valuation_value"] == 4
    seventh = fixture("gig_reviews_page_2.json")["reviews"][1]
    assert answer["next_cursor"] == refs.review_cursor(seventh["id"], seventh.get("score"))
    site = Site(monkeypatch)
    site.gig_reviews = [fixture("gig_reviews_last_page.json")]
    answer = api.gigs_reviews(gig="505200827", sort="recent", limit=20, cursor="6aa2aa3fb0246a7e6cffa232~0", stars=None,
                              business_only=None)
    assert answer["count"] == 3 and answer["next_cursor"] is None
    assert site.calls[0][2]["last_score"] == "0" and site.calls[0][2]["sort_by"] == "recent"


def test_gig_reviews_by_link_none_unknown_and_partial(monkeypatch):
    site = Site(monkeypatch)
    api.gigs_reviews(gig="logocraftz/create-modern", sort="relevant", limit=5, cursor=None, stars=None, business_only=None)
    assert [c[0] for c in site.calls] == ["gig", "gig_reviews"] and site.calls[1][1] == "417735249"
    site = Site(monkeypatch)
    site.gig_reviews = [fixture("gig_reviews_none.json")]
    answer = api.gigs_reviews(gig="516722324", sort="relevant", limit=20, cursor=None, stars=None, business_only=None)
    assert answer["reviews"] == [] and answer["total_count"] == 0 and answer["next_cursor"] is None
    site.gig_reviews = [fixture("gig_reviews_not_found.json")]
    with pytest.raises(NotFound, match="gig 999999999999 not found"):
        api.gigs_reviews(gig="999999999999", sort="relevant", limit=20, cursor=None, stars=None, business_only=None)
    # the second upstream page is refused: the first five are still answered, with their cursor
    site.gig_reviews = [fixture("gig_reviews_page_1.json"), fetch.FiverrBlocked("refused")]
    answer = api.gigs_reviews(gig="417735249", sort="relevant", limit=20, cursor=None, stars=None, business_only=None)
    assert answer["count"] == 5 and answer["next_cursor"] == "6aa2aa3fb0246a7e6cffa232~0.70956004"
    site.gig_reviews = [fetch.FiverrBlocked("refused")]
    with pytest.raises(Blocked):
        api.gigs_reviews(gig="1", sort="relevant", limit=20, cursor=None, stars=None, business_only=None)


def test_seller_details_and_gigs_share_one_page(monkeypatch):
    site = Site(monkeypatch)
    details = api.sellers_details(seller="loftydesignshop")
    assert "gigs" not in details and details["gig_count"] == 13 and details["timezone"] == "Asia/Kolkata"
    gigs = api.sellers_gigs(seller="loftydesignshop")
    assert list(gigs) == ["seller", "count", "gigs"] and gigs["count"] == 13
    assert gigs["seller"] == {"id": 70944075, "username": "loftydesignshop", "display_name": "Alpa",
                              "link": "https://www.fiverr.com/loftydesignshop"}
    assert site.calls == [("seller", "loftydesignshop")]
    site.seller = fetch.FiverrNotFound("seller zz not found")
    with pytest.raises(NotFound):
        api.sellers_details(seller="zz")
    site.seller = page("gig_not_found_home_page.json.gz")
    with pytest.raises(NotFound, match="seller yy not found"):
        api.sellers_gigs(seller="yy")


def test_seller_reviews(monkeypatch):
    site = Site(monkeypatch)
    answer = api.sellers_reviews(seller="logocraftz", sort="relevant", limit=10, cursor=None)
    assert list(answer) == ["seller", "sort", "rating", "rating_breakdown", "rating_details", "total_count", "count",
                            "reviews", "next_cursor"]
    assert answer["seller"] == {"id": 102898503, "username": "logocraftz", "link": "https://www.fiverr.com/logocraftz"}
    assert answer["rating"] == 4.9 and answer["total_count"] == 400 and answer["count"] == 10
    assert site.calls == [("seller_head", "logocraftz", {"sort_by": "relevant"}),
                          ("seller_reviews", 102898503, {"sort_by": "relevant", "last_star_rating_id": "6aa2aa3fb0246a7e6cffa232",
                                                         "last_review_id": "6aa2aa3fb0246a7e6cffa232", "last_score": "0.70956004"})]
    # the next page reuses the cached head for the seller's id and rating
    more = api.sellers_reviews(seller="logocraftz", sort="relevant", limit=5, cursor=answer["next_cursor"])
    assert more["count"] == 3 and more["next_cursor"] is None and more["rating"] == 4.9
    assert [c[0] for c in site.calls] == ["seller_head", "seller_reviews", "seller_reviews"]


def test_seller_reviews_unknown_and_agency(monkeypatch):
    site = Site(monkeypatch)
    site.seller_head = fetch.FiverrNotFound("gone")
    with pytest.raises(NotFound, match="seller zz not found"):
        api.sellers_reviews(seller="zz", sort="relevant", limit=20, cursor=None)
    site = Site(monkeypatch)
    site.seller = page("seller_agency.json.gz")
    site.seller_head = fixture("seller_reviews_agency.json")
    answer = api.sellers_reviews(seller="agencies/colordesk", sort="relevant", limit=5, cursor=None)
    assert answer["seller"]["username"] == "colordesk_in" and answer["count"] == 5
    assert site.calls[0] == ("seller", "agencies/colordesk") and site.calls[1][:2] == ("seller_head", "colordesk_in")


def test_categories_list_and_suggestions(monkeypatch):
    site = Site(monkeypatch)
    answer = api.categories_list()
    assert answer["count"] == 12 and answer["categories"][0]["id"] == 3
    monkeypatch.setattr(site, "_answer", lambda value: (_ for _ in ()).throw(fetch.FiverrBlocked("refused")))
    site.store.clear()
    assert api.categories_list()["categories"][0]["id"] is None       # the tree alone, ids null
    assert site.store == {}                                           # and not kept: the next call asks for the ids again
    suggestions = api.gigs_suggestions(query="logo")
    assert suggestions == {"query": "logo", "count": 8, "suggestions": suggestions["suggestions"], "sellers": ["logos_designer6"]}
