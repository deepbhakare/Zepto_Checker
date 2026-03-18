"""
Zepto Hot Wheels Stock Checker
Uses real browser cookies + storeId extracted from your Zepto session.
Monitors specific pvids and alerts via Telegram when stock is available.

HOW TO UPDATE COOKIES (every ~1 hour they expire):
  1. Open zepto.com in Chrome → open any Hot Wheels product
  2. Press F12 → Network tab → filter XHR/Fetch
  3. Find any request to zepto.com → Right click → Copy as cURL
  4. Update the COOKIES dict below with fresh values
  5. Commit scraper.py — bot will use new cookies immediately
"""

import os
import json
import hashlib
import requests
import time
import re
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# ─── CONFIG ────────────────────────────────────────────────────────────────────

# !! UPDATE THESE WHEN COOKIES EXPIRE !!
# Extract from your browser's Network tab (F12) on zepto.com
COOKIES = {
    "session_id":        "a54bf773-8bee-4cc6-8bfe-8bdc8900a9f3",
    "device_id":         "5748a738-9e60-439b-a12b-8c2bc2cf202d",
    "marketplace":       "SUPER_SAVER",
    "accessToken":       os.environ.get("ZEPTO_ACCESS_TOKEN", "eyJhbGciOiJIUzUxMiJ9.eyJ2ZXJzaW9uIjoxLCJzdWIiOiJmN2Q4OGE1NC1iNDdiLTQ1ZWItYTA2MS1hYzVmNjcxY2ViODUiLCJpYXQiOjE3NzM4NjM4ODcsImV4cCI6MTc3Mzg2NzQ4N30.IPvbcFiLIb6IiQfrImJ9GUyIOBK4HNoOpwKcXhNd0MCcjVHr7HomHHqL91niTSU0JciQJjdXE9rSZXoQ_Zyeqg"),
    "refreshToken":      "71fb3913-7f9a-45b2-abc4-a42eb649e607",
    "isAuth":            "true",
    "user_id":           "f7d88a54-b47b-45eb-a061-ac5f671ceb85",
    "latitude":          "18.561451870834524",
    "longitude":         "73.91288062557578",
    "pwa":               "false",
    "XSRF-TOKEN":        "b2vjINuvpRkIGI7LhtHcg%3Apada48ZFKhGPPloMR383osfRyGs.TtAZQcNCzChSXlFGVmZZ7lyUMXHX33dopoLnK%2BJFsLQ",
}

# Store IDs extracted from your cookies (serviceability field)
# These are YOUR actual Pune dark store IDs
LOCATIONS = [
    {
        "label":    "Viman Nagar",
        "store_id": "04b8b5aa-15dd-49f9-ada0-df4d94f119a4",  # from your cookie
        "lat":      18.561451870834524,
        "lng":      73.91288062557578,
    },
    # Keshav Nagar — update store_id after setting that address in Zepto app
    # and copying a fresh curl from that location
    {
        "label":    "Keshav Nagar",
        "store_id": "931f1ec1-e287-4412-9b52-df3f8ab9c95c",  # secondary store from cookie
        "lat":      18.5524,
        "lng":      73.9359,
    },
]

# ── Products to watch ─────────────────────────────────────────────────────────
# Format: "Label": "pvid from Zepto URL"
# How to find pvid: zepto.com/pn/.../pvid/XXXX-XXXX ← that's the pvid
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
    # How to add: Zepto app → product → Share → copy link → extract pvid
    # Example (in stock — use to test notifications):
    "TEST HW Birthday Burner (IN STOCK)": "4e7ff3b5-31df-43d4-95a3-c0e04058a4a5",
    # https://www.zepto.com/pn/hot-wheels-worldwide-basic-car-hw-birthday-burner-.../pvid/4e7ff3b5-31df-43d4-95a3-c0e04058a4a5
}

# ─── CREDENTIALS ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

STATE_FILE = "seen_products_zepto.json"

# ─── HEADERS ──────────────────────────────────────────────────────────────────
BASE_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en-IN;q=0.9,en;q=0.8",
    "Referer":         "https://www.zepto.com/",
    "sec-ch-ua":       '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest":  "document",
    "sec-fetch-mode":  "navigate",
    "sec-fetch-site":  "same-origin",
    "dnt":             "1",
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
    return hashlib.md5(f"{pvid}_{location_label}".encode()).hexdigest()

# ─── ZEPTO FETCH ──────────────────────────────────────────────────────────────

def build_session() -> requests.Session:
    """Build a requests session with real browser cookies."""
    session = requests.Session()
    for k, v in COOKIES.items():
        session.cookies.set(k, v, domain=".zepto.com")
    return session


