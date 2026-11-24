"""Page data / JSON -> clean dicts for every /fiverr/* endpoint. Pure
functions, no I/O.

A Fiverr page carries its data as JSON in <script id="perseus-initial-props">
(page_props reads it); the listing, gig and seller parsers take that object.
The review, category and suggestion parsers take the JSON routes' answers.

Fixtures (fixtures/, captured 2026-11-21 through the exits, as a signed-out
visitor with logged_out_currency=USD; the pages' data is kept packed, one
full page as gig_page_1500855.html.gz):
  search_*.json.gz, category_*.json.gz   listing pages
  gig_*.json.gz                          gig pages (a Pro gig, one with a video,
                                         one with one package and no review, an
                                         old sparse one, the two not-found answers)
  seller_*.json.gz                       seller pages (a Pro seller with 13 gigs,
                                         a new seller, an agency)
  gig_reviews_*.json, seller_reviews_*.json, categories_*.json*, suggestions_*.json
  blocked_page.html, page_not_found_404.html

Units the site uses (kept out of the answers): a listing row's price is whole
USD, a package price and an hourly rate are cents, a package duration is
hours, a revision count of -1 means unlimited, joinedAt / memberSince are
epoch seconds, recentDelivery and a work experience's startDate / endDate
epoch milliseconds, a review's created_at an ISO time without a zone (UTC).

Left out on purpose: encrypted gig and order ids, review relevancy scores and
the reviewer's own review count (in the data, never shown to a visitor), ad
and tracking fields, and the requester's address the listing data echoes.
"""
import json
import math
import re

from fiverr import refs
from scraper_utils.dates import epoch_utc, iso_day, iso_utc
from scraper_utils.text import clean, html_to_text, multiline
from scraper_utils.values import as_dict, as_list, g, num, rating, to_int

CURRENCY = "USD"
PROMOTED = "promoted_gigs"      # a listing row that is an ad
PACKAGE_TIERS = {1: "basic", 2: "standard", 3: "premium"}

_PROPS_RE = re.compile(r'<script type="application/json" id="perseus-initial-props">\s*(.*?)\s*</script>', re.S)
_NUMBER_RE = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")


# ---- small helpers ---------------------------------------------------------------------

def page_props(html):
    """The page's own data (perseus-initial-props) -> dict; None when the page has none."""
    match = _PROPS_RE.search(html or "")
    if not match:
        return None
    try:
        props = json.loads(match.group(1))
    except ValueError:
        return None
    return props if isinstance(props, dict) else None


def _usd(cents):
    """Cents -> dollars (4000 -> 40, 1250 -> 12.5); None for a missing amount."""
    value = num(cents)
    if value is None:
        return None
    value = round(value / 100, 2)
    return int(value) if value == int(value) else value


def _id(value):
    """A positive id as an int; 0, None and junk -> None."""
    value = to_int(value)
    return value if value else None


def _date(epoch):
    """Epoch seconds -> 'YYYY-MM-DD'."""
    stamp = epoch_utc(to_int(epoch))
    return stamp[:10] if stamp else None


