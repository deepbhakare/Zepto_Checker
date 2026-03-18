"""
Zepto Hot Wheels Stock Checker
Monitors specific Hot Wheels products on Zepto for stock availability
across multiple Pune locations and sends Telegram alerts.

Locations monitored:
  - Viman Nagar, Pune 411014
  - Keshav Nagar, Pune 411036
"""

import os
import json
import hashlib
import requests
import time
from datetime import datetime, timezone, timedelta

# ─── CONFIG ────────────────────────────────────────────────────────────────────

# Your two Pune locations (lat, long, label)
LOCATIONS = [
    {"label": "Viman Nagar",  "lat": 18.5679,  "lng": 73.9143, "pincode": "411014"},
    {"label": "Keshav Nagar", "lat": 18.5524,  "lng": 73.9359, "pincode": "411036"},
]

# ── Products to watch ─────────────────────────────────────────────────────────
# Format: "Label": "pvid from Zepto URL"
WATCH_PRODUCTS = {
    "HW Mercedes Benz 300 SEL 6.8 AMG Premium":  "bfa7a07e-b757-457c-8ec2-8a2fbb60a63e",
    "HW Mercedes Benz Driver 1 F1 Race Team":     "c8863d71-4d5d-4664-a53d-e0a33e0a45fe",
    "HW LB Works Lamborghini Huracan Coupe":      "2d858651-fb20-468b-979a-e0d099c472d1",
    "HW Ferrari 12 Cylindri":                     "a2d91bdd-c5b1-44ff-a3d6-ab48f1ff5103",
    "HW VCARB Driver 1 Racing Bulls F1":          "23fe0075-e2e4-4f98-940f-2afb168ec334",
    "HW 85 Honda City Turbo II":                  "115b2807-59eb-426f-a75e-7d81f9bc40d2",
    "HW Corvette C7 Z06":                         "4e37dc69-b7c1-4d9a-9e9f-413cb7e4e838",
    "HW 87 Ford Sierra Cosworth":                 "08a93ef0-ac2e-4c63-b609-2afcb088f181",
    "HW Ferrari 250 GTO Team Transport":          "4596baaf-95b9-4a99-a3f1-fbadc3bf1090",
    "HW 17 Pagani Huayra Roadster":               "bf753e65-09dc-4c5d-8e17-68f24b472e6d",
    "HW 2019 Audi R8 Spyder":                     "758df8ff-4c5e-4859-bf66-ffd70adabfbf",

    # ── ADD MORE BELOW ────────────────────────────────────────────────────────
    # "Label": "pvid from zepto URL",
}

# ─── CREDENTIALS ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

STATE_FILE = "seen_products_zepto.json"

# ─── ZEPTO API HEADERS ────────────────────────────────────────────────────────
# These mimic a real browser request to Zepto's internal API
def get_headers(lat: float, lng: float) -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://www.zepto.com",
        "Referer": "https://www.zepto.com/",
        "x-latitude": str(lat),
        "x-longitude": str(lng),
        "x-app-version": "12.0.0",
        "x-platform": "web",
    }

# ─── STATE MANAGEMENT ─────────────────────────────────────────────────────────