def check_product(pvid: str, label: str, location: dict, session: requests.Session) -> dict | None:
    """
    Fetch a Zepto product page using real browser cookies.
    Detects stock status from page content.
    """
    # Build product URL with store context
    slug_url = f"https://www.zepto.com/pn/product/pvid/{pvid}"

    # Update location cookies for this request
    session.cookies.set("latitude",  str(location["lat"]),  domain=".zepto.com")
    session.cookies.set("longitude", str(location["lng"]),  domain=".zepto.com")

    # Try multiple URL patterns Zepto uses
    urls_to_try = [
        # Pattern 1: Direct pvid URL
        f"https://www.zepto.com/pn/product/pvid/{pvid}",
        # Pattern 2: Search by pvid
        f"https://www.zepto.com/search?query={pvid}",
    ]

    for url in urls_to_try:
        try:
            headers = {**BASE_HEADERS, "Referer": "https://www.zepto.com/search?query=hot+wheels"}
            resp = session.get(url, headers=headers, timeout=15, allow_redirects=True)
            print(f"    [{resp.status_code}] {url[:80]}")

            if resp.status_code == 200:
                result = _parse_page(resp.text, pvid, label)
                if result:
                    return result
        except Exception as e:
            print(f"    [ERROR] {e}")

    # Pattern 3: Use the actual product URL from Zepto (requires slug)
    # Try fetching via known slug pattern
    return _try_with_full_url(pvid, label, location, session)


def _try_with_full_url(pvid: str, label: str, location: dict, session: requests.Session) -> dict | None:
    """Try fetching the actual product page URL stored in WATCH_PRODUCTS."""
    # Map pvid back to full URL using known product slugs
    PRODUCT_URLS = {
        "bfa7a07e-b757-457c-8ec2-8a2fbb60a63e": "https://www.zepto.com/pn/hot-wheels-premium-car-culture-mercedes-benz-300-sel-68-amg-164-scale-collectible-toy-vehicle/pvid/bfa7a07e-b757-457c-8ec2-8a2fbb60a63e",
        "c8863d71-4d5d-4664-a53d-e0a33e0a45fe": "https://www.zepto.com/pn/hot-wheels-164-scale-premium-race-team-mercedes-benz-driver-1-die-cast-formula-1/pvid/c8863d71-4d5d-4664-a53d-e0a33e0a45fe",
        "2d858651-fb20-468b-979a-e0d099c472d1": "https://www.zepto.com/pn/hot-wheels-worldwide-basic-car-hw-lb-works-lamborghini-huracan-coupe-toy-car/pvid/2d858651-fb20-468b-979a-e0d099c472d1",
        "a2d91bdd-c5b1-44ff-a3d6-ab48f1ff5103": "https://www.zepto.com/pn/hot-wheels-worldwide-basic-car-hw-ferrari-12-cylindri-toy-car-for-kids-and-collectors/pvid/a2d91bdd-c5b1-44ff-a3d6-ab48f1ff5103",
        "23fe0075-e2e4-4f98-940f-2afb168ec334": "https://www.zepto.com/pn/hot-wheels-164-scale-premium-race-team-vcarb-driver-1-racing-bulls-die-cast-formula-1/pvid/23fe0075-e2e4-4f98-940f-2afb168ec334",
        "115b2807-59eb-426f-a75e-7d81f9bc40d2": "https://www.zepto.com/pn/hot-wheels-worldwide-basic-car-hw-85-honda-city-turbo-ii-toy-car-for-kids-and-collectors/pvid/115b2807-59eb-426f-a75e-7d81f9bc40d2",
        "4e37dc69-b7c1-4d9a-9e9f-413cb7e4e838": "https://www.zepto.com/pn/hot-wheels-worldwide-basic-car-hw-corvette-c7-z06-toy-car-for-kids-and-collectors/pvid/4e37dc69-b7c1-4d9a-9e9f-413cb7e4e838",
        "08a93ef0-ac2e-4c63-b609-2afcb088f181": "https://www.zepto.com/pn/hot-wheels-worldwide-basic-car-hw-87-ford-sierra-cosworth-toy-car-for-kids-and-collectors/pvid/08a93ef0-ac2e-4c63-b609-2afcb088f181",
        "4596baaf-95b9-4a99-a3f1-fbadc3bf1090": "https://www.zepto.com/pn/hot-wheels-team-transport-ferrari-250-gto-gift-for-racing-collectors/pvid/4596baaf-95b9-4a99-a3f1-fbadc3bf1090",
        "bf753e65-09dc-4c5d-8e17-68f24b472e6d": "https://www.zepto.com/pn/hot-wheels-worldwide-basic-car-hw-17-pagani-huayra-roadster-1-cabriolet-decapotable-toy-car/pvid/bf753e65-09dc-4c5d-8e17-68f24b472e6d",
        "758df8ff-4c5e-4859-bf66-ffd70adabfbf": "https://www.zepto.com/pn/hot-wheels-worldwide-basic-car-hw-2019-audi-r8-spyder-toy-car-for-kids-and-collectors/pvid/758df8ff-4c5e-4859-bf66-ffd70adabfbf",
        "4e7ff3b5-31df-43d4-95a3-c0e04058a4a5": "https://www.zepto.com/pn/hot-wheels-worldwide-basic-car-hw-birthday-burner-toy-car-for-kids-and-collectors/pvid/4e7ff3b5-31df-43d4-95a3-c0e04058a4a5",
    }

    url = PRODUCT_URLS.get(pvid)
    if not url:
        return None

    try:
        headers = {**BASE_HEADERS, "Referer": "https://www.zepto.com/search?query=hot+wheels"}
        resp = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        print(f"    [FULL URL] {resp.status_code}")
        if resp.status_code == 200:
            return _parse_page(resp.text, pvid, label)
    except Exception as e:
        print(f"    [FULL URL ERROR] {e}")
    return None