def _datetime_ms(epoch_ms):
    value = to_int(epoch_ms)
    return epoch_utc(value // 1000) if value else None


def _date_ms(epoch_ms):
    """Epoch milliseconds -> 'YYYY-MM-DD'."""
    stamp = _datetime_ms(epoch_ms)
    return stamp[:10] if stamp else None


# A work-history date is epoch milliseconds on most profiles and epoch seconds on
# some (bhaveshbandhiya, 2026-11-23), which read as milliseconds land in January
# 1970. A value that reads as seconds from 1900 to 2100 is seconds; any other is
# milliseconds (only a millisecond date within seven weeks of 1970-01-01 would
# read as seconds).
_EPOCH_1900 = -2208988800
_EPOCH_2100 = 4102444800


def _date_s_or_ms(epoch):
    """Epoch seconds or milliseconds -> 'YYYY-MM-DD'."""
    value = to_int(epoch)
    if value and _EPOCH_1900 <= value < _EPOCH_2100:
        return _date(value)
    return _date_ms(value)


def level_name(value):
    """Any spelling of a seller level the site uses -> top_rated / level_2 / level_1 / new."""
    if value is None:
        return None
    return refs.LEVEL_NAMES.get(str(value).strip().lower())


def _languages(rows):
    """[{code|name, level}] in either spelling -> [{code, level}] with the level as a word."""
    out = []
    for row in as_list(rows):
        code = clean(as_dict(row).get("code") or as_dict(row).get("name"))
        if not code:
            continue
        out.append({"code": code.lower(), "level": refs.LANGUAGE_LEVELS.get(as_dict(row).get("level"))})
    return out


def _image(value):
    """A media link; None for junk and for the site's "file no longer available" placeholder."""
    if not isinstance(value, str) or not value.startswith("http") or "/placeholders/file_no_longer_available" in value:
        return None
    return clean(value)


# ---- listing rows (search, category, a seller's gigs) -----------------------------------

def _row_agency(agency):
    agency = as_dict(agency)
    if not agency.get("slug"):
        return None
    return {
        "slug": agency.get("slug"),
        "link": refs.agency_link(agency.get("slug")),
        "established": to_int(agency.get("established")),
        "team_size": to_int(agency.get("employees_count")),
        "highlights": [h for h in (clean(x) for x in as_list(agency.get("highlights"))) if h],
        "image": _image(agency.get("banner_image_url")),
    }


def gig_row(item):
    """One gig of a listing or of a seller's page."""
    item = as_dict(item)
    recommended = as_dict(g(item, "packages", "recommended", default=None))
    images = [link for link in (_image(a.get("cloud_img_main_gig")) for a in as_list(item.get("assets"))
                                if isinstance(a, dict)) if link]
    videos = [link for link in (_image(a.get("stream_url")) for a in as_list(item.get("attachments"))
                                if isinstance(a, dict)) if link]
    seller_rating = as_dict(item.get("seller_rating"))
    return {
        "id": _id(item.get("gig_id") or item.get("gigId")),
        "title": clean(item.get("title")),
        "link": refs.gig_link(item.get("gig_url")),
        "price_from": num(item.get("price_i")) if item.get("price_i") is None else to_int(item.get("price_i")),
        "currency": CURRENCY,
        "delivery_days": to_int(recommended.get("duration")),
        "has_extra_fast": bool(item.get("extra_fast")),
        "package_count": to_int(item.get("num_of_packages")),
        "hourly_rate": _usd(item.get("hourly_rate")),
        "rating": rating(item.get("buying_review_rating")),
        "review_count": to_int(item.get("buying_review_rating_count")),
        "is_pro": bool(item.get("is_pro")),
        "is_fiverr_choice": bool(item.get("is_fiverr_choice") or item.get("type") == "fiverr_choice"),
        "is_featured": bool(item.get("is_featured")),
        "has_video": bool(videos),
        "has_subscription": bool(item.get("has_recurring_option")),
        "subscription_discounts": [d for d in (to_int(as_dict(o).get("discount_percentage"))
                                               for o in as_list(item.get("recurring_options"))) if d],
        "has_consultation": bool(item.get("offer_consultation")),
        "category_id": _id(item.get("category_id")),
        "sub_category_id": _id(item.get("sub_category_id")),
        "nested_sub_category_id": _id(item.get("nested_sub_category_id")),
        "image": images[0] if images else None,
        "images": images,
        "video": videos[0] if videos else None,
        "attributes": [{"name": m.get("type"), "values": [v for v in as_list(m.get("value")) if isinstance(v, str)]}
                       for m in as_list(item.get("metadata")) if isinstance(m, dict) and m.get("type")],
        "seller": {
            "id": _id(item.get("seller_id") or item.get("sellerId")),
            "username": clean(item.get("seller_name")),
            "display_name": clean(item.get("seller_display_name")),
            "link": refs.seller_link(clean(item.get("seller_name"))),
            "image": _image(item.get("seller_img")),
            "level": level_name(item.get("seller_level") or ""),
            "country_code": clean(item.get("seller_country")),
            "is_online": bool(item.get("seller_online")),
            "is_available": not item.get("is_seller_unavailable"),
            "rating": rating(seller_rating.get("score")),
            "rating_count": to_int(seller_rating.get("count")),
            "languages": _languages(item.get("seller_languages")),
            "agency": _row_agency(item.get("agency")),
        },
    }


def listing_rows(props):
    """The gigs of a listing page, ads left out."""
    return [gig_row(item) for item in as_list(as_dict(props).get("items"))
            if isinstance(item, dict) and (item.get("gig_id") or item.get("gigId")) and item.get("type") != PROMOTED]


def has_promoted_rows(props):
    """True for a listing page that carried ads: it was answered to a visitor outside India."""
    return any(isinstance(item, dict) and item.get("type") == PROMOTED for item in as_list(as_dict(props).get("items")))


def is_listing(props):
    """True for the data of a search or category listing page."""
    props = as_dict(props)
    return isinstance(props.get("items"), list) and isinstance(props.get("appData"), dict)


def selected_filters(props):
    """{filter name: {values}} the site says it applied. A filter or a value it does not
    know is echoed in the page but never listed here, and the rows come back unfiltered."""
    chosen = {}
    for row in as_list(g(as_dict(props), "appFilters", "selectedFilters", default=None)):
        if isinstance(row, dict) and row.get("id"):
            chosen.setdefault(row["id"], set())
            if row.get("value") is not None:
                chosen[row["id"]].add(str(row["value"]))
    return chosen


def listing_attributes(props):
    """The category's own filters of a listing (style, file format, ...): what `attributes` takes."""
    out = []
    for flt in as_list(g(as_dict(props), "appFilters", "filters", default=None)):
        if not isinstance(flt, dict) or flt.get("type") != "specific":
            continue
        name = flt.get("id")
        if not name or name in refs.OWN_PARAMS or name in refs.IGNORED_FILTERS:
            continue
        options = [{"value": str(o.get("id")), "label": clean(o.get("alias")), "count": to_int(o.get("count")),
                    "is_selected": bool(o.get("selected"))}
                   for o in as_list(flt.get("options")) if isinstance(o, dict) and o.get("id") not in (None, "")]
        if options:
            out.append({"name": name, "label": clean(flt.get("alias")), "options": options})
    return out


def _listing_categories(props):
    """(category, sub_category, nested_sub_category, nested_sub_categories) of a listing page."""
    sub = as_dict(props.get("subCategoryData"))
    top = as_dict(sub.get("category"))
    category = sub_category = nested = None
    if _id(top.get("id")):
        category = {"id": _id(top.get("id")), "name": clean(top.get("name")), "slug": clean(top.get("cached_slug")),
                    "link": refs.category_link(clean(top.get("cached_slug")))}
    if _id(sub.get("id")):
        sub_category = {"id": _id(sub.get("id")), "name": clean(sub.get("name")), "slug": clean(sub.get("cached_slug")),
                        "description": clean(sub.get("subtitle")),
                        "link": refs.category_link(clean(top.get("cached_slug")), clean(sub.get("cached_slug")))}
    nested_id = _id(g(props, "categoryIds", "nestedSubCategoryId", default=None))

    def nested_row(row):
        return {"id": _id(row.get("id")), "name": clean(row.get("name")), "slug": clean(row.get("cached_slug")),
                "link": refs.category_link(clean(top.get("cached_slug")), clean(sub.get("cached_slug")),
                                           clean(row.get("cached_slug")))}

    nested_all = [nested_row(row) for row in as_list(sub.get("nestedSubCategories")) if isinstance(row, dict) and _id(row.get("id"))]
    if nested_id:
        data = as_dict(sub.get("nestedSubCategoryData"))
        nested = nested_row(data) if _id(data.get("id")) else next((n for n in nested_all if n["id"] == nested_id), {"id": nested_id, "name": None, "slug": None, "link": None})
    return category, sub_category, nested, nested_all


def parse_listing(props, page, max_page):
    """A search or category listing page -> the answer's shared part: the sort, the
    categories, the category's own filters, the rows (ads left out) and the pagination."""
    props = as_dict(props)
    rows = listing_rows(props)
    pagination = as_dict(g(props, "appData", "pagination", default=None))
    total = to_int(pagination.get("total")) or 0
    raw_rows = [i for i in as_list(props.get("items")) if isinstance(i, dict)]
    if raw_rows and not rows:
        total = 0       # nothing but ads: the site counts them as the result
    category, sub_category, nested, nested_all = _listing_categories(props)
    return {
        "sort": refs.SORT_NAMES.get(g(props, "appData", "sorting", "sortBy", default=None)),
        "category": category,
        "sub_category": sub_category,
        "nested_sub_category": nested,
        "nested_sub_categories": nested_all,
        "attributes": listing_attributes(props),
        "results": rows,
        "pagination": {
            "page": page,
            "items_per_page": refs.LISTING_PAGE_SIZE,
            "total_pages": min(math.ceil(total / refs.LISTING_PAGE_SIZE), max_page),
            "total_count": total,
        },
    }


def corrected_query(props):
    """The query the site searched instead (a spelling it corrected), else None."""
    data = as_dict(g(as_dict(props), "displayData", "searchComponentData", default=None))
    modified = clean(data.get("modifiedQueryString"))
    return modified if modified and modified != clean(data.get("query")) else None


def listing_currency(props):
    """The currency the page was rendered in ('USD' when the currency cookie was honoured)."""
    return g(as_dict(props), "currency", "name", default=None)


# ---- reviews ------------------------------------------------------------------------------

def _price_bounds(text):
    """'Up to $50' -> (None, 50); '$100-$200' -> (100, 200); '$1,000 and above' -> (1000, None)."""
    text = text or ""
    numbers = [num(n.replace(",", "")) for n in _NUMBER_RE.findall(text)]
    numbers = [int(n) if n == int(n) else n for n in numbers if n is not None]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        return (None, numbers[0]) if re.search(r"up to|under|less", text, re.I) else (numbers[0], None)
    return None, None


def parse_review(row):
    """One review, as the gig and seller pages show it."""
    row = as_dict(row)
    low, high = _price_bounds(row.get("order_price_range_usd") or "")
    response = as_dict(row.get("seller_response"))
    return {
        "id": clean(row.get("id")),
        "rating": num(row.get("value")),
        "comment": multiline(row.get("comment")),
        "language": clean(row.get("comment_language")),
        "created_at": iso_utc(row.get("created_at")),
        "is_repeat_buyer": bool(row.get("repeat_buyer")),
        "is_business_buyer": bool(row.get("is_business")),
        "reviewer": {
            "username": clean(row.get("username")),
            "country": clean(row.get("reviewer_country")),
            "country_code": clean(row.get("reviewer_country_code")),
            "image": _image(row.get("user_image_url")),
            "industries": [i for i in as_list(row.get("reviewer_industry")) if isinstance(i, str)],
        },
        "order": {
            "price_min": low,
            "price_max": high,
            "currency": CURRENCY if (low is not None or high is not None) else None,
            "duration_days": to_int(row.get("order_duration_in_days")),
            "is_cancelled": bool(row.get("is_cancelled_order")),
        },
        "gig": {
            "id": _id(row.get("gig_id")),
            "slug": clean(row.get("gig_slug")),
            "category_id": _id(row.get("gig_category")),
            "sub_category_id": _id(row.get("gig_sub_category")),
            "nested_sub_category_id": _id(row.get("gig_nested_sub_category")),
        },
        "work_sample": ({"image": _image(row.get("work_sample_preview_url")),
                         "content_type": clean(row.get("work_sample_content_type"))}
                        if _image(row.get("work_sample_preview_url")) else None),
        "seller_response": ({"comment": multiline(response.get("comment")),
                             "created_at": iso_utc(response.get("created_at"))}
                            if response.get("comment") else None),
    }


def is_reviews(payload):
    """True for a reviews answer; an unknown gig answers an object without `reviews`."""
    return isinstance(payload, dict) and isinstance(payload.get("reviews"), list)


def parse_reviews(payload):
    """A reviews answer -> (reviews, cursor after the last one or None, total count)."""
    payload = as_dict(payload)
    rows = [r for r in as_list(payload.get("reviews")) if isinstance(r, dict) and r.get("id")]
    cursor = None
    if rows and payload.get("has_next"):
        cursor = refs.review_cursor(rows[-1]["id"], rows[-1].get("score"))
    return [parse_review(r) for r in rows], cursor, to_int(payload.get("total_count"))


def review_cursors(payload):
    """The cursor behind each review of an answer, in the answer's order."""
    return [refs.review_cursor(r["id"], r.get("score")) for r in as_list(as_dict(payload).get("reviews"))
            if isinstance(r, dict) and r.get("id")]


def rating_summary(block):
    """The rating part of a reviews block: average, count, per-star counts, the three sub-scores."""
    block = as_dict(block)
    stars = as_dict(block.get("star_summary"))
    breakdown = [{"stars": to_int(b.get("average_valuation_value")), "count": to_int(b.get("count")) or 0}
                 for b in as_list(block.get("breakdown")) if isinstance(b, dict)]
    return {
        "rating": rating(block.get("average_valuation")),
        "review_count": to_int(block.get("total_count")),
        "rating_breakdown": sorted(breakdown, key=lambda b: -(b["stars"] or 0)),
        "rating_details": {
            "communication": rating(stars.get("communication_valuation")),
            "quality_of_delivery": rating(stars.get("quality_of_delivery_valuation")),
            "value_for_money": rating(stars.get("value_for_money_valuation")),
        },
        "business_review_count": to_int(g(block, "filters_counters", "business", default=None)),
        "work_sample_review_count": to_int(g(block, "filters_counters", "work_sample", default=None)),
    }


# ---- a gig page -----------------------------------------------------------------------------

def is_gig(props):
    """True for the data of a gig page. An unknown slug answers the seller's page and an
    unknown seller the home page, both HTTP 200 and neither with a gig id."""
    return bool(_id(g(as_dict(props), "general", "gigId", default=None)))


def _package(pkg):
    pkg = as_dict(pkg)
    revisions = as_dict(pkg.get("revisions"))
    revision_count = to_int(revisions.get("value")) if revisions.get("included") else None
    fast = as_dict(pkg.get("extraFast"))
    hours = to_int(pkg.get("duration"))
    return {
        "tier": PACKAGE_TIERS.get(to_int(pkg.get("id"))),
        "name": clean(pkg.get("title")),
        "description": multiline(pkg.get("description")),
        "price": _usd(pkg.get("price")),
        "currency": CURRENCY,
        "delivery_days": (round(hours / 24, 1) if hours % 24 else hours // 24) if hours else None,
        "revisions": None if revision_count == -1 else revision_count,
        "has_unlimited_revisions": revision_count == -1,
        "extra_fast": ({"price": _usd(fast.get("price")), "delivery_hours": to_int(fast.get("duration"))}
                       if to_int(fast.get("price")) else None),
        "features": [{"name": clean(f.get("label")), "key": clean(f.get("name")),
                      "is_included": bool(f.get("included")),
                      "quantity": to_int(f.get("value")) if f.get("type") == "NUMERIC" else None}
                     for f in as_list(pkg.get("features")) if isinstance(f, dict)],
        "extras": [{"name": clean(e.get("label")), "description": clean(e.get("buyerTooltip")),
                    "price": _usd(e.get("price")), "extra_hours": to_int(e.get("duration")) or 0}
                   for e in as_list(pkg.get("customExtras")) if isinstance(e, dict)],
    }


def _media(slides):
    """Gallery slides -> (images, videos, documents, work sample images)."""
    images, videos, documents, samples = [], [], [], []
    for entry in as_list(slides):
        slide = as_dict(as_dict(entry).get("slide"))
        media = as_dict(slide.get("media"))
        link = _image(media.get("original")) or _image(slide.get("src"))
        if slide.get("typeVideo") or slide.get("itemScopeType") == "VideoSlide":
            video = _image(slide.get("videoSrc")) or _image(slide.get("src"))
            if video:
                videos.append({"link": video, "thumbnail": _image(slide.get("thumbnail"))})
        elif slide.get("typePdf") or slide.get("itemScopeType") == "PdfSlide":
            if link:
                documents.append({"link": link, "thumbnail": _image(slide.get("thumbnail")),
                                  "pages": [p for p in (_image(x) for x in as_list(media.get("pages"))) if p]})
        elif link:
            (samples if slide.get("isWorkSample") else images).append(link)
    return images, videos, documents, samples


def _consultation(data):
    data = as_dict(data)
    sessions = [{"minutes": to_int(p.get("session_minutes")), "price": num(p.get("price")), "currency": CURRENCY}
                for p in as_list(data.get("pricing")) if isinstance(p, dict) and p.get("status") == "ACTIVE"]
    if not sessions:
        return None
    return {"description": multiline(data.get("description")), "sessions": sessions}


def _client_gig(client):
    """A notable client as the gig page writes it."""
    client = as_dict(client)
    details = as_dict(client.get("enriched_details"))
    return {
        "name": clean(client.get("name") or details.get("name")),
        "domain": clean(client.get("website") or details.get("domain")),
        "industry": clean(details.get("industry")),
        "description": multiline(client.get("interaction_description")),
        "about": multiline(details.get("description")),
        "logo": _image(details.get("logo")),
        "is_fortune_500": bool(details.get("in_fortune")),
        "started_on": iso_day(client.get("started_at")),
        "ended_on": iso_day(client.get("ended_at")),
    }


def _client_seller(client):
    """A notable client as the seller page writes it."""
    client = as_dict(client)
    company = as_dict(client.get("company"))
    return {
        "name": clean(company.get("name")),
        "domain": None,
        "industry": clean(g(company, "industry", "slug", default=None)),
        "description": multiline(client.get("description")),
        "about": multiline(company.get("description")),
        "logo": _image(g(company, "logoImage", "previewUrl", "url", default=None)),
        "is_fortune_500": bool(company.get("inFortuneList")),
        "started_on": _date(client.get("startedAt")),
        "ended_on": _date(client.get("endedAt")),
    }


def _education(rows):
    return [{"school": clean(e.get("school")), "degree": clean(e.get("degree")),
             "degree_title": clean(e.get("degreeTitle")), "country_code": clean(e.get("countryCode")),
             "graduation_year": to_int(e.get("toYear"))}
            for e in as_list(rows) if isinstance(e, dict)]


def _certifications(rows):
    return [{"name": clean(c.get("certificationName")), "issuer": clean(c.get("receivedFrom")),
             "year": to_int(c.get("year"))}
            for c in as_list(rows) if isinstance(c, dict)]


def _skills(rows):
    return [{"name": clean(s.get("label") or s.get("name")), "level": (clean(s.get("level")) or "").lower() or None,
             "is_verified": bool(s.get("verified"))}
            for s in as_list(rows) if isinstance(s, dict) and (s.get("name") or s.get("label"))]


def _gig_seller(props, full_name=True):
    seller = as_dict(props.get("seller"))
    user = as_dict(seller.get("user"))
    card = as_dict(props.get("sellerCard"))
    username = clean(user.get("name")) or clean(g(props, "overview", "seller", "username", default=None))
    agency = as_dict(seller.get("agency"))
    sub_names = {to_int(s.get("id")): clean(s.get("name")) for s in as_list(card.get("proSubCategories")) if isinstance(s, dict)}
    return {
        "id": _id(user.get("id") or seller.get("id") or g(props, "general", "sellerId", default=None)),
        "username": username,
        "display_name": clean(g(user, "profile", "displayName", default=None)),
        "full_name": clean(user.get("fullName")) if full_name else None,
        "link": refs.seller_link(username),
        "image": _image(g(user, "profileImage", "previewUrl", "url", default=None)) or _image(card.get("profilePhoto")),
        "tagline": clean(seller.get("oneLinerTitle") or card.get("oneLiner")),
        "description": multiline(seller.get("description") or card.get("description")),
        "level": level_name(seller.get("sellerLevel")),
        "is_pro": bool(seller.get("isPro")),
        "is_verified": bool(seller.get("isVerified")),
        "is_highly_responsive": bool(seller.get("isHighlyResponsive")),
        "is_on_vacation": bool(seller.get("isOnVacation")),
        "country_code": clean(g(user, "address", "countryCode", default=None) or card.get("countryCode")),
        "member_since": _date(user.get("joinedAt") or card.get("memberSince")),
        "response_time_hours": to_int(g(seller, "responseTime", "inHours", default=None) or card.get("responseTime")),
        "last_delivery_at": _datetime_ms(card.get("recentDelivery")),
        "rating": rating(g(seller, "rating", "score", default=None) or card.get("rating")),
        "rating_count": to_int(g(seller, "rating", "count", default=None) or card.get("ratingsCount")),
        "completed_orders": to_int(seller.get("completedOrdersCount")),
        "hourly_rate": _usd(g(seller, "hourlyRate", "priceInCents", default=None)),
        "currency": CURRENCY,
        "languages": _languages(user.get("languages")) or _languages(card.get("proficientLanguages")),
        "skills": _skills(seller.get("activeStructuredSkills")),
        "education": _education(seller.get("activeEducations")),
        "certifications": _certifications(seller.get("certifications")),
        "pro_sub_categories": [{"id": to_int(s.get("subCategoryId")), "name": sub_names.get(to_int(s.get("subCategoryId")))}
                               for s in as_list(seller.get("proSubCategories")) if isinstance(s, dict) and s.get("subCategoryId")],
        "intro_video": _image(g(seller, "introVideo", "url", default=None)),
        "portfolio_count": to_int(g(seller, "portfolios", "totalCount", default=None)),
        "agency": ({"slug": agency.get("slug"), "link": refs.agency_link(agency.get("slug"))} if agency.get("slug") else None),
    }


def parse_gig(props, full_name=True):
    """A gig page -> the full record; None when the page is not a gig page. `full_name`:
    whether the seller's full name (in the page's data, not in its text) is returned."""
    props = as_dict(props)
    if not is_gig(props):
        return None
    general = as_dict(props.get("general"))
    overview_gig = as_dict(g(props, "overview", "gig", default=None))
    seller = _gig_seller(props, full_name)
    slug = clean(g(props, "portfolio", "slug", default=None))
    packages = [_package(p) for p in as_list(g(props, "packages", "packageList", default=None)) if isinstance(p, dict)]
    prices = [p["price"] for p in packages if p["price"] is not None]
    images, videos, documents, samples = _media(g(props, "gallery", "slides", default=None))
    reviews_block = as_dict(props.get("reviews"))
    reviews, _, _ = parse_reviews(reviews_block)
    summary = rating_summary(reviews_block)
    portfolio = as_dict(props.get("portfolio"))
    nested_id = _id(general.get("nestedSubCategoryId"))
    return {
        "id": _id(general.get("gigId")),
        "title": clean(general.get("gigTitle")),
        "link": refs.gig_link(f"{seller['username']}/{slug}") if seller["username"] and slug else None,
        "status": clean(general.get("gigStatus")),
        "category": {"id": _id(general.get("categoryId")), "name": clean(general.get("categoryName")),
                     "slug": clean(general.get("categorySlug")),
                     "link": refs.category_link(clean(general.get("categorySlug")))},
        "sub_category": {"id": _id(general.get("subCategoryId")), "name": clean(general.get("subCategoryName")),
                         "slug": clean(general.get("subCategorySlug")),
                         "link": refs.category_link(clean(general.get("categorySlug")), clean(general.get("subCategorySlug")))},
        "nested_sub_category": ({"id": nested_id, "name": clean(g(props, "overview", "categories", "nestedSubCategory", "name", default=None)),
                                 "slug": clean(general.get("nestedSubCategorySlug")),
                                 "link": refs.category_link(clean(general.get("categorySlug")), clean(general.get("subCategorySlug")),
                                                            clean(general.get("nestedSubCategorySlug")))}
                                if nested_id else None),
        "description": html_to_text(g(props, "description", "content", default=None)),
        "attributes": [{"name": clean(a.get("name")), "label": clean(g(a, "metadata", "alias", default=None) or g(a, "metadata", "label", default=None)),
                        "values": [clean(o.get("value")) for o in as_list(a.get("options")) if isinstance(o, dict)],
                        "value_labels": [clean(o.get("label") or o.get("value")) for o in as_list(a.get("options")) if isinstance(o, dict)]}
                       for a in as_list(g(props, "description", "metadataAttributes", default=None)) if isinstance(a, dict)],
        "tags": [t for t in (clean(as_dict(t).get("name")) for t in as_list(g(props, "tags", "tagsGigList", default=None))) if t],
        "price_from": min(prices) if prices else _usd(g(props, "openGraph", "price", default=None)),
        "currency": CURRENCY,
        "packages": packages,
        "subscriptions": [{"months": to_int(o.get("duration")), "discount_percent": to_int(o.get("discountPercentage"))}
                          for o in as_list(g(props, "packages", "recurringOptions", default=None))
                          if isinstance(o, dict) and o.get("durationTimeUnit") in (None, "time_unit_month")],
        "consultation": _consultation(props.get("consultationData")),
        "faq": [{"question": clean(q.get("question")), "answer": multiline(q.get("answer"))}
                for q in as_list(g(props, "faq", "questionsAndAnswers", default=None)) if isinstance(q, dict)],
        "image": images[0] if images else None,
        "images": images,
        "videos": videos,
        "documents": documents,
        "work_samples": samples,
        "rating": summary["rating"] or rating(overview_gig.get("rating")),
        "review_count": summary["review_count"] if summary["review_count"] is not None else to_int(overview_gig.get("ratingsCount")),
        "rating_breakdown": summary["rating_breakdown"],
        "rating_details": summary["rating_details"],
        "business_review_count": summary["business_review_count"],
        "work_sample_review_count": summary["work_sample_review_count"],
        "reviews": reviews,
        "summary_points": [s for s in (clean(x) for x in as_list(g(props, "aiSummary", "summary", default=None))) if s]
                          if g(props, "aiSummary", "visible", default=False) else [],
        "orders_in_queue": to_int(overview_gig.get("ordersInQueue")),
        "saved_count": to_int(g(props, "topNav", "gigCollectedCount", default=None)),
        "is_pro": bool(general.get("isPro")),
        "is_on_vacation": bool(general.get("isOnVacation")),
        "is_restricted_by_region": bool(overview_gig.get("isRestrictedByRegion")),
        "has_repeat_buyers": bool(g(props, "repeatScore", "score", default=False)),
        "accepts_custom_orders": bool(g(props, "customOrder", "allowCustomOrders", default=False)),
        "portfolio": {
            "project_count": to_int(portfolio.get("projectsCount")) or 0,
            "projects": [{"title": clean(p.get("title")), "image": _image(p.get("item"))}
                         for p in as_list(portfolio.get("portfolioProjects")) if isinstance(p, dict)],
        },
        "notable_clients": [_client_gig(c) for c in as_list(props.get("notableClients")) if isinstance(c, dict)],
        "other_gig_ids": [i for i in (_id(x) for x in as_list(g(props, "otherGigs", "gigIds", default=None))) if i],
        "seller": seller,
    }


# ---- a seller page ---------------------------------------------------------------------------

def is_seller(props):
    """True for the data of a seller (or agency) page."""
    return bool(g(as_dict(props), "seller", "user", "id", default=None))


def _agency(props):
    agency = as_dict(props.get("agency"))
    if not agency.get("slug"):
        nested = as_dict(g(props, "seller", "agency", default=None))
        return {"slug": nested.get("slug"), "link": refs.agency_link(nested.get("slug")), "established": None,
                "team_size": None, "cover_image": None, "members": []} if nested.get("slug") else None
    return {
        "slug": agency.get("slug"),
        "link": refs.agency_link(agency.get("slug")),
        "established": to_int(agency.get("established")),
        "team_size": to_int(agency.get("teamSize")),
        "cover_image": _image(agency.get("profileBackgroundUrl")),
        "members": [{"name": clean(m.get("name")), "role": clean(m.get("role")),
                     "description": multiline(m.get("description")), "image": _image(m.get("profileImageUrl"))}
                    for m in sorted((m for m in as_list(agency.get("members")) if isinstance(m, dict)),
                                    key=lambda m: to_int(m.get("position")) or 0)],
    }


def _work_experience(rows):
    out = []
    for row in as_list(rows):
        if not isinstance(row, dict):
            continue
        company = as_dict(row.get("company"))
        out.append({
            "title": clean(row.get("title")),
            "company": clean(company.get("name")),
            "industry": clean(company.get("industry")),
            "employment_type": (clean(row.get("employmentType")) or "").lower() or None,
            "description": multiline(row.get("description")),
            "is_current": bool(row.get("currentJob")),
            "started_on": _date_s_or_ms(row.get("startDate")) or iso_day(row.get("startDate")),
            "ended_on": _date_s_or_ms(row.get("endDate")) or iso_day(row.get("endDate")),
            "skills": [s for s in (clean(as_dict(s).get("name") if isinstance(s, dict) else s) for s in as_list(row.get("skills"))) if s],
        })
    return out


def _testimonials(rows):
    return [{"text": multiline(t.get("text")), "client_name": clean(g(t, "client", "name", default=None)),
             "client_role": clean(g(t, "client", "role", default=None)),
             "client_company": clean(g(t, "client", "company", default=None)),
             "project": clean(g(t, "project", "name", default=None)),
             "project_date": _date(g(t, "project", "date", default=None))}
            for t in as_list(rows) if isinstance(t, dict)]


def parse_seller(props):
    """A seller page (or an agency's page) -> the full record; None when the page is neither.
    The record carries the seller's gigs under `gigs` (api.py serves them on their own route)."""
    props = as_dict(props)
    if not is_seller(props):
        return None
    seller = as_dict(props.get("seller"))
    user = as_dict(seller.get("user"))
    username = clean(user.get("name")) or clean(props.get("username"))
    localization = as_dict(props.get("localizationData") or props.get("localization"))
    reviews_block = as_dict(g(props, "reviewsData", "buying_reviews", default=None) or g(props, "reviews", "buying_reviews", default=None))
    summary = rating_summary(reviews_block)
    gigs = [gig_row(item) for item in as_list(props.get("gigsData") or props.get("gigs"))
            if isinstance(item, dict) and (item.get("gig_id") or item.get("gigId"))]
    presences = [clean(as_dict(p).get("platform")) for p in
                 as_list(seller.get("onlinePresences")) + as_list(seller.get("professionalPresences"))]
    return {
        "id": _id(user.get("id")),
        "username": username,
        "display_name": clean(g(user, "profile", "displayName", default=None)),
        "link": refs.seller_link(username),
        "image": _image(user.get("profileImageUrl")),
        "cover_image": _image(g(seller, "profileBackgroundImage", "previewUrl", "url", default=None)),
        "tagline": clean(seller.get("oneLinerTitle")),
        "description": multiline(seller.get("description")),
        "level": level_name(seller.get("sellerLevel")),
        "is_pro": bool(seller.get("isPro")),
        "is_verified": bool(seller.get("isVerified")),
        "is_highly_responsive": bool(seller.get("isHighlyResponsive")),
        "is_active": bool(seller.get("isActive")),
        "is_on_vacation": bool(seller.get("isOnVacation")),
        "is_agency": bool(as_dict(props.get("agency")).get("slug") or as_dict(seller.get("agency")).get("slug")),
        "country": clean(g(user, "address", "countryName", default=None)),
        "country_code": clean(g(user, "address", "countryCode", default=None)),
        "timezone": clean(g(user, "localization", "timezone", default=None) or localization.get("timezone")),
        "member_since": _date(user.get("joinedAt")),
        "response_time_hours": to_int(g(seller, "responseTime", "inHours", default=None)),
        "rating": rating(g(seller, "rating", "score", default=None)) or summary["rating"],
        "rating_count": to_int(g(seller, "rating", "count", default=None)),
        "review_count": summary["review_count"],
        "rating_breakdown": summary["rating_breakdown"],
        "rating_details": summary["rating_details"],
        "business_review_count": summary["business_review_count"],
        "work_sample_review_count": summary["work_sample_review_count"],
        "reviews": parse_reviews(reviews_block)[0],
        "hourly_rate": _usd(g(seller, "hourlyRate", "priceInCents", default=None)),
        "currency": CURRENCY,
        "languages": _languages(user.get("languages")),
        "skills": _skills(seller.get("activeStructuredSkills")),
        "education": _education(seller.get("activeEducations")),
        "certifications": _certifications(seller.get("certifications")),
        "work_experience": _work_experience(g(seller, "workExperiences", "nodes", default=None)),
        "notable_clients": [_client_seller(c) for c in as_list(seller.get("notableClients")) if isinstance(c, dict)],
        "testimonials": _testimonials(seller.get("testimonials")),
        "social_platforms": sorted({p.lower() for p in presences if p}),
        "consultation": _consultation(props.get("consultationData")),
        "intro_video": _image(g(seller, "introVideo", "url", default=None)),
        "portfolio_count": to_int(g(seller, "portfolios", "totalCount", default=None)),
        "categories": [{"category_id": _id(c.get("categoryId")), "sub_category_id": _id(c.get("subCategoryId")),
                        "nested_sub_category_id": _id(c.get("nestedCategoryId"))}
                       for c in as_list(seller.get("gigCategories")) if isinstance(c, dict)],
        "gig_count": to_int(seller.get("approvedGigsCount")) if seller.get("approvedGigsCount") is not None else len(gigs),
        "agency": _agency(props),
        "gigs": gigs,
    }


# ---- categories --------------------------------------------------------------------------------

def _key(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def parse_categories(tree, ids=None):
    """The category tree (names, slugs, links) joined with the navigation menu's numeric ids
    (matched by name inside each category) -> [{id, name, slug, link, sub_categories: [...]}].
    A name the menu does not list keeps a null id."""
    category_ids, sub_ids, nested = {}, {}, {}
    config = as_dict(as_dict(ids).get("config"))
    for rows in as_dict(config.get("level_1")).values():
        for row in as_list(rows):
            if isinstance(row, dict) and row.get("type") == "category":
                category_ids[_key(row.get("alias"))] = _id(g(row, "urlParams", "id", default=None))

    def category_id_of(name):
        """The menu's id for a tree category: the same name, or the menu's shorter one
        ('Personal Growth' for the tree's 'Personal Growth & Hobbies')."""
        key = _key(name)
        if key in category_ids:
            return category_ids[key]
        return next((cid for alias, cid in category_ids.items() if alias and key.startswith(alias + " ")), None)

    for level in ("level_2", "level_3"):
        for rows in as_dict(config.get(level)).values():
            for row in as_list(rows):
                if not isinstance(row, dict):
                    continue
                params = as_dict(row.get("urlParams"))
                if row.get("type") == "sub_category":
                    sub_ids.setdefault((_id(params.get("categoryId")), _key(row.get("alias"))), _id(params.get("id")))
                elif row.get("type") == "nested_sub_category":
                    rows_of = nested.setdefault(_id(params.get("subCategoryId")), [])
                    entry = {"id": _id(params.get("id")), "name": clean(row.get("alias"))}
                    if entry["id"] and entry not in rows_of:
                        rows_of.append(entry)
    out = []
    for category in as_list(as_dict(tree).get("categories")):
        if not isinstance(category, dict):
            continue
        category_id = category_id_of(category.get("name"))
        subs = []
        for column in as_dict(category.get("sub_categories")).values():
            for entry in as_list(column):
                for name, data in as_dict(entry).items():
                    link = refs.site_link(as_dict(data).get("url"))
                    sub_id = sub_ids.get((category_id, _key(name)))
                    subs.append({
                        "id": sub_id,
                        "name": clean(name),
                        "slug": link.rstrip("/").rsplit("/", 1)[-1] if link else None,
                        "link": link,
                        "nested_sub_categories": nested.get(sub_id, []) if sub_id else [],
                    })
        out.append({
            "id": category_id,
            "name": clean(category.get("name")),
            "slug": clean(category.get("slug")),
            "link": refs.site_link(category.get("url")),
            "sub_categories": subs,
        })
    return out


# ---- suggestions --------------------------------------------------------------------------------

def parse_suggestions(payload):
    """The search box's answer -> (suggested searches, suggested usernames)."""
    payload = as_dict(payload)
    searches = [v for v in (clean(as_dict(s).get("value")) for s in as_list(payload.get("suggestions"))) if v]
    sellers = [v for v in (clean(as_dict(s).get("value")) for s in as_list(payload.get("users_suggestions"))) if v]
    return searches, sellers
