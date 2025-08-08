import csv, json, re, time, urllib.parse, requests
from pathlib import Path
from json import JSONDecodeError

API_KEY   = "3ad6073b07dded11ca8a5906e3291baf"
WRAP      = f"https://api.scraperapi.com/?api_key={API_KEY}&url="
AUTOPARSE = f"https://api.scraperapi.com/?api_key={API_KEY}&autoparse=true&url="

R_REALTIME = "https://www.newegg.com/product/api/ProductRealtime?ItemNumber={}&IsVATPrice=true"
R_COMPARE  = ("https://www.newegg.com/product/api/CompareRecommendsItem"
              "?compareItemList={}&smc=10&isNeedBaseItemDeactivateInfo=true&parentItemList={} ")

URLS_FILE, OUT_FILE = "urls.txt", "newegg_products.csv"
DELAY_SEC, FIELDS   = 1.0, ["url", "title", "description", "price", "seller", "rating"]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/138.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
}


def fetch_html(url: str) -> str:
    target = WRAP + urllib.parse.quote(url, safe="")
    try:
        r = requests.get(target, headers=HEADERS, timeout=60)
        r.raise_for_status()
        return r.text or ""
    except requests.RequestException:
        return ""


def extract_title_from_html(html: str) -> str:
    if not html:
        return ""
    # Try og:title
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1).strip()
    # Try <title> ... </title>
    m = re.search(r"<title>([^<]+)</title>", html, re.I)
    if m:
        return m.group(1).strip()
    # Try JSON-LD product name
    m = re.search(r'"@type"\s*:\s*"Product"[\s\S]*?"name"\s*:\s*"([^"]+)"', html, re.I)
    if m:
        return m.group(1).strip()
    return ""


def extract_seller_from_html(html: str) -> str:
    if not html:
        return ""
    # Look for "Sold and shipped by <a>Seller</a>" pattern
    m = re.search(r"Sold\s+and\s+shipped\s+by\s*<[^>]*>([^<]+)</", html, re.I)
    if m:
        return m.group(1).strip()
    # Fallback: JSON-LD offers -> seller name
    m = re.search(r'"seller"\s*:\s*\{[\s\S]*?"name"\s*:\s*"([^"]+)"', html, re.I)
    if m:
        return m.group(1).strip()
    return ""


