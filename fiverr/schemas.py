"""Marshmallow request schemas for every /fiverr/* route.

ONE param per input (never a sibling `url` / `id` pair):

    gig        a gig link or its <seller>/<gig-slug> path; gigs/reviews also
               takes the numeric gig id
    seller     a username or a profile link
    category   a category link or its <category>/<sub-category> path, a
               nested sub-category as a third segment

A value Fiverr would silently ignore is refused here: an unknown sort, a
seller level it does not have, a `pro=false`. The category's own filters
(logo style, file format, ...) go in `attributes` as name:value pairs; the
names and values a listing accepts come back in its answer.
"""
from marshmallow import ValidationError, pre_load, validates_schema

import schema_fields
from schema_fields import BaseSchema as _SharedBaseSchema
from schema_fields import (ChoiceField, CommaListField, LimitField, PageField, PositiveInt, Price,
                           QueryField, RefField, StrippedString, TrueOnlyFlag)
from fiverr import refs


class BaseSchema(_SharedBaseSchema):
    """The base of every /fiverr/* schema."""

    @pre_load
    def empty_is_absent(self, data, **kwargs):
        """An optional param sent empty (`page=`: a form or an automation
        that sends every field) is the absent param, so it takes its
        default (`page=` was refused as not a valid integer). A required
        param sent empty is still refused."""
        required = {field.data_key or name for name, field in self.fields.items() if field.required}
        return {key: value for key, value in data.items()
                if key in required or not (isinstance(value, str) and not value.strip())}


MAX_PAGE = 100            # Fiverr itself stops at page 11 (search) and 21 (category): later pages answer empty
MAX_REVIEWS = 50          # reviews per call: Fiverr serves 5 a call, so 10 upstream calls at most
DEFAULT_REVIEWS = 20


class GigRefField(RefField):
    resolver = staticmethod(refs.resolve_gig)


class GigOrIdRefField(RefField):
    resolver = staticmethod(refs.resolve_gig_or_id)


class SellerRefField(RefField):
    resolver = staticmethod(refs.resolve_seller)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class AttributesField(RefField):
    resolver = staticmethod(refs.resolve_attributes)


class CursorField(RefField):
    resolver = staticmethod(refs.resolve_cursor)


class CodeListField(CommaListField):
    """'us, GB' -> ['US', 'GB']: ISO codes checked against the real list, with a short message."""

    def __init__(self, codes, what, upper=True, **kwargs):
        super().__init__(upper=upper, **kwargs)
        self._codes, self._what = codes, what

    def _deserialize(self, value, attr, data, **kwargs):
        items = super()._deserialize(value, attr, data, **kwargs)
        for item in items or []:
            if item.upper() not in self._codes and item.lower() not in self._codes:
                raise ValidationError(f"'{item}' is not {self._what}.")
        return list(dict.fromkeys(i.upper() if self.upper else i.lower() for i in items)) if items else None


class _ListingFilters(BaseSchema):
    """The filters and the sort every gig listing takes."""
    sort = ChoiceField(refs.SORTS, metadata={
        "description": "order of the gigs: relevance, best_selling or newest (Fiverr's own default when left out)"})
    seller_level = CommaListField(value_map=refs.SELLER_LEVELS, upper=False, metadata={
        "description": "seller levels, comma-separated: top_rated, level_2, level_1, new"})
    seller_country = CodeListField(schema_fields.COUNTRY_CODES, "a 2-letter country code", metadata={
        "description": "countries the seller lives in, as 2-letter codes, comma-separated (US,GB)"})
    seller_language = CodeListField(schema_fields.LANGUAGE_CODES, "a 2-letter language code", upper=False, metadata={
        "description": "languages the seller speaks, as 2-letter codes, comma-separated (en,es)"})
    delivery_time = ChoiceField(list(refs.DELIVERY_TIMES), metadata={
        "description": "delivered within this many days: 1, 3 or 7"})
    min_price = Price(metadata={"description": "lowest starting price, in USD"})
    max_price = Price(metadata={"description": "highest starting price, in USD"})
    pro = TrueOnlyFlag(metadata={"description": "true = only Fiverr Pro gigs"})
    online = TrueOnlyFlag(metadata={"description": "true = only sellers who are online now"})
    hourly = TrueOnlyFlag(metadata={"description": "true = only sellers who also work at an hourly rate"})
    agency = TrueOnlyFlag(metadata={"description": "true = only gigs of agencies"})
    attributes = AttributesField(required=False, load_default=None, metadata={
        "description": "the category's own filters as name:value pairs, comma-separated (style:retro,file_format:svg); "
                       "the names and values a listing accepts are in `attributes` of its answer"})
    nested_sub_category = PositiveInt(metadata={
        "description": "id of a nested sub-category (from /fiverr/categories/list)"})
    page = PageField(max_page=MAX_PAGE, metadata={"description": "page number, 48 gigs a page"})

    @validates_schema
    def _price_range(self, data, **kwargs):
        low, high = data.get("min_price"), data.get("max_price")
        for name, value in (("min_price", low), ("max_price", high)):
            if value is not None and value > refs.PRICE_CEILING:
                raise ValidationError(f"Must be at most {refs.PRICE_CEILING}.", name)
        if low is not None and high is not None and low > high:
            raise ValidationError("Must not be above max_price.", "min_price")


class GigSearchSchema(_ListingFilters):
    query = QueryField(metadata={"description": "what to search for (logo design)"})
    sub_category = PositiveInt(metadata={
        "description": "id of a sub-category to search inside (from /fiverr/categories/list)"})

    @validates_schema
    def _nested_needs_sub(self, data, **kwargs):
        if data.get("nested_sub_category") and not data.get("sub_category"):
            raise ValidationError("Needs sub_category: a nested sub-category belongs to one.", "nested_sub_category")


class CategoryGigsSchema(_ListingFilters):
    category = CategoryRefField(metadata={
        "description": "a Fiverr category link, or its <category>/<sub-category> path "
                       "(graphics-design/creative-logo-design); a nested sub-category as a third segment"})


class GigDetailsSchema(BaseSchema):
    gig = GigRefField(metadata={
        "description": "a Fiverr gig link, or its <seller>/<gig-slug> path"})


class _ReviewsPaging(BaseSchema):
    sort = ChoiceField(refs.REVIEW_SORTS, load_default="relevant", metadata={
        "description": "relevant (Fiverr's default order) or recent (newest first)"})
    limit = LimitField(default=DEFAULT_REVIEWS, max_size=MAX_REVIEWS, metadata={
        "description": "how many reviews to return (default 20, at most 50)"})
    cursor = CursorField(required=False, load_default=None, metadata={
        "description": "next_cursor of the previous answer, for the reviews after it"})


class GigReviewsSchema(_ReviewsPaging):
    gig = GigOrIdRefField(metadata={
        "description": "a numeric gig id, a Fiverr gig link, or its <seller>/<gig-slug> path"})
    stars = PositiveInt(max_value=5, metadata={"description": "only reviews whose rating rounds to this many stars: 1 to 5"})
    business_only = TrueOnlyFlag(metadata={"description": "true = only reviews by business buyers"})


class SellerSchema(BaseSchema):
    seller = SellerRefField(metadata={
        "description": "a Fiverr username, or a profile link"})


class SellerReviewsSchema(_ReviewsPaging):
    seller = SellerRefField(metadata={
        "description": "a Fiverr username, or a profile link"})


class CategoriesListSchema(BaseSchema):
    pass


class SuggestionsSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={"description": "the start of a search (logo)"})
