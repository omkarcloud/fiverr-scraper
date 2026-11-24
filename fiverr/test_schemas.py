"""Offline tests for the /fiverr/* request schemas.

    python -m pytest fiverr/test_schemas.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fiverr import schemas  # noqa: E402
from schema_fields import load_query  # noqa: E402


def ok(schema, **query):
    data, error = load_query(schema, query)
    assert error is None, error
    return data


def bad(schema, field, **query):
    data, error = load_query(schema, query)
    assert data is None and field in error["errors"], error
    return error["errors"][field][0]


def test_every_field_has_a_description():
    for name in dir(schemas):
        schema = getattr(schemas, name)
        if isinstance(schema, type) and issubclass(schema, schemas.BaseSchema) and schema is not schemas.BaseSchema:
            for field_name, field in schema().fields.items():
                assert field.metadata.get("description"), f"{name}.{field_name}"


# ---- gigs/search -----------------------------------------------------------------------------

def test_search_defaults():
    data = ok(schemas.GigSearchSchema, query="  logo   design ")
    assert data["query"] == "logo design" and data["page"] == 1
    assert all(data[name] is None for name in ("sort", "seller_level", "seller_country", "seller_language",
                                               "delivery_time", "min_price", "max_price", "pro", "online", "hourly",
                                               "agency", "attributes", "sub_category", "nested_sub_category"))


def test_search_filters_become_the_sites_tokens():
    data = ok(schemas.GigSearchSchema, query="logo", sort="Best_Selling", seller_level="top_rated, level_2,new",
              seller_country="us,GB", seller_language="EN, es", delivery_time="3", min_price="10", max_price="200",
              pro="true", online="1", hourly="yes", agency="true", attributes="style:retro,logo_type:mascot",
              sub_category="49", nested_sub_category="2609", page="3")
    assert data["sort"] == "rating"
    assert data["seller_level"] == ["top_rated_seller", "level_two_seller", "na"]
    assert data["seller_country"] == ["US", "GB"] and data["seller_language"] == ["en", "es"]
    assert data["delivery_time"] == "3" and (data["min_price"], data["max_price"]) == (10, 200)
    assert data["pro"] is data["online"] is data["hourly"] is data["agency"] is True
    assert data["attributes"] == {"logo_type": ["mascot"], "style": ["retro"]}
    assert (data["sub_category"], data["nested_sub_category"], data["page"]) == (49, 2609, 3)
    assert ok(schemas.GigSearchSchema, query="logo", seller_language="EN,en, Es")["seller_language"] == ["en", "es"]
    assert ok(schemas.GigSearchSchema, query="logo", sort="newest")["sort"] == "new"
    assert ok(schemas.GigSearchSchema, query="logo", sort="relevance")["sort"] == "auto"


@pytest.mark.parametrize("field, value, message", [
    ("sort", "price_asc", "relevance, best_selling, newest"),      # Fiverr names it but does not sort by it
    ("seller_level", "level_3", "not one of"),
    ("seller_country", "zz", "not a 2-letter country code"),
    ("seller_language", "english", "not a 2-letter language code"),
    ("delivery_time", "2", "Must be one of: 1, 3, 7"),
    ("min_price", "-1", "greater than or equal to 0"),
    ("max_price", "60000", "at most 50000"),
    ("pro", "false", "Must be true, or not provided"),
    ("online", "maybe", "Must be true or false"),
    ("attributes", "style", "name:value"),
    ("attributes", "seller_level:na", "param of its own"),
    ("sub_category", "logo", "Not a valid integer"),
    ("page", "0", ""),
    ("page", "101", ""),
])
def test_search_refuses(field, value, message):
    assert message in bad(schemas.GigSearchSchema, field, query="logo", **{field: value})


def test_search_cross_field_rules():
    assert "max_price" in bad(schemas.GigSearchSchema, "min_price", query="logo", min_price="50", max_price="10")
    assert "sub_category" in bad(schemas.GigSearchSchema, "nested_sub_category", query="logo", nested_sub_category="2609")
    assert "required" in bad(schemas.GigSearchSchema, "query").lower()
    assert "Unknown" in bad(schemas.GigSearchSchema, "currency", query="logo", currency="EUR")


# ---- categories/gigs --------------------------------------------------------------------------

def test_category_forms():
    for value in ("graphics-design/creative-logo-design", "/categories/graphics-design/creative-logo-design",
                  "https://www.fiverr.com/categories/graphics-design/creative-logo-design?source=category_tree"):
        assert ok(schemas.CategoryGigsSchema, category=value)["category"] == "graphics-design/creative-logo-design"
    data = ok(schemas.CategoryGigsSchema, category="programming-tech/website-development/wordpress-development",
              sort="newest", seller_level="top_rated", page="21")
    assert data["category"].count("/") == 2 and data["sort"] == "new" and data["page"] == 21
    assert "top category" in bad(schemas.CategoryGigsSchema, "category", category="graphics-design")
    assert "fiverr.com link" in bad(schemas.CategoryGigsSchema, "category", category="https://example.com/categories/a/b")
    assert "required" in bad(schemas.CategoryGigsSchema, "category").lower()
    assert "Unknown" in bad(schemas.CategoryGigsSchema, "query", category="a/b", query="logo")
    assert "Unknown" in bad(schemas.CategoryGigsSchema, "sub_category", category="a/b", sub_category="49")


# ---- gigs/details, gigs/reviews ---------------------------------------------------------------

def test_gig_forms():
    for value in ("logocraftz/create-modern-logo", "https://www.fiverr.com/logocraftz/create-modern-logo?pos=1"):
        assert ok(schemas.GigDetailsSchema, gig=value)["gig"] == "logocraftz/create-modern-logo"
    assert "gig link" in bad(schemas.GigDetailsSchema, "gig", gig="417735249")       # an id cannot be opened
    assert "fiverr.com link" in bad(schemas.GigDetailsSchema, "gig", gig="https://www.upwork.com/a/b")
    assert "required" in bad(schemas.GigDetailsSchema, "gig").lower()


def test_gig_reviews():
    data = ok(schemas.GigReviewsSchema, gig="417735249")
    assert data == {"gig": "417735249", "sort": "relevant", "limit": 20, "cursor": None, "stars": None, "business_only": None}
    data = ok(schemas.GigReviewsSchema, gig="https://www.fiverr.com/logocraftz/create-modern-logo", sort="recent",
              limit="50", stars="4", business_only="true", cursor="6aa2aa3fb0246a7e6cffa232~0.70956004")
    assert data["gig"] == "logocraftz/create-modern-logo" and data["sort"] == "recent" and data["limit"] == 50
    assert data["stars"] == 4 and data["business_only"] is True and data["cursor"] == "6aa2aa3fb0246a7e6cffa232~0.70956004"
    assert "relevant, recent" in bad(schemas.GigReviewsSchema, "sort", gig="1", sort="date")
    assert bad(schemas.GigReviewsSchema, "stars", gig="1", stars="6")
    assert bad(schemas.GigReviewsSchema, "limit", gig="1", limit="51")
    assert "next_cursor" in bad(schemas.GigReviewsSchema, "cursor", gig="1", cursor="page2")
    assert "numeric gig id" in bad(schemas.GigReviewsSchema, "gig", gig="logocraftz")
    assert "true" in bad(schemas.GigReviewsSchema, "business_only", gig="1", business_only="false")


# ---- sellers ----------------------------------------------------------------------------------

def test_seller_forms():
    for value in ("logocraftz", "@Logocraftz", "https://www.fiverr.com/logocraftz", "fiverr.com/logocraftz?source=x"):
        assert ok(schemas.SellerSchema, seller=value)["seller"] == "logocraftz"
    assert ok(schemas.SellerSchema, seller="https://www.fiverr.com/agencies/colordesk")["seller"] == "agencies/colordesk"
    assert "username" in bad(schemas.SellerSchema, "seller", seller="categories")
    assert "fiverr.com link" in bad(schemas.SellerSchema, "seller", seller="https://example.com/logocraftz")
    assert "required" in bad(schemas.SellerSchema, "seller").lower()


def test_seller_reviews():
    data = ok(schemas.SellerReviewsSchema, seller="logocraftz")
    assert data == {"seller": "logocraftz", "sort": "relevant", "limit": 20, "cursor": None}
    assert "Unknown" in bad(schemas.SellerReviewsSchema, "stars", seller="logocraftz", stars="5")
    assert "next_cursor" in bad(schemas.SellerReviewsSchema, "cursor", seller="logocraftz", cursor="x")


# ---- categories/list, gigs/suggestions ---------------------------------------------------------

def test_categories_and_suggestions():
    assert ok(schemas.CategoriesListSchema) == {}
    assert "Unknown" in bad(schemas.CategoriesListSchema, "page", page="2")
    assert ok(schemas.SuggestionsSchema, query=" logo ")["query"] == "logo"
    assert "required" in bad(schemas.SuggestionsSchema, "query").lower()
    assert bad(schemas.SuggestionsSchema, "query", query="x" * 101)


def test_an_optional_param_sent_empty_is_the_absent_param():
    # a form or an automation that sends every field: each empty one takes its default
    empty = ok(schemas.GigSearchSchema, query="logo", page="", min_price="", max_price="", pro="", sub_category="")
    assert empty == ok(schemas.GigSearchSchema, query="logo")
    assert ok(schemas.GigReviewsSchema, gig="1500855", limit="", stars="", business_only="") == \
        ok(schemas.GigReviewsSchema, gig="1500855")
    assert bad(schemas.SuggestionsSchema, "query", query="")    # a required one sent empty is still refused