def extract_price_from_html(html: str) -> str:
    if not html:
        return ""
    # 1) OpenGraph / meta price
    m = re.search(r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        val = parse_price_value(m.group(1))
        if val:
            return val
    m = re.search(r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        val = parse_price_value(m.group(1))
        if val:
            return val
    # 2) JSON-LD offers price
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>', html, re.I):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        # could be dict or list
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") == "Product":
                offers = node.get("offers")
                if isinstance(offers, dict):
                    val = parse_price_value(offers.get("price"))
                    if val:
                        return val
                elif isinstance(offers, list):
                    for off in offers:
                        if isinstance(off, dict):
                            val = parse_price_value(off.get("price"))
                            if val:
                                return val
    # 3) Visible price text in common Newegg classes
    m = re.search(r'<[^>]*class=["\'][^"\']*price-current[^"\']*["\'][^>]*>([\s\S]*?)</[^>]+>', html, re.I)
    if m:
        # Strip HTML and keep digits, dots, commas
        txt = re.sub(r"<[^>]+>", " ", m.group(1))
        txt = re.sub(r"\s+", " ", txt).strip()
        val = parse_price_value(txt)
        if val:
            return val
    # 4) Generic itemprop="price" visible text
    m = re.search(r'itemprop=["\']price["\'][^>]*>([^<]+)<', html, re.I)
    if m:
        val = parse_price_value(m.group(1))
        if val:
            return val
    return ""


def fill_missing_from_html(row: dict) -> dict:
    if row.get("title") and row.get("seller"):
        # Still try to fill price if empty
        if row.get("price"):
            return row
    html = fetch_html(row.get("url", ""))
    if not row.get("title"):
        t = extract_title_from_html(html)
        if t:
            row["title"] = t
    if not row.get("seller"):
        s = extract_seller_from_html(html)
        if s:
            row["seller"] = s
    if not row.get("price"):
        p = extract_price_from_html(html)
        if p:
            row["price"] = p
    return row


def item_no(url: str) -> str | None:
    m = re.search(r"/p/([^/?#]+)", url, re.I)
    return m.group(1) if m else None


def get_json(url: str, wrap=True) -> dict | list | None:
    target = WRAP + urllib.parse.quote(url, safe="") if wrap else url
    try:
        r = requests.get(target, headers=HEADERS, timeout=60)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, JSONDecodeError):
        return None


def blank(url: str) -> dict:
    return {k: (url if k == "url" else "") for k in FIELDS}


def tidy(txt: str) -> str:
    return " | ".join(line.strip() for line in txt.splitlines() if line.strip()) if txt else ""


def parse_price_value(raw: object) -> str:
    if raw is None:
        return ""

    # Convert to float safely from diverse string formats
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        s = str(raw)
        s = s.strip()
        if not s:
            return ""

        # Handle European-style decimals ("," as decimal) when there's no dot
        if "," in s and "." not in s:
            # Keep digits and commas, then switch comma to dot
            s_clean = re.sub(r"[^\d,]", "", s).replace(",", ".")
        else:
            # Default: keep digits and dots, drop everything else (currency, spaces, commas)
            s_clean = re.sub(r"[^\d.]", "", s)

        try:
            value = float(s_clean) if s_clean else 0.0
        except ValueError:
            return ""

    # Filter out obviously bogus/sentinel prices
    # Newegg uses sentinel values ~100004-100012 when price is unavailable
    if value <= 0:
        return ""

    if 100000 <= value <= 100020:
        return ""

    return f"{value:.2f}"


def seller_from(block: dict) -> str:
    # Use the explicit SellerName if present,
    # otherwise fallback to "Newegg"
    s = (block.get("Seller") or {}).get("SellerName")
    return s if s else "Newegg"


def parse_block(block: dict, url: str) -> dict:
    desc   = block.get("Description", {}) or {}
    review = block.get("Review", {}) or {}
    price  = parse_price_value(block.get("FinalPrice"))
    return {
        "url":         url,
        "title":       desc.get("Title", ""),
        "description": tidy(desc.get("BulletDescription", "")),
        "price":       price,
        "seller":      seller_from(block),
        "rating":      review.get("RatingOneDecimal", "") or review.get("Rating", ""),
    }


def from_realtime(j: dict, url: str) -> dict:
    return parse_block(j.get("MainItem", {}) or {}, url)


def pick_offer(lst: list[dict]) -> dict:
    # Prefer the first offer that has its own SellerName + FinalPrice
    for o in lst:
        if o.get("FinalPrice") and (o.get("Seller") or {}).get("SellerName"):
            return o
    # Otherwise just pick the first with any FinalPrice
    for o in lst:
        if o.get("FinalPrice"):
            return o
    return {}


def from_compare(lst: list, url: str) -> dict:
    best = pick_offer(lst or [])
    return parse_block(best, url)


def from_autoparse(j: dict, url: str) -> dict:
    pricing = (j.get("pricing") or {})
    raw_price = (
        pricing.get("price")
        or pricing.get("sale_price")
        or pricing.get("salePrice")
        or pricing.get("original_price")
        or pricing.get("originalPrice")
        or pricing.get("list_price")
        or pricing.get("listPrice")
        or ""
    )
    return {
        "url":         url,
        "title":       j.get("title", ""),
        "description": tidy(j.get("description", "")),
        "price":       parse_price_value(raw_price),
        "seller":      j.get("seller", ""),
        "rating":      j.get("rating", ""),
    }


def scrape_one(url: str) -> tuple[str, dict]:
    item = item_no(url)
    if not item:
        return "⚠️ bad-url", blank(url)

    # 1) Try realtime API
    j_rt = get_json(R_REALTIME.format(item))
    if j_rt:
        row = fill_missing_from_html(from_realtime(j_rt, url))
        if row["title"]:
            return "✔", row

    # 2) Fallback to compare API
    j_cp = get_json(R_COMPARE.format(item, item))
    if j_cp:
        row2 = fill_missing_from_html(from_compare(j_cp, url))
        if row2["title"]:
            return "🛒", row2

    # 3) Final fallback to ScraperAPI's autoparse
    j_ap = get_json(AUTOPARSE + urllib.parse.quote(url, safe=""), wrap=False)
    if j_ap:
        row3 = from_autoparse(j_ap, url)
        if not row3.get("title"):
            row3 = fill_missing_from_html(row3)
        if row3["title"]:
            return "🅿️", row3

    return "⚠️ empty", blank(url)


def main():
    urls = [u.strip() for u in Path(URLS_FILE).read_text().splitlines() if u.strip()]
    rows, failed, total = [], [], len(urls)

    for idx, link in enumerate(urls, 1):
        code, data = scrape_one(link)
        if data.get("title") or data.get("price"):
            rows.append(data)
            print(f"{idx}/{total} {code} {link}")
        else:
            failed.append(link)
            print(f"{idx}/{total} ⏭️ SKIP {link} (no usable data)")
        time.sleep(DELAY_SEC)

    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    # Save failures for inspection/retry
    if failed:
        Path("failed_urls.txt").write_text("\n".join(failed), encoding="utf-8")

    print(f"\n🎉  Done → {OUT_FILE} ({len(rows)} rows)")
    if failed:
        print(f"⚠️  Skipped {len(failed)} URL(s) → failed_urls.txt")


if __name__ == "__main__":
    main()
