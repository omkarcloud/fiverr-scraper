"""The /fiverr/* endpoint functions (route_glue's route_table calls them with
the schema's loaded kwargs).

Two page parses are cached once and sliced: the gig record (gigs/details,
and the gig id gigs/reviews needs for a link) and the seller record
(sellers/details, sellers/gigs). Reviews come 5 a call from Fiverr, so a
reviews answer chains the calls it needs and hands back `next_cursor`.
"""
import config
from cache import DontCache, cached_call
from fiverr import cache_config as ttl
from fiverr import fetch, parsers, refs
from fiverr.fetch import FiverrBadRequest, FiverrNotFound, FiverrUpstreamError

REVIEWS_PER_CALL = 5      # Fiverr's own page of reviews; page_size is ignored


# ---- listings: gigs/search and categories/gigs ---------------------------------------------

def _ref(filters):
    """The site's `ref` param: name:value,value|name:value."""
    parts = []
    for name, value in filters:
        if value in (None, "", []):
            continue
        parts.append(f"{name}:{','.join(str(v) for v in value) if isinstance(value, list) else value}")
    return "|".join(parts) or None


def _listing_params(data):
    """The validated params of a listing -> the site's query params."""
    low, high = data.get("min_price"), data.get("max_price")
    price = None
    if low is not None or high is not None:
        price = [int(low or 0), int(high if high is not None else refs.PRICE_CEILING)]
    filters = [
        ("seller_level", data.get("seller_level")),
        ("seller_location", data.get("seller_country")),
        ("seller_language", data.get("seller_language")),
        ("delivery_time", data.get("delivery_time")),
        ("gig_price_range", price),
        ("pro", "any" if data.get("pro") else None),       # the site's own token; `pro:pro` is ignored
        ("is_seller_online", "true" if data.get("online") else None),
        ("has_hourly", "true" if data.get("hourly") else None),
        ("is_agency", "true" if data.get("agency") else None),
        *sorted((data.get("attributes") or {}).items()),
    ]
    ref = _ref(filters)
    page = data.get("page") or 1
    return {
        "source": "drop_down_filters" if ref else None,
        "ref": ref,
        "filter": data.get("sort"),
        "nested_sub_category": data.get("nested_sub_category"),
        "page": page if page > 1 else None,
    }


def _check_attributes(props, attributes):
    """A category filter or a value Fiverr does not know is answered with the
    unfiltered list: refuse it instead, naming what the listing takes. Called
    for a listing with rows only: an empty one has ignored nothing, and a
    search with no result offers no filter to check against."""
    if not attributes:
        return
    applied = parsers.selected_filters(props)
    offered = {a["name"]: [o["value"] for o in a["options"]] for a in parsers.listing_attributes(props)}
    for name, values in attributes.items():
        if name not in applied and name not in offered:
            known = ", ".join(sorted(offered)) or "none"
            raise FiverrBadRequest(f"attributes: this listing has no filter '{name}'. It takes: {known}.")
        missing = [v for v in values if v not in applied.get(name, ())]
        if missing:
            known = ", ".join(offered.get(name) or []) or "none"
            raise FiverrBadRequest(f"attributes: '{missing[0]}' is not a value of '{name}'. It takes: {known}.")


def _empty_listing(page):
    return {"sort": None, "category": None, "sub_category": None, "nested_sub_category": None,
            "nested_sub_categories": [], "attributes": [], "results": [],
            "pagination": {"page": page, "items_per_page": refs.LISTING_PAGE_SIZE, "total_pages": 0, "total_count": 0}}


def _listing(fetch_html, data, max_page, what):
    """One listing page: fetch, check it is the listing that was asked for, parse."""
    page = data.get("page") or 1
    if page > max_page:
        return None, _empty_listing(page)       # Fiverr shows no page past this one
    try:
        html = fetch_html(_listing_params(data))
    except FiverrNotFound:
        if page > 1:
            return None, _empty_listing(page)   # far past the end the site answers 404
        raise
    props = parsers.page_props(html)
    if not parsers.is_listing(props):
        raise FiverrNotFound(f"{what} not found")
    if parsers.listing_currency(props) != parsers.CURRENCY:
        raise FiverrUpstreamError("Fiverr answered in another currency than USD")
    listing = parsers.parse_listing(props, page, max_page)
    if listing["results"]:
        _check_attributes(props, data.get("attributes"))
    nested = data.get("nested_sub_category")
    if nested and (listing["nested_sub_category"] or {}).get("id") != nested:
        raise FiverrNotFound(f"nested_sub_category {nested} not found in this sub-category")
    return props, listing


