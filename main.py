"""Use the scraper straight from Python, no server needed.

    python main.py

Each call validates its params with the same schema the API uses (so the
defaults apply) and returns the same JSON the API does, except that a list
keeps its `pagination` block instead of next / previous links. The results
are written to output/*.json.
"""
import json
import os

from fiverr import api, schemas
from schema_fields import load_query

os.makedirs("output", exist_ok=True)


def run(schema_cls, impl, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return impl(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # one gig in full: packages, prices, FAQ, gallery, rating breakdown, reviews and the seller
    save("gigs_details.json", run(schemas.GigDetailsSchema, api.gigs_details, gig='deryano/design-amazon-images-infographics-and-lifestyle'))

    # what Fiverr suggests for the start of a search, plus matching sellers
    save("gigs_suggestions.json", run(schemas.SuggestionsSchema, api.gigs_suggestions, query='logo'))

    # one page of gigs for a keyword, with the filters that keyword's category offers
    save("gigs_search.json", run(schemas.GigSearchSchema, api.gigs_search, query='logo design'))
