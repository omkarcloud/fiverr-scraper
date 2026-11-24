"""Offline tests for the Fiverr parsers and reference resolvers, against the
fixtures (real answers captured 2026-11-21).

    python -m pytest fiverr/test_parsers.py -q
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fiverr import parsers, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(name):
    opener = gzip.open if name.endswith(".gz") else open
    with opener(os.path.join(FX, name), "rt", encoding="utf-8") as f:
        return f.read()


def fixture(name):
    return json.loads(raw(name))


def snake(value, path=""):
    """Every key of an answer is snake_case and no value is '' (null instead)."""
    if isinstance(value, dict):
        for key, item in value.items():
            assert key == key.lower() and " " not in key and "-" not in key, f"{path}.{key}"
            snake(item, f"{path}.{key}")
    elif isinstance(value, list):
        for item in value:
            snake(item, path + "[]")
    else:
        assert value != "", path


# ---- the page's data block ---------------------------------------------------------------

def test_page_props_reads_the_data_of_a_real_page():
    props = parsers.page_props(raw("gig_page_1500855.html.gz"))
    assert props == fixture("gig_sparse_1500855.json.gz")
    assert parsers.parse_gig(props)["id"] == 1500855


def test_pages_without_data_answer_none():
    assert parsers.page_props(raw("blocked_page.html")) is None
    assert parsers.page_props(raw("page_not_found_404.html")) is None
    assert parsers.page_props("") is None and parsers.page_props(None) is None


# ---- listings ------------------------------------------------------------------------------

def test_search_page():
    props = fixture("search_page_1.json.gz")
    assert parsers.is_listing(props) and parsers.listing_currency(props) == "USD"
    listing = parsers.parse_listing(props, 1, refs.SEARCH_MAX_PAGE)
    snake(listing)
    assert listing["sort"] == "relevance"
    assert listing["pagination"] == {"page": 1, "items_per_page": 48, "total_pages": 11, "total_count": 169355}
    assert listing["category"]["slug"] == "graphics-design" and listing["sub_category"]["id"] == 49
    assert listing["sub_category"]["link"] == "https://www.fiverr.com/categories/graphics-design/creative-logo-design"
    assert [a["name"] for a in listing["attributes"]] == ["style", "logo_type", "file_format"]
    assert {"value": "retro", "label": "Vintage"}.items() <= listing["attributes"][0]["options"][2].items()
    rows = listing["results"]
    assert len(rows) == 48 and len({r["id"] for r in rows}) == 48
    row = rows[0]
    assert list(row)[:5] == ["id", "title", "link", "price_from", "currency"]
    assert row["link"].startswith("https://www.fiverr.com/") and "?" not in row["link"]
    assert isinstance(row["price_from"], int) and row["currency"] == "USD"
    assert isinstance(row["delivery_days"], int) and row["images"] and row["image"] == row["images"][0]
    assert row["seller"]["link"] == "https://www.fiverr.com/" + row["seller"]["username"]
    assert {r["seller"]["level"] for r in rows} <= {"top_rated", "level_2", "level_1", "new"}
    assert all(r["seller"]["languages"] and r["seller"]["languages"][0]["level"] in
               ("basic", "conversational", "fluent", "native_or_bilingual") for r in rows)
    hourly = [r["hourly_rate"] for r in rows if r["hourly_rate"] is not None]
    assert hourly and all(5 <= h <= 500 for h in hourly)        # cents in the raw data, dollars here
    assert any(r["has_video"] and r["video"] for r in rows)
    assert all({"name", "values"} == set(a) for r in rows for a in r["attributes"])


def test_ads_are_left_out_and_never_counted_as_the_result():
    props = fixture("search_with_promoted_rows.json.gz")
    assert sum(1 for i in props["items"] if i.get("type") == "promoted_gigs") == 20
    assert len(parsers.listing_rows(props)) == 28
    assert parsers.has_promoted_rows(props)
    assert not parsers.has_promoted_rows(fixture("search_page_1.json.gz"))      # a visitor from India is shown none
    assert not parsers.has_promoted_rows(None) and not parsers.has_promoted_rows({})
    only_ads = parsers.parse_listing(fixture("search_no_result_promoted_only.json.gz"), 1, 11)
    assert only_ads["results"] == [] and only_ads["pagination"]["total_count"] == 0
    assert only_ads["pagination"]["total_pages"] == 0


def test_no_result_past_end_and_last_page():
    empty = fixture("search_no_result.json.gz")
    listing = parsers.parse_listing(empty, 1, 11)
    assert listing["results"] == [] and listing["pagination"]["total_count"] == 0
    assert listing["category"] is None and listing["sub_category"] is None and listing["attributes"] == []
    assert parsers.corrected_query(empty) == "zxqvwkjh permit"      # Fiverr searched its own spelling
    assert parsers.corrected_query(fixture("search_page_1.json.gz")) is None
    past = parsers.parse_listing(fixture("search_past_end.json.gz"), 12, 11)
    assert past["results"] == [] and past["pagination"]["total_count"] == 0
    last = parsers.parse_listing(fixture("search_last_page.json.gz"), 11, 11)
    assert len(last["results"]) == 20 and last["pagination"]["total_pages"] == 11


def test_filters_show_in_the_rows_and_in_what_the_site_says_it_applied():
    props = fixture("search_filters_combined.json.gz")
    listing = parsers.parse_listing(props, 1, 11)
    rows = listing["results"]
    assert listing["sort"] == "best_selling" and listing["pagination"]["total_count"] == 36 == len(rows)
    assert {r["seller"]["level"] for r in rows} == {"top_rated"}
    assert {r["seller"]["country_code"] for r in rows} == {"US"}
    assert all(r["delivery_days"] <= 3 and 20 <= r["price_from"] <= 200 for r in rows)
    assert set(parsers.selected_filters(props)) == {"seller_level", "seller_location", "delivery_time", "gig_price_range"}


def test_category_filters_known_and_unknown():
    props = fixture("search_attributes.json.gz")
    assert parsers.selected_filters(props) == {"style": {"retro"}, "logo_type": {"mascot", "emblem"}}
    listing = parsers.parse_listing(props, 1, 11)
    style = next(a for a in listing["attributes"] if a["name"] == "style")
    assert [o["value"] for o in style["options"] if o["is_selected"]] == ["retro"]
    assert all("retro" in next(a["values"] for a in r["attributes"] if a["name"] == "style") for r in listing["results"])
    # a value Fiverr does not know is echoed nowhere in the applied filters: the rows are unfiltered
    assert parsers.selected_filters(fixture("search_attribute_unknown.json.gz")) == {}


def test_newest_sort_and_agency_rows():
    assert parsers.parse_listing(fixture("search_sort_newest.json.gz"), 1, 11)["sort"] == "newest"
    rows = parsers.parse_listing(fixture("search_agency_rows.json.gz"), 1, 11)["results"]
    agency = next(r["seller"]["agency"] for r in rows if r["seller"]["agency"])
    assert agency["link"] == "https://www.fiverr.com/agencies/" + agency["slug"]
    assert isinstance(agency["established"], int) and isinstance(agency["team_size"], int) and agency["highlights"]
    assert all(r["seller"]["agency"] for r in rows)


def test_category_pages():
    first = parsers.parse_listing(fixture("category_page_1.json.gz"), 1, refs.CATEGORY_MAX_PAGE)
    assert first["sort"] == "best_selling" and len(first["results"]) == 48
    assert first["pagination"]["total_pages"] == 21 and first["nested_sub_category"] is None
    last = parsers.parse_listing(fixture("category_last_page.json.gz"), 21, refs.CATEGORY_MAX_PAGE)
    assert len(last["results"]) == 48
    nested = parsers.parse_listing(fixture("category_nested.json.gz"), 1, refs.CATEGORY_MAX_PAGE)
    assert nested["nested_sub_category"] == {
        "id": 2609, "name": "WordPress", "slug": "wordpress-development",
        "link": "https://www.fiverr.com/categories/programming-tech/website-development/wordpress-development"}
    assert {r["nested_sub_category_id"] for r in nested["results"]} == {2609}
    assert len(nested["nested_sub_categories"]) == 30
    # an unknown sub-category answers the category's landing page: no listing in it
    assert not parsers.is_listing(fixture("category_unknown.json.gz"))


# ---- a gig page ----------------------------------------------------------------------------

def test_gig_full_record():
    gig = parsers.parse_gig(fixture("gig_417735249.json.gz"))
    snake(gig)
    assert list(gig)[:4] == ["id", "title", "link", "status"]
    assert gig["id"] == 417735249
    assert gig["link"] == "https://www.fiverr.com/logocraftz/create-modern-minimalist-business-logo-design"
    assert gig["category"]["slug"] == "graphics-design" and gig["sub_category"]["id"] == 49
    assert gig["nested_sub_category"] is None
    assert "<" not in gig["description"] and gig["description"].startswith("Welcome to Logocraftz")
    assert len(gig["tags"]) == 5 and len(gig["faq"]) == 10 and gig["faq"][0]["question"].endswith("?")
    assert [a["name"] for a in gig["attributes"]] == ["style", "logo_type", "file_format"]
    assert gig["attributes"][0]["values"] == ["flat_minimalist"] and gig["attributes"][0]["value_labels"] == ["Minimalist"]
    # packages: cents -> dollars, hours -> days, -1 revisions -> unlimited
    assert [p["tier"] for p in gig["packages"]] == ["basic", "standard", "premium"]
    basic = gig["packages"][0]
    assert basic["price"] == 40 and basic["currency"] == "USD" and basic["delivery_days"] == 2
    assert basic["revisions"] is None and basic["has_unlimited_revisions"] is True
    assert basic["extra_fast"] == {"price": 20, "delivery_hours": 24}
    assert len(basic["features"]) == 10 and basic["features"][0] == {
        "name": "Number of concepts included", "key": "included_versions", "is_included": True, "quantity": 1}
    assert len(basic["extras"]) == 2 and basic["extras"][0]["price"] == 50
    assert gig["price_from"] == 40
    assert gig["rating"] == 4.9 and gig["review_count"] == 397
    assert [b["stars"] for b in gig["rating_breakdown"]] == [5, 4, 3, 2, 1]
    assert sum(b["count"] for b in gig["rating_breakdown"]) == 397
    assert gig["rating_details"] == {"communication": 4.9, "quality_of_delivery": 4.9, "value_for_money": 4.9}
    assert len(gig["reviews"]) == 5 and len(gig["summary_points"]) == 5
    assert gig["orders_in_queue"] == 9 and gig["saved_count"] == 404
    assert len(gig["images"]) == 3 and len(gig["work_samples"]) == 16 and len(gig["documents"]) == 1 and gig["image"] == gig["images"][0]
    assert gig["portfolio"]["project_count"] == 3 and len(gig["portfolio"]["projects"]) == 3
    seller = gig["seller"]
    assert seller["id"] == 102898503 and seller["username"] == "logocraftz" and seller["level"] == "level_2"
    assert seller["full_name"] == "Logo Craftz" and seller["completed_orders"] == 568
    assert seller["member_since"] == "2021-02-28" and seller["last_delivery_at"].endswith("Z")
    assert seller["hourly_rate"] == 15 and seller["country_code"] == "PK"
    assert seller["languages"] == [{"code": "en", "level": "fluent"}, {"code": "es", "level": "conversational"},
                                   {"code": "fr", "level": "conversational"}]
    assert len(seller["skills"]) == 14 and seller["education"][0]["school"] == "University of Sindh Jamshoro"
    assert seller["certifications"][0] == {"name": "Certificate in Information Technology", "issuer": "Computer Man", "year": 2014}


def test_the_full_name_can_be_switched_off():
    assert parsers.parse_gig(fixture("gig_417735249.json.gz"), full_name=False)["seller"]["full_name"] is None


def test_pro_gig_with_video_documents_subscriptions_and_clients():
    gig = parsers.parse_gig(fixture("gig_pro_448616551.json.gz"))
    snake(gig)
    assert gig["is_pro"] and gig["seller"]["is_pro"] and gig["seller"]["level"] == "top_rated"
    assert len(gig["videos"]) == 1 and gig["videos"][0]["link"].startswith("https://")
    assert len(gig["documents"]) == 2 and gig["documents"][0]["pages"]
    assert gig["subscriptions"] and gig["subscriptions"][0]["discount_percent"] == 20
    assert gig["consultation"]["sessions"][0] == {"minutes": 30, "price": 35, "currency": "USD"}
    client = gig["notable_clients"][0]
    assert client["name"] == "Cisco" and client["domain"] == "cisco.com" and client["started_on"] == "2021-07-01"
    assert gig["packages"][0]["revisions"] == 1 and gig["packages"][0]["has_unlimited_revisions"] is False
    assert gig["packages"][0]["delivery_days"] == 3
    assert gig["seller"]["pro_sub_categories"][0] == {"id": 462, "name": "Icon Design"}
    assert gig["seller"]["intro_video"] and len(gig["other_gig_ids"]) == 10
    assert gig["has_repeat_buyers"] is True


def test_sparse_gigs_keep_every_key():
    full = parsers.parse_gig(fixture("gig_417735249.json.gz"))
    for name in ("gig_no_reviews_one_package_516722324.json.gz", "gig_sparse_1500855.json.gz", "gig_video_317160323.json.gz"):
        gig = parsers.parse_gig(fixture(name))
        snake(gig)
        assert list(gig) == list(full) and list(gig["seller"]) == list(full["seller"]), name
    gig = parsers.parse_gig(fixture("gig_no_reviews_one_package_516722324.json.gz"))
    assert len(gig["packages"]) == 1 and gig["review_count"] == 0 and gig["rating"] is None
    assert gig["reviews"] == [] and gig["faq"] == [] and gig["seller"]["level"] == "new"
    assert gig["seller"]["full_name"] is None and gig["consultation"] is None
    assert gig["packages"][0]["extra_fast"] is None


def test_not_found_gig_pages_are_not_gigs():
    seller_page = fixture("gig_not_found_seller_page.json.gz")       # an unknown slug of a real seller
    home_page = fixture("gig_not_found_home_page.json.gz")           # an unknown seller
    assert parsers.parse_gig(seller_page) is None and parsers.parse_gig(home_page) is None
    assert parsers.is_seller(seller_page) and not parsers.is_seller(home_page)
    assert parsers.parse_gig(None) is None and parsers.parse_gig({}) is None


# ---- a seller page -------------------------------------------------------------------------

def test_seller_full_record():
    seller = parsers.parse_seller(fixture("seller_pro_many_gigs.json.gz"))
    snake(seller)
    assert list(seller)[:4] == ["id", "username", "display_name", "link"]
    assert seller["id"] == 70944075 and seller["link"] == "https://www.fiverr.com/loftydesignshop"
    assert seller["level"] == "top_rated" and seller["is_pro"] and not seller["is_agency"]
    assert seller["country"] == "India" and seller["timezone"] == "Asia/Kolkata"
    assert seller["member_since"] == "2018-08-10" and seller["hourly_rate"] == 45
    assert seller["rating"] == 4.9 and seller["rating_count"] == 15428 and seller["review_count"] == 15428
    assert len(seller["reviews"]) == 5 and seller["reviews"][0]["seller_response"]["comment"]
    assert seller["gig_count"] == 13 == len(seller["gigs"]) and len({g["id"] for g in seller["gigs"]}) == 13
    assert seller["gigs"][0]["seller"]["username"] == "loftydesignshop"
    assert seller["social_platforms"] == ["behance", "dribbble", "linkedin"]
    assert len(seller["notable_clients"]) == 5 and seller["notable_clients"][0]["name"] == "Coldwell Banker"
    assert seller["notable_clients"][0]["started_on"] == "2023-08-01"
    assert seller["testimonials"][0]["client_company"] == "Ocean Abrasive"
    assert seller["testimonials"][0]["project_date"] == "2018-01-25"
    assert seller["consultation"]["sessions"][0]["price"] == 100
    assert seller["cover_image"] is None        # the site's "file no longer available" placeholder is not a cover
    assert seller["education"][0]["graduation_year"] == 2014 and len(seller["skills"]) == 33
    assert seller["categories"][0] == {"category_id": 3, "sub_category_id": 49, "nested_sub_category_id": None}


def test_seller_work_experience_and_a_new_seller():
    seller = parsers.parse_seller(fixture("seller_logocraftz.json.gz"))
    job = seller["work_experience"][0]
    assert job["company"] == "Freelancer.com" and job["is_current"] is True and job["description"]
    assert job["started_on"] == "2017-12-15" and job["ended_on"] is None     # startDate is epoch milliseconds
    new = parsers.parse_seller(fixture("seller_new_no_reviews.json.gz"))
    snake(new)
    assert list(new) == list(seller)
    assert new["level"] == "new" and new["rating"] is None and new["review_count"] == 0 and new["reviews"] == []
    assert new["gig_count"] == 4 and new["agency"] is None and new["hourly_rate"] is None


def test_work_experience_dates_in_seconds_or_milliseconds():
    # Most profiles send epoch milliseconds; some send epoch seconds (bhaveshbandhiya,
    # 2026-11-23), which read as milliseconds came out as 1970-01-20. Both units read
    # as the same day; a pre-1970 date in milliseconds and an ISO day stay right.
    rows = [
        {"title": "UIUX Designer", "company": {"name": "Teq"}, "currentJob": True, "startDate": 1648771200},
        {"title": "Product Designer", "company": {"name": "Clar"}, "startDate": 1648771200000, "endDate": 1669852800},
        {"title": "Typesetter", "startDate": -315619200000, "endDate": "2001-05-01"},
        {"title": "No dates", "startDate": None, "endDate": 0},
    ]
    jobs = parsers._work_experience(rows)
    assert [job["started_on"] for job in jobs] == ["2022-04-01", "2022-04-01", "1960-01-01", None]
    assert [job["ended_on"] for job in jobs] == [None, "2022-12-01", "2001-05-01", None]


def test_agency_page_has_the_same_keys():
    agency = parsers.parse_seller(fixture("seller_agency.json.gz"))
    snake(agency)
    assert list(agency) == list(parsers.parse_seller(fixture("seller_logocraftz.json.gz")))
    assert agency["username"] == "colordesk_in" and agency["is_agency"] and agency["timezone"] == "Asia/Kolkata"
    assert agency["agency"]["link"] == "https://www.fiverr.com/agencies/colordesk"
    assert agency["agency"]["established"] == 2020 and agency["agency"]["team_size"] == 10
    assert len(agency["agency"]["members"]) == 8 and agency["agency"]["members"][0]["role"] == "Founder and Lead"
    assert len(agency["gigs"]) == 7 and agency["review_count"] == 45 and len(agency["reviews"]) == 5


def test_pages_that_are_not_a_seller():
    assert parsers.parse_seller(fixture("gig_not_found_home_page.json.gz")) is None
    assert parsers.parse_seller(None) is None


# ---- reviews -------------------------------------------------------------------------------

def test_reviews_page_and_its_cursor():
    payload = fixture("gig_reviews_page_1.json")
    reviews, cursor, total = parsers.parse_reviews(payload)
    snake(reviews)
    assert len(reviews) == 5 and total == 394 and cursor == "6aa2aa3fb0246a7e6cffa232~0.70956004"
    assert parsers.review_cursors(payload)[-1] == cursor
    first = reviews[0]
    assert list(first)[:3] == ["id", "rating", "comment"]
    assert first["id"] == "6afca00500df1b2b3fb39113" and first["rating"] == 5
    assert first["created_at"] == "2026-11-17T19:44:51Z"
    assert first["reviewer"] == {"username": "bramirez1026", "country": "United States", "country_code": "US",
                                 "image": first["reviewer"]["image"],
                                 "industries": ["retail_and_wholesale", "sports_and_fitness"]}
    assert first["order"] == {"price_min": None, "price_max": 50, "currency": "USD", "duration_days": 4, "is_cancelled": False}
    assert first["gig"]["id"] == 417735249 and first["seller_response"]["created_at"] == "2026-11-17T19:45:16Z"
    assert first["is_repeat_buyer"] is True
    # nothing the page hides: no encrypted order id, no ranking score, no buyer's review count
    text = json.dumps(reviews)
    assert "FO1E1AF37E43" not in text and "relevancy" not in text and "reviews_count_as_buyer" not in text
    second, _, _ = parsers.parse_reviews(fixture("gig_reviews_page_2.json"))
    assert not {r["id"] for r in reviews} & {r["id"] for r in second}


@pytest.mark.parametrize("text, bounds", [
    ("Up to $50", (None, 50)), ("$100-$200", (100, 200)), ("$1,000-$2,000", (1000, 2000)),
    ("$2,000 and above", (2000, None)), ("", (None, None)), (None, (None, None)),
])
def test_price_ranges(text, bounds):
    assert parsers._price_bounds(text) == bounds


def test_reviews_last_page_none_and_unknown_gig():
    reviews, cursor, total = parsers.parse_reviews(fixture("gig_reviews_last_page.json"))
    assert len(reviews) == 3 and cursor is None and total == 13
    assert parsers.parse_reviews(fixture("gig_reviews_none.json")) == ([], None, 0)
    assert parsers.is_reviews(fixture("gig_reviews_none.json"))
    assert not parsers.is_reviews(fixture("gig_reviews_not_found.json"))
    assert not parsers.is_reviews(fixture("seller_reviews_not_found.json"))


def test_review_sorts_and_filters():
    recent, cursor, _ = parsers.parse_reviews(fixture("gig_reviews_sort_recent.json"))
    dates = [r["created_at"] for r in recent]
    assert dates == sorted(dates, reverse=True) and cursor.endswith("~0")
    business, _, total = parsers.parse_reviews(fixture("gig_reviews_business.json"))
    assert total == 18 and all(r["is_business_buyer"] for r in business)
    four, _, _ = parsers.parse_reviews(fixture("gig_reviews_4_stars.json"))
    assert all(round(r["rating"]) == 4 for r in four)      # 3.7 to 4.3: the star a rating rounds to


def test_seller_reviews_head_and_work_samples():
    head = fixture("seller_reviews_first_page.json")
    assert head["user_id"] == 102898503
    summary = parsers.rating_summary(head)
    assert summary["rating"] == 4.9 and summary["review_count"] == 400 and summary["business_review_count"] == 18
    assert len(parsers.parse_reviews(fixture("seller_reviews_page_2.json"))[0]) == 5
    agency, _, _ = parsers.parse_reviews(fixture("seller_reviews_agency.json"))
    sample = next(r["work_sample"] for r in agency if r["work_sample"])
    assert sample["image"].startswith("https://") and sample["content_type"]


# ---- categories and suggestions --------------------------------------------------------------

def test_categories_with_ids():
    categories = parsers.parse_categories(fixture("categories_tree.json"), fixture("categories_navigation_config.json.gz"))
    snake(categories)
    assert len(categories) == 12
    design = categories[0]
    assert (design["id"], design["name"], design["slug"]) == (3, "Graphics & Design", "graphics-design")
    assert design["link"] == "https://www.fiverr.com/categories/graphics-design"
    logo = design["sub_categories"][0]
    assert (logo["id"], logo["name"], logo["slug"]) == (49, "Logo Design", "creative-logo-design")
    assert logo["link"] == "https://www.fiverr.com/categories/graphics-design/creative-logo-design"
    web = next(s for c in categories for s in c["sub_categories"] if s["id"] == 514)
    assert {"id": 2609, "name": "WordPress"} in web["nested_sub_categories"]
    assert next(c for c in categories if c["name"].startswith("Personal Growth"))["id"] == 7
    subs = [s for c in categories for s in c["sub_categories"]]
    assert len(subs) == 310 and sum(1 for s in subs if s["id"]) >= 240


def test_categories_without_the_menu_keep_null_ids():
    categories = parsers.parse_categories(fixture("categories_tree.json"))
    assert len(categories) == 12 and categories[0]["id"] is None
    assert categories[0]["sub_categories"][0]["slug"] == "creative-logo-design"
    assert parsers.parse_categories({}) == [] and parsers.parse_categories(None) == []


def test_suggestions():
    searches, sellers = parsers.parse_suggestions(fixture("suggestions_logo.json"))
    assert searches[0] == "logo design" and len(searches) == 8 and sellers == ["logos_designer6"]
    assert parsers.parse_suggestions(fixture("suggestions_no_result.json")) == ([], [])


# ---- refs ------------------------------------------------------------------------------------

@pytest.mark.parametrize("value, gig", [
    ("https://www.fiverr.com/logocraftz/create-modern-logo?context_referrer=search&pos=1", "logocraftz/create-modern-logo"),
    ("www.fiverr.com/Logocraftz/Create-Modern-Logo", "logocraftz/create-modern-logo"),
    ("logocraftz/create-modern-logo", "logocraftz/create-modern-logo"),
    ("/logocraftz/create-modern-logo/", "logocraftz/create-modern-logo"),
    ("https://it.fiverr.com/logocraftz/create-modern-logo", "logocraftz/create-modern-logo"),
])
def test_resolve_gig(value, gig):
    assert refs.resolve_gig(value) == gig
    assert refs.resolve_gig_or_id(value) == gig


@pytest.mark.parametrize("value", ["", "logocraftz", "417735249", "https://www.upwork.com/a/b", "categories/graphics-design",
                                   "https://www.fiverr.com/search/gigs?query=x", "a/b/c"])
def test_resolve_gig_refuses(value):
    with pytest.raises(ValueError):
        refs.resolve_gig(value)


def test_gig_id_form():
    assert refs.resolve_gig_or_id(" 417735249 ") == "417735249" and refs.is_gig_id("417735249")
    assert not refs.is_gig_id("logocraftz/x")
    with pytest.raises(ValueError, match="numeric gig id"):
        refs.resolve_gig_or_id("logocraftz")


@pytest.mark.parametrize("value, seller", [
    ("logocraftz", "logocraftz"), ("@LogoCraftz", "logocraftz"), ("https://www.fiverr.com/logocraftz?source=gig", "logocraftz"),
    ("https://www.fiverr.com/users/logocraftz", "logocraftz"), ("fiverr.com/logocraftz/some-gig", "logocraftz"),
    ("https://www.fiverr.com/agencies/colordesk", "agencies/colordesk"), ("john_smith2298", "john_smith2298"),
])
def test_resolve_seller(value, seller):
    assert refs.resolve_seller(value) == seller


@pytest.mark.parametrize("value", ["", "categories", "https://www.fiverr.com/categories/graphics-design",
                                   "https://example.com/logocraftz", "a b", "x"])
def test_resolve_seller_refuses(value):
    with pytest.raises(ValueError):
        refs.resolve_seller(value)


def test_resolve_category():
    assert refs.resolve_category("graphics-design/creative-logo-design") == "graphics-design/creative-logo-design"
    assert refs.resolve_category("https://www.fiverr.com/categories/Programming-Tech/website-development/"
                                 "wordpress-development?source=category_tree") == \
        "programming-tech/website-development/wordpress-development"
    for bad, message in (("graphics-design", "top category"), ("https://www.fiverr.com/categories/graphics-design", "top category"),
                         ("graphics-design/buy/creative-logo-design/minimalist", "filtered landing page"),
                         ("https://example.com/categories/a/b", "fiverr.com link"), ("a/b/c/d", "category link")):
        with pytest.raises(ValueError, match=message):
            refs.resolve_category(bad)


def test_resolve_attributes():
    assert refs.resolve_attributes("style:retro, logo_type:mascot,logo_type:emblem,style:retro") == \
        {"logo_type": ["mascot", "emblem"], "style": ["retro"]}
    for bad, message in (("style", "name:value"), ("", "name:value"), ("seller_level:na", "param of its own: seller_level"),
                         ("gig_price_range:1", "min_price / max_price"), ("service_offerings:subscription", "does not filter"),
                         ("style:a|pro:any", "name:value")):
        with pytest.raises(ValueError, match=message):
            refs.resolve_attributes(bad)


def test_cursor_round_trip():
    cursor = refs.review_cursor("6aa2aa3fb0246a7e6cffa232", 0.70956004)
    assert refs.resolve_cursor(cursor) == cursor
    assert refs.cursor_params(cursor) == {"last_star_rating_id": "6aa2aa3fb0246a7e6cffa232",
                                          "last_review_id": "6aa2aa3fb0246a7e6cffa232", "last_score": "0.70956004"}
    assert refs.cursor_params(refs.review_cursor("6aa2aa3fb0246a7e6cffa232", None))["last_score"] == "0"
    assert refs.cursor_params(None) == {}
    for bad in ("", "abc", "6aa2aa3fb0246a7e6cffa232", "6aa2aa3fb0246a7e6cffa232~x", "2"):
        with pytest.raises(ValueError, match="next_cursor"):
            refs.resolve_cursor(bad)


def test_level_names_cover_every_spelling():
    assert [parsers.level_name(v) for v in ("top_rated_seller", "LEVEL_TRS", "level_two_seller", "LEVEL_TWO",
                                            "level_one_seller", "LEVEL_ONE", "na", "NEW_SELLER", "")] == \
        ["top_rated", "top_rated", "level_2", "level_2", "level_1", "level_1", "new", "new", "new"]
    assert parsers.level_name(None) is None and parsers.level_name("something_else") is None
