import cloudscraper, re, random
from pathlib import Path
from urllib.parse import urljoin, urlparse

SITEMAP        = "https://www.newegg.com/xmlsitemap/ProductListKeywords_USA.xml"
TARGET_ITEMS   = 500      
SEARCH_PAGES   = 120      

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)

# grab raw sitemap (still HTML entities, totally fine for regex)
raw = scraper.get(SITEMAP, timeout=30).text
keyword_urls = re.findall(r"<loc>([^<]+)</loc>", raw)
random.shuffle(keyword_urls)

def is_product(url: str) -> bool:
    path = urlparse(url).path.lower()
    # must have "/p/" ...
    if "/p/" not in path:
        return False
    # ... but NOT "/p/pl" (that's the list prefix)
    if "/p/pl" in path:
        return False
    # final segment should be an item code like N82E168... or 14P-000V-007T0
    item_code = path.split("/p/")[-1].split("/")[0]
    # simple heuristic: item code has at least one digit and one letter
    return bool(re.search(r"[a-z]", item_code, re.I) and re.search(r"\d", item_code))

product_links = set()

for kw in keyword_urls[:SEARCH_PAGES]:
    html = scraper.get(kw, timeout=30).text
    for href in re.findall(r'href="(/[^"]+|https://www\.newegg\.com/[^"]+)"', html):
        full = urljoin("https://www.newegg.com", href)
        if is_product(full):
            product_links.add(full.split("?")[0].split("#")[0])
            if len(product_links) >= TARGET_ITEMS:
                break
    if len(product_links) >= TARGET_ITEMS:
        break

Path("urls.txt").write_text("\n".join(list(product_links)[:TARGET_ITEMS]), encoding="utf-8")
print(f"✅  Saved {len(product_links)} **product** URLs to urls.txt")