def _answered(props, answer):
    """A page with ads came from the exit behind the ad-free ones and holds fewer
    gigs (the ads are left out). It is answered but not kept, so the next call asks
    for the full page. A copy of this scraper with no ad-free exit keeps its pages."""
    if props is not None and config.FIVERR_LISTING_FALLBACK_EXITS and parsers.has_promoted_rows(props):
        return DontCache(answer)
    return answer


def _search(**data):
    query = data["query"]
    sub_category = data.get("sub_category")
    params = {"query": query, "sub_category": sub_category}
    props, listing = _listing(lambda extra: fetch.fetch_search({**params, **extra}), data,
                              refs.SEARCH_MAX_PAGE, f"search {query!r}")
    if props is not None and sub_category and (listing["sub_category"] or {}).get("id") != sub_category:
        # a sub-category Fiverr does not know is answered with an empty list and no category
        raise FiverrNotFound(f"sub_category {sub_category} not found")
    return _answered(props, {"query": query, "corrected_query": parsers.corrected_query(props) if props else None, **listing})


def gigs_search(**data):
    return cached_call("fiverr.gigs_search", data, _search, ttl.SEARCH_CACHE)


def _category_gigs(**data):
    category = data["category"]
    segments = category.split("/")
    props, listing = _listing(lambda extra: fetch.fetch_category(category, extra), data,
                              refs.CATEGORY_MAX_PAGE, f"category {category}")
    if props is not None and len(segments) == 3 and not listing["nested_sub_category"]:
        # a third segment the site does not know is answered with the whole sub-category
        raise FiverrNotFound(f"category {category} not found: '{segments[2]}' is not a nested sub-category "
                             f"of {segments[0]}/{segments[1]}")
    return _answered(props, listing)


def categories_gigs(**data):
    return cached_call("fiverr.categories_gigs", data, _category_gigs, ttl.CATEGORY_GIGS_CACHE)


# ---- gigs/details ---------------------------------------------------------------------------

def _gig_record(gig):
    record = parsers.parse_gig(parsers.page_props(fetch.fetch_gig(gig)), full_name=config.FIVERR_RETURN_FULL_NAME)
    if record is None:      # an unknown slug answers the seller's page, an unknown seller the home page
        raise FiverrNotFound(f"gig {gig} not found")
    return record


def _record(gig):
    return cached_call("fiverr.gig", {"gig": gig}, _gig_record, ttl.GIG_CACHE)


def gigs_details(gig):
    return _record(gig)


# ---- reviews --------------------------------------------------------------------------------

def _chain(first_call, next_call, cursor, limit):
    """Reviews from 5-a-call upstream pages until `limit` -> (reviews, next_cursor, total);
    (None, None, None) when the first answer is not a reviews answer (an unknown id).
    `first_call()` answers the first page (no cursor), `next_call(cursor params)` any
    page. A page that fails after the first keeps what was read: a partial result."""
    reviews, after, total = [], [], None       # after[i]: the cursor behind reviews[i]
    while len(reviews) < limit:
        try:
            payload = first_call() if first_call is not None and not cursor else next_call(refs.cursor_params(cursor))
        except FiverrUpstreamError:
            if not reviews:
                raise
            break
        if not parsers.is_reviews(payload):
            if not reviews:
                return None, None, None
            break
        rows, cursor, page_total = parsers.parse_reviews(payload)
        total = page_total if page_total is not None else total
        reviews += rows
        after += parsers.review_cursors(payload)
        if not rows or not cursor:
            cursor = None
            break
    if len(reviews) > limit:                    # cut inside an upstream page: go on from the last row kept
        cursor = after[limit - 1]
    return reviews[:limit], cursor, total


