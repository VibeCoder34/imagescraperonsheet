import csv
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple


SITEMAP_URL = "https://www.otomol.com/sitemap/araclar.xml"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

# Extract /gorsel/<uuid> from HTML.
GORS_EL_RE = re.compile(r"/gorsel/[a-f0-9\\-]{36}", re.IGNORECASE)

# Extract listing id from "...-ikinci-el-araba-8767"
LISTING_ID_RE = re.compile(r"-ikinci-el-araba-(\d+)(?:$|\?)")

# Extract listing links from /araclar pages in document order.
LISTING_HREF_RE = re.compile(
    r'href="(/araclar/[a-z0-9\-]+-ikinci-el-araba-\d+)"',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Listing:
    url: str
    listing_id: Optional[int]


def http_get_text(url: str, timeout_s: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        # gzip handling: urllib auto-decodes in most cases; we keep it simple.
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def parse_listing_page_urls() -> List[str]:
    """Return listing URLs in the order shown on https://www.otomol.com/araclar."""
    ordered: List[str] = []
    seen: set[str] = set()
    page = 1

    while True:
        if page == 1:
            page_url = "https://www.otomol.com/araclar"
        else:
            page_url = f"https://www.otomol.com/araclar?sayfa={page}"

        print(f"Fetching listing page: {page_url}")
        html = http_get_text(page_url)
        page_urls: List[str] = []
        for match in LISTING_HREF_RE.finditer(html):
            full_url = f"https://www.otomol.com{match.group(1)}"
            if full_url not in seen:
                seen.add(full_url)
                page_urls.append(full_url)

        if not page_urls:
            break

        print(f"  found {len(page_urls)} listings")
        ordered.extend(page_urls)
        page += 1
        time.sleep(0.3)

    return ordered


def parse_sitemap_listing_urls(sitemap_xml: str) -> List[str]:
    root = ET.fromstring(sitemap_xml)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls: List[str] = []
    for loc in root.findall(".//sm:url/sm:loc", ns):
        if loc.text:
            urls.append(loc.text.strip())
    # Keep only araclar listings
    urls = [u for u in urls if "/araclar/" in u and "ikinci-el-araba-" in u]
    return sorted(set(urls))


def listing_id_from_url(url: str) -> Optional[int]:
    m = LISTING_ID_RE.search(url)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def extract_image_paths_from_gallery(listing_html: str) -> List[str]:
    """Return image paths in the same order as the website gallery."""
    for pattern in (
        r'\\"images\\"\s*:\s*\[(.*?)\]',
        r'"images"\s*:\s*\[(.*?)\]',
    ):
        match = re.search(pattern, listing_html, re.DOTALL)
        if not match:
            continue
        paths = GORS_EL_RE.findall(match.group(1))
        if paths:
            return paths

    # Fallback: first appearance in HTML, preserving document order.
    seen: set[str] = set()
    ordered: List[str] = []
    for path in GORS_EL_RE.findall(listing_html):
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def extract_image_urls(listing_html: str) -> List[str]:
    return [
        f"https://www.otomol.com{path}"
        for path in extract_image_paths_from_gallery(listing_html)
    ]


def iter_listings(listing_urls: Sequence[str]) -> Iterable[Listing]:
    for u in listing_urls:
        yield Listing(url=u, listing_id=listing_id_from_url(u))


def fetch_listing_images(
    listing_urls: Sequence[str],
    cache: dict[str, List[str]],
) -> None:
    for i, listing in enumerate(iter_listings(listing_urls), start=1):
        if listing.url in cache:
            continue

        print(f"[{i}/{len(listing_urls)}] {listing.url}")
        try:
            html = http_get_text(listing.url)
        except Exception as e:
            print(f"  ERROR fetching listing page: {e}")
            cache[listing.url] = []
            continue

        image_urls = extract_image_urls(html)
        cache[listing.url] = image_urls
        print(f"  images: {len(image_urls)}")
        time.sleep(0.5)


def write_csv(
    out_path: str,
    listing_urls: Sequence[str],
    cache: dict[str, List[str]],
    include_listing_order: bool = False,
) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if include_listing_order:
            writer.writerow(
                ["listing_order", "listing_url", "listing_id", "image_index", "image_url"]
            )
        else:
            writer.writerow(["listing_url", "listing_id", "image_index", "image_url"])

        for order, url in enumerate(listing_urls, start=1):
            listing_id = listing_id_from_url(url)
            image_urls = cache.get(url, [])
            for image_index, image_url in enumerate(image_urls, start=1):
                if include_listing_order:
                    writer.writerow([order, url, listing_id, image_index, image_url])
                else:
                    writer.writerow([url, listing_id, image_index, image_url])


def main() -> None:
    print("Fetching listing order from /araclar ...")
    listing_page_urls = parse_listing_page_urls()
    print(f"Found {len(listing_page_urls)} listings in website order.")

    print(f"Fetching sitemap: {SITEMAP_URL}")
    sitemap_xml = http_get_text(SITEMAP_URL)
    sitemap_urls = parse_sitemap_listing_urls(sitemap_xml)
    print(f"Found {len(sitemap_urls)} listing URLs in sitemap.")

    all_urls = list(dict.fromkeys([*listing_page_urls, *sitemap_urls]))
    cache: dict[str, List[str]] = {}
    fetch_listing_images(all_urls, cache)

    write_csv("otomol_images.csv", sitemap_urls, cache)
    print("Done. Wrote otomol_images.csv")

    write_csv(
        "otomol_images_by_listing_order.csv",
        listing_page_urls,
        cache,
        include_listing_order=True,
    )
    print("Done. Wrote otomol_images_by_listing_order.csv")


if __name__ == "__main__":
    main()