def _parse_page(html: str, pvid: str, label: str) -> dict | None:
    """Parse Zepto product page for stock status."""
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text()

    # Must have some product content
    if len(page_text) < 200:
        return None

    # Name
    name = label
    try:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            name = h1.get_text(strip=True)
        elif soup.title and soup.title.string:
            name = soup.title.string.strip()
    except Exception:
        pass

    # Price
    price = ""
    price_match = re.search(r'₹\s*([\d,]+)', page_text)
    if price_match:
        price = price_match.group(1).replace(",", "")

    # Stock status
    out_of_stock = bool(re.search(
        r'out\s*of\s*stock|not\s*available|sold\s*out|notify\s*me|currently\s*unavailable',
        page_text, re.I
    ))
    add_to_cart = bool(re.search(
        r'add\s*to\s*(cart|bag)|buy\s*now|\d+\s*min|add\b',
        page_text, re.I
    ))

    in_stock = add_to_cart and not out_of_stock

    print(f"    {'✅ IN STOCK' if in_stock else '❌ Out of Stock'} | {name[:50]} | ₹{price}")
    return {"pvid": pvid, "name": name, "price": price, "in_stock": in_stock}

# ─── NOTIFICATIONS ────────────────────────────────────────────────────────────

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[SKIP] Telegram not configured.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id":               TELEGRAM_CHAT_ID,
                "text":                  message,
                "parse_mode":            "HTML",
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
    lines = ["🚗 <b>Zepto Hot Wheels Alert!</b>", f"🕐 {ts}\n", "🔔 <b>Now available:</b>"]
    for a in alerts:
        price_str = f" — ₹{a['price']}" if a.get("price") else ""
        loc_str   = f" 📍 {a['location']}"
        url = f"https://www.zepto.com/pn/product/pvid/{a['pvid']}"
        lines.append(f"• <a href=\"{url}\">{a['name']}</a>{price_str}{loc_str}")
    send_telegram("\n".join(lines))

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"Zepto Checker — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Watching {len(WATCH_PRODUCTS)} products × {len(LOCATIONS)} locations")
    print(f"{'='*60}\n")

    seen    = load_seen()
    alerts  = []
    session = build_session()

    for location in LOCATIONS:
        loc_label = location["label"]
        print(f"\n📍 [{loc_label}]")

        loc_seen = seen.get(loc_label, {})

        for label, pvid in WATCH_PRODUCTS.items():
            print(f"\n  Checking: {label}")
            result = check_product(pvid, label, location, session)

            if not result:
                print(f"    ⚠️  Could not fetch.")
                time.sleep(1)
                continue

            in_stock = result["in_stock"]
            name     = result.get("name") or label
            price    = result.get("price", "")
            key      = make_key(pvid, loc_label)
            prev     = loc_seen.get(key)

            if prev is None:
                loc_seen[key] = {
                    "label": label, "name": name, "pvid": pvid,
                    "in_stock": in_stock,
                    "first_seen": datetime.now().isoformat(),
                }
                if in_stock:
                    alerts.append({"name": name, "price": price, "pvid": pvid, "location": loc_label})
            elif not prev.get("in_stock") and in_stock:
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