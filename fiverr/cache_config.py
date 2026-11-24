"""Cache TTL per /fiverr/* endpoint (cache.py, keyed on the validated
params). A gig page and a seller page are parsed once and sliced: the gig
record serves gigs/details and gives gigs/reviews the gig's id; the seller
record serves sellers/details and sellers/gigs.
"""
from datetime import timedelta

# A listing reorders through the day and sellers go on and off line.
SEARCH_CACHE = timedelta(hours=1)
CATEGORY_GIGS_CACHE = timedelta(hours=1)
# One row per gig link: prices and packages change rarely, the queue and the review count daily.
GIG_CACHE = timedelta(hours=6)
# One row per seller: profile text changes rarely, the rating and the gig list daily.
SELLER_CACHE = timedelta(hours=6)
# Reviews only grow; a busy gig gets a few a day.
REVIEWS_CACHE = timedelta(hours=3)
# The seller's numeric id and rating summary behind sellers/reviews (one upstream call).
SELLER_REVIEWS_HEAD_CACHE = timedelta(hours=6)
# The category tree changes a few times a year.
CATEGORIES_CACHE = timedelta(hours=24)
# Suggestions follow what buyers type: stable within a day.
SUGGESTIONS_CACHE = timedelta(hours=12)
