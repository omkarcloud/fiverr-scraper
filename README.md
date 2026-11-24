# 🚀 Fiverr Scraper

Fiverr Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Fiverr data for free.

## ✨ What Can I Get?

- 🎯 **Full details of 1.3M+ gigs** — packages, prices, delivery days, revisions, extras, FAQ, gallery & rating breakdown
- 🔎 **Search 310 sub-categories across 12 categories** — filter by seller level, country, language, price, delivery time & Pro
- ⭐ **Real buyer reviews, 26,000+ on a single gig** — rating, comment, buyer country, price range, duration & the seller's reply
- 👤 **Seller profiles from 174 countries** — level, rating, languages, skills, education, certifications, clients & hourly rate

## 💼 Example: A Full Fiverr Gig

```json
{
  "id": 167747863,
  "title": "design converting amazon listing images, product infographics photo editing",
  "link": "https://www.fiverr.com/deryano/design-amazon-images-infographics-and-lifestyle",
  "category": { "name": "Graphics & Design", "slug": "graphics-design" },
  "sub_category": { "id": 53, "name": "Image Editing", "slug": "image-editing" },
  "tags": ["amazon listing", "product images", "amazon images"],
  "price_from": 100,
  "currency": "USD",
  "packages": [
    { "tier": "basic", "name": "3 x INFOGRAPHICS /ENHANCED IMAGE", "price": 100, "delivery_days": 3, "revisions": 5 },
    { "tier": "premium", "name": "9 x INFOGRAPHICS / LIFESTYLE IMAGES", "price": 245, "delivery_days": 4, "revisions": 5 }
  ],
  "rating": 4.9,
  "review_count": 847,
  "rating_details": { "communication": 4.9, "quality_of_delivery": 4.9, "value_for_money": 4.8 },
  "reviews": [
    { "rating": 5.0, "comment": "Omar did an outstanding job creating the images for our Amazon FBA listing.…", "reviewer": { "country": "Spain" }, "order": { "price_min": 200, "price_max": 400, "duration_days": 6 } }
  ],
  "orders_in_queue": 1,
  "is_pro": true,
  "notable_clients": [{ "name": "Dermacol", "domain": "dermacol.com", "industry": "Beauty & Cosmetics Products" }],
  "seller": { "username": "deryano", "display_name": "Omar Studios", "level": "top_rated", "country_code": "US", "member_since": "2016-09-18", "completed_orders": 15800, "hourly_rate": 100 }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Fiverr Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/fiverr-scraper
cd fiverr-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

Fiverr sits behind HUMAN (PerimeterX) and Cloudflare. The scraper gets through over plain HTTP, with no browser.

Your own connection is enough to start. Fiverr can block one IP for a few hours after about 150 calls: for volume, set a proxy with `FIVERR_PROXY=http://user:pass@host:port`.

Outside India, Fiverr mixes ads into its search and category pages. The scraper leaves them out, so a page holds about 28 gigs instead of 48.

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/gigs/details?gig=deryano/design-amazon-images-infographics-and-lifestyle"
```

```json
{
  "id": 167747863,
  "title": "design converting amazon listing images, product infographics photo editing",
  "link": "https://www.fiverr.com/deryano/design-amazon-images-infographics-and-lifestyle",
  "status": "approved",
  "price_from": 100,
  "currency": "USD",
  "packages": [
    { "tier": "basic", "name": "3 x INFOGRAPHICS /ENHANCED IMAGE", "price": 100, "delivery_days": 3, "revisions": 5 }
  ],
  "rating": 4.9,
  "review_count": 847,
  "orders_in_queue": 2,
  "saved_count": 1353,
  "is_pro": true,
  "seller": { "username": "deryano", "display_name": "Omar Studios", "level": "top_rated", "country_code": "US", "completed_orders": 15800 }
}
```

All 9 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

9 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Gig Details | `/gigs/details` | The whole gig in one call: packages, FAQ, gallery, reviews, seller |
| Search Suggestions | `/gigs/suggestions` | What buyers search for, plus matching seller usernames |
| Search Gigs | `/gigs/search` | Gigs by keyword, seller, country, language, price and delivery |
| Gig Reviews | `/gigs/reviews` | Rating, comment, buyer country, order price and seller reply |
| Seller Details | `/sellers/details` | Level, rating, skills, education, clients, work history and hourly rate |
| Seller Gigs | `/sellers/gigs` | Every gig a seller offers, with prices and ratings |
| Seller Reviews | `/sellers/reviews` | Reviews across all of a seller's gigs |
| Category Gigs | `/categories/gigs` | Any category's gigs, with the same filters as search |
| Categories | `/categories/list` | All 12 categories and 310 sub-categories with their ids |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-fiverr-scraper-free-200-calls/pricing) — 200 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-fiverr-scraper-free-200-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-fiverr-scraper-free-200-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/gigs/details",
    params={"gig": "deryano/design-amazon-images-infographics-and-lifestyle"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Fiverr Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/fiverr-scraper-github-whatsapp)

[![Ask Us by Email about Fiverr Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Fiverr%20Scraper%20API&body=I%20need%20help%20using%20the%20Fiverr%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/fiverr-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/fiverr-scraper)