def load_seen() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_seen(data: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def make_key(pvid: str, location_label: str) -> str:
    raw = f"{pvid}_{location_label}"
    return hashlib.md5(raw.encode()).hexdigest()

# ─── ZEPTO PRODUCT CHECK ──────────────────────────────────────────────────────

def check_product_zepto(pvid: str, lat: float, lng: float) -> dict | None:
    """
    Try to fetch product availability from Zepto's internal API.
    Falls back to scraping the product page if API fails.
    """
    # Method 1: Zepto internal product detail API
    api_url = f"https://api.zepto.com/api/v1/pdp/product-details/?product_variant_id={pvid}"
    headers = get_headers(lat, lng)

    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return _parse_api_response(data, pvid)
    except Exception as e:
        print(f"    [API] Failed: {e}")

    # Method 2: Zepto product page scrape
    return _scrape_product_page(pvid, lat, lng)


def _parse_api_response(data: dict, pvid: str) -> dict | None:
    """Parse Zepto API JSON response for stock status."""
    try:
        # Walk common Zepto API response structures
        product = (
            data.get("data", {}).get("product") or
            data.get("product") or
            data.get("data") or
            {}
        )
        name  = product.get("name") or product.get("productName") or "Unknown"
        price = str(product.get("discountedSellingPrice") or product.get("mrp") or product.get("price") or "")

        # Stock detection
        in_stock = True
        inventory = product.get("inventory", {})
        if isinstance(inventory, dict):
            qty = inventory.get("quantity", 1)
            in_stock = qty > 0
        elif "outOfStock" in product:
            in_stock = not product["outOfStock"]
        elif "available" in product:
            in_stock = product["available"]

        return {"pvid": pvid, "name": name, "price": price, "in_stock": in_stock}
    except Exception as e:
        print(f"    [PARSE] {e}")
        return None


def _scrape_product_page(pvid: str, lat: float, lng: float) -> dict | None:
    """Scrape Zepto product page as fallback."""
    import re
    from bs4 import BeautifulSoup

    # Construct a search URL using pvid
    url = f"https://www.zepto.com/pn/product/pvid/{pvid}"
    headers = get_headers(lat, lng)
    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

    try:
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            print(f"    [SCRAPE] HTTP {resp.status_code}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        page_text = soup.get_text()

        # Name
        name = "Unknown"
        h1 = soup.find("h1")
        if h1:
            name = h1.get_text(strip=True)
        elif soup.title and soup.title.string:
            name = soup.title.string.strip()

        # Price
        price = ""
        price_match = re.search(r'₹\s*([\d,]+)', page_text)
        if price_match:
            price = price_match.group(1).replace(",", "")

        # Stock status
        out_of_stock = bool(re.search(r'out\s*of\s*stock|not\s*available|sold\s*out|notify\s*me', page_text, re.I))
        add_to_cart  = bool(re.search(r'add\s*to\s*(cart|bag)|buy\s*now', page_text, re.I))
        in_stock = add_to_cart and not out_of_stock

        return {"pvid": pvid, "name": name, "price": price, "in_stock": in_stock}

    except Exception as e:
        print(f"    [SCRAPE] {e}")
        return None

# ─── NOTIFICATIONS ─────────────────────────────────────────────────────────────

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[SKIP] Telegram not configured.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        r.raise_for_status()
        print("[OK] Telegram sent ✅")
    except Exception as e:
        print(f"[ERROR] Telegram: {e}")


def notify(alerts: list[dict]):
    if not alerts:
        return

    IST = timezone(timedelta(hours=5, minutes=30))
    ts  = datetime.now(IST).strftime('%d %b %Y, %I:%M %p IST')

    lines = [
        "🚗 <b>Zepto Hot Wheels Alert!</b>",
        f"🕐 {ts}\n",
        "🔔 <b>Back in stock / Now available:</b>",
    ]

    for a in alerts:
        price_str    = f" — ₹{a['price']}" if a.get("price") else ""
        location_str = f" 📍 {a['location']}"
        url = f"https://www.zepto.com/pn/product/pvid/{a['pvid']}"
        lines.append(f"• <a href=\"{url}\">{a['name']}</a>{price_str}{location_str}")

    send_telegram("\n".join(lines))

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"Zepto Checker — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Watching {len(WATCH_PRODUCTS)} products × {len(LOCATIONS)} locations")
    print(f"{'='*60}\n")

    seen   = load_seen()
    alerts = []

    for location in LOCATIONS:
        loc_label = location["label"]
        lat = location["lat"]
        lng = location["lng"]
        print(f"\n📍 [{loc_label}] lat={lat}, lng={lng}")

        loc_seen = seen.get(loc_label, {})

        for label, pvid in WATCH_PRODUCTS.items():
            print(f"  Checking: {label}")
            result = check_product_zepto(pvid, lat, lng)

            if not result:
                print(f"    ⚠️  Could not fetch, skipping.")
                time.sleep(1)
                continue

            in_stock = result["in_stock"]
            name     = result.get("name") or label
            price    = result.get("price", "")
            key      = make_key(pvid, loc_label)
            prev     = loc_seen.get(key)

            status = "✅ IN STOCK" if in_stock else "❌ Out of Stock"
            print(f"    {status} | {name[:50]} | ₹{price}")

            if prev is None:
                # First time seeing — record status
                loc_seen[key] = {
                    "label": label,
                    "name": name,
                    "pvid": pvid,
                    "in_stock": in_stock,
                    "first_seen": datetime.now().isoformat(),
                }
                # Alert if already in stock on first check
                if in_stock:
                    alerts.append({"name": name, "price": price, "pvid": pvid, "location": loc_label})

            elif not prev.get("in_stock") and in_stock:
                # Was out of stock → now in stock!
                print(f"    🎉 BACK IN STOCK at {loc_label}!")
                alerts.append({"name": name, "price": price, "pvid": pvid, "location": loc_label})
                loc_seen[key]["in_stock"] = True
                loc_seen[key]["name"]     = name

            else:
                loc_seen[key]["in_stock"] = in_stock

            time.sleep(1)

        seen[loc_label] = loc_seen

    save_seen(seen)
    notify(alerts)

    if not alerts:
        print("\n✅ No stock changes. All quiet.")
    else:
        print(f"\n🚨 {len(alerts)} alert(s) sent!")


if __name__ == "__main__":
    main()