def _gig_reviews(gig, sort, limit, cursor, stars, business_only):
    gig_id = gig if refs.is_gig_id(gig) else str(_record(gig)["id"])
    filter_by = ",".join(name for name, on in (("business", business_only), ("breakdown", stars)) if on)
    params = {"sort_by": sort, "filter_by": filter_by or None, "average_valuation_value": stars}
    call = lambda extra: fetch.fetch_gig_reviews(gig_id, {**params, **extra})   # noqa: E731
    reviews, next_cursor, total = _chain(None, call, cursor, limit)
    if reviews is None:
        raise FiverrNotFound(f"gig {gig} not found")
    return {"gig_id": int(gig_id), "sort": sort, "stars": stars, "is_business_only": bool(business_only),
            "total_count": total, "count": len(reviews), "reviews": reviews, "next_cursor": next_cursor}


def gigs_reviews(**data):
    return cached_call("fiverr.gigs_reviews", data, _gig_reviews, ttl.REVIEWS_CACHE)


# ---- sellers --------------------------------------------------------------------------------

def _seller_record(seller):
    record = parsers.parse_seller(parsers.page_props(fetch.fetch_seller(seller)))
    if record is None:
        raise FiverrNotFound(f"seller {seller} not found")
    return record


def _seller(seller):
    return cached_call("fiverr.seller", {"seller": seller}, _seller_record, ttl.SELLER_CACHE)


def sellers_details(seller):
    record = _seller(seller)
    return {key: value for key, value in record.items() if key != "gigs"}


def sellers_gigs(seller):
    record = _seller(seller)
    return {
        "seller": {"id": record["id"], "username": record["username"], "display_name": record["display_name"],
                   "link": record["link"]},
        "count": len(record["gigs"]),
        "gigs": record["gigs"],
    }


def _reviews_head(username, sort):
    """The seller's first reviews page: its numeric id, the rating summary and 5 reviews."""
    try:
        payload = fetch.fetch_seller_reviews_head(username, {"sort_by": sort})
    except FiverrNotFound:
        raise FiverrNotFound(f"seller {username} not found")
    if not parsers.is_reviews(payload) or not payload.get("user_id"):
        raise FiverrNotFound(f"seller {username} not found")
    return payload


def _seller_reviews(seller, sort, limit, cursor):
    username = _seller(seller)["username"] if seller.startswith("agencies/") else seller
    head = cached_call("fiverr.seller_reviews_head", {"username": username, "sort": sort}, _reviews_head,
                       ttl.SELLER_REVIEWS_HEAD_CACHE)
    user_id = head["user_id"]
    call = lambda extra: fetch.fetch_seller_reviews(user_id, {"sort_by": sort, **extra})   # noqa: E731
    reviews, next_cursor, total = _chain(lambda: head, call, cursor, limit)
    summary = parsers.rating_summary(head)
    return {
        "seller": {"id": int(user_id), "username": username, "link": refs.seller_link(username)},
        "sort": sort,
        "rating": summary["rating"],
        "rating_breakdown": summary["rating_breakdown"],
        "rating_details": summary["rating_details"],
        "total_count": summary["review_count"] if summary["review_count"] is not None else total,
        "count": len(reviews or []),
        "reviews": reviews or [],
        "next_cursor": next_cursor,
    }


def sellers_reviews(**data):
    return cached_call("fiverr.sellers_reviews", data, _seller_reviews, ttl.REVIEWS_CACHE)


# ---- categories/list and gigs/suggestions ----------------------------------------------------

def _categories():
    tree = fetch.fetch_category_tree()
    try:
        ids = fetch.fetch_category_ids()
    except FiverrUpstreamError:
        ids = None          # the tree alone still lists every category; the ids come back null
    categories = parsers.parse_categories(tree, ids)
    if not categories:
        raise FiverrUpstreamError("Fiverr's category tree came back empty")
    result = {"count": len(categories), "categories": categories}
    return DontCache(result) if ids is None else result     # answered without its ids, not kept for a day


def categories_list():
    return cached_call("fiverr.categories", {}, _categories, ttl.CATEGORIES_CACHE)


def _suggestions(query):
    suggestions, sellers = parsers.parse_suggestions(fetch.fetch_suggestions(query))
    return {"query": query, "count": len(suggestions), "suggestions": suggestions, "sellers": sellers}


def gigs_suggestions(**data):
    return cached_call("fiverr.suggestions", data, _suggestions, ttl.SUGGESTIONS_CACHE)
