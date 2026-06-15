import argparse
import csv
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


SITEMAP_URL = "https://www.otomol.com/sitemap/araclar.xml"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)

GORS_EL_RE = re.compile(r"/gorsel/[a-f0-9\\-]{36}", re.IGNORECASE)
LISTING_ID_RE = re.compile(r"-ikinci-el-araba-(\d+)(?:$|\?)")
LISTING_HREF_RE = re.compile(
    r'href="(/araclar/[a-z0-9\-]+-ikinci-el-araba-\d+)"',
    re.IGNORECASE,
)
PLAKA_PATTERNS = (
    re.compile(
        r'\\"label\\"\s*:\s*\\"Plaka\\"\s*,\s*\\"value\\"\s*:\s*\\"([^\\"]+)\\"',
        re.IGNORECASE,
    ),
    re.compile(
        r'"label"\s*:\s*"Plaka"\s*,\s*"value"\s*:\s*"([^"]+)"',
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class ListingData:
    image_urls: List[str]
    plate_number: Optional[str]


def http_get_text(url: str, timeout_s: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def parse_listing_page_urls() -> List[str]:
    ordered: List[str] = []
    seen: set[str] = set()
    page = 1

    while True:
        page_url = (
            "https://www.otomol.com/araclar"
            if page == 1
            else f"https://www.otomol.com/araclar?sayfa={page}"
        )

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
    urls = [u for u in urls if "/araclar/" in u and "ikinci-el-araba-" in u]
    return sorted(set(urls))


def listing_id_from_url(url: str) -> Optional[int]:
    match = LISTING_ID_RE.search(url)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def extract_plate_number(listing_html: str) -> Optional[str]:
    for pattern in PLAKA_PATTERNS:
        match = pattern.search(listing_html)
        if match:
            plate = match.group(1).strip()
            if plate:
                return plate
    return None


def extract_image_paths_from_gallery(listing_html: str) -> List[str]:
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


def fetch_listings(
    listing_urls: Sequence[str],
    cache: dict[str, ListingData],
    delay_s: float = 0.5,
) -> None:
    for i, url in enumerate(listing_urls, start=1):
        if url in cache:
            continue

        print(f"[{i}/{len(listing_urls)}] {url}")
        try:
            html = http_get_text(url)
            image_urls = extract_image_urls(html)
            plate_number = extract_plate_number(html)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            cache[url] = ListingData(image_urls=[], plate_number=None)
            continue

        cache[url] = ListingData(image_urls=image_urls, plate_number=plate_number)
        print(
            f"  images: {len(image_urls)}, "
            f"plate: {plate_number or '(not found)'}"
        )
        time.sleep(delay_s)


def write_csv(
    out_path: str,
    listing_urls: Sequence[str],
    cache: dict[str, ListingData],
    include_listing_order: bool = False,
) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if include_listing_order:
            writer.writerow(
                [
                    "listing_order",
                    "listing_url",
                    "listing_id",
                    "plate_number",
                    "image_index",
                    "image_url",
                ]
            )
        else:
            writer.writerow(
                ["listing_url", "listing_id", "plate_number", "image_index", "image_url"]
            )

        for order, url in enumerate(listing_urls, start=1):
            listing_id = listing_id_from_url(url)
            data = cache.get(url, ListingData(image_urls=[], plate_number=None))
            plate_number = data.plate_number or ""

            for image_index, image_url in enumerate(data.image_urls, start=1):
                if include_listing_order:
                    writer.writerow(
                        [order, url, listing_id, plate_number, image_index, image_url]
                    )
                else:
                    writer.writerow(
                        [url, listing_id, plate_number, image_index, image_url]
                    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape Otomol listing URLs, images, and plate numbers."
    )
    parser.add_argument(
        "--output",
        default="otomol_listings_2026-06-09.csv",
        help="Output CSV path (sitemap order)",
    )
    parser.add_argument(
        "--output-by-order",
        default="otomol_listings_by_order_2026-06-09.csv",
        help="Output CSV path (/araclar page order)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between listing page requests in seconds",
    )
    args = parser.parse_args()

    print("Fetching listing order from /araclar ...")
    listing_page_urls = parse_listing_page_urls()
    print(f"Found {len(listing_page_urls)} listings in website order.")

    print(f"Fetching sitemap: {SITEMAP_URL}")
    sitemap_xml = http_get_text(SITEMAP_URL)
    sitemap_urls = parse_sitemap_listing_urls(sitemap_xml)
    print(f"Found {len(sitemap_urls)} listing URLs in sitemap.")

    all_urls = list(dict.fromkeys([*listing_page_urls, *sitemap_urls]))
    print(f"Fetching details for {len(all_urls)} unique listings ...")

    cache: dict[str, ListingData] = {}
    fetch_listings(all_urls, cache, delay_s=args.delay)

    write_csv(args.output, sitemap_urls, cache)
    print(f"Done. Wrote {args.output}")

    write_csv(
        args.output_by_order,
        listing_page_urls,
        cache,
        include_listing_order=True,
    )
    print(f"Done. Wrote {args.output_by_order}")

    plates_found = sum(1 for data in cache.values() if data.plate_number)
    images_total = sum(len(data.image_urls) for data in cache.values())
    print(
        f"Summary: {len(all_urls)} listings, "
        f"{plates_found} plates found, {images_total} images"
    )


if __name__ == "__main__":
    main()
