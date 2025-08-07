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


def seller_from(block: dict) -> str:
    # Use the explicit SellerName if present,
    # otherwise fallback to "Newegg"
    s = (block.get("Seller") or {}).get("SellerName")
    return s if s else "Newegg"


def parse_block(block: dict, url: str) -> dict:
    desc   = block.get("Description", {}) or {}
    review = block.get("Review", {}) or {}
    return {
        "url":         url,
        "title":       desc.get("Title", ""),
        "description": tidy(desc.get("BulletDescription", "")),
        "price":       block.get("FinalPrice", ""),
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
    return {
        "url":         url,
        "title":       j.get("title", ""),
        "description": tidy(j.get("description", "")),
        "price":       (j.get("pricing") or {}).get("price", ""),
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
        row = from_realtime(j_rt, url)
        if row["price"] and row["seller"]:
            return "✔", row

    # 2) Fallback to compare API
    j_cp = get_json(R_COMPARE.format(item, item))
    if j_cp:
        row2 = from_compare(j_cp, url)
        if row2["price"] and row2["seller"]:
            return "🛒", row2

    # 3) Final fallback to ScraperAPI's autoparse
    j_ap = get_json(AUTOPARSE + urllib.parse.quote(url, safe=""), wrap=False)
    if j_ap:
        row3 = from_autoparse(j_ap, url)
        if row3["title"]:
            return "🅿️", row3

    return "⚠️ empty", blank(url)


def main():
    urls = [u.strip() for u in Path(URLS_FILE).read_text().splitlines() if u.strip()]
    rows, total = [], len(urls)

    for idx, link in enumerate(urls, 1):
        code, data = scrape_one(link)
        rows.append(data)
        print(f"{idx}/{total} {code} {link}")
        time.sleep(DELAY_SEC)

    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n🎉  Done → {OUT_FILE} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
