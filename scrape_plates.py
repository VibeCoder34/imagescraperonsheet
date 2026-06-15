import argparse
import csv
import re
import time
import urllib.request
from typing import Dict, List, Optional, Sequence


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
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


def http_get_text(url: str, timeout_s: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def extract_plate_number(listing_html: str) -> Optional[str]:
    for pattern in PLAKA_PATTERNS:
        match = pattern.search(listing_html)
        if match:
            plate = match.group(1).strip()
            if plate:
                return plate
    return None


def unique_listing_urls(rows: Sequence[dict]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for row in rows:
        url = row.get("listing_url", "").strip()
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def fetch_plates(
    listing_urls: Sequence[str],
    cache: Dict[str, Optional[str]],
    delay_s: float = 0.5,
) -> None:
    for i, url in enumerate(listing_urls, start=1):
        if url in cache:
            continue

        print(f"[{i}/{len(listing_urls)}] {url}")
        try:
            html = http_get_text(url)
            plate = extract_plate_number(html)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            plate = None
        else:
            print(f"  plate: {plate or '(not found)'}")

        cache[url] = plate
        time.sleep(delay_s)


def read_csv(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: str, rows: Sequence[dict]) -> None:
    fieldnames = [
        "listing_url",
        "listing_id",
        "plate_number",
        "image_index",
        "image_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def enrich_rows_with_plates(rows: Sequence[dict], cache: Dict[str, Optional[str]]) -> List[dict]:
    enriched: List[dict] = []
    for row in rows:
        listing_url = row.get("listing_url", "").strip()
        enriched.append(
            {
                **row,
                "plate_number": cache.get(listing_url) or "",
            }
        )
    return enriched


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add plate numbers from listing pages to an images CSV."
    )
    parser.add_argument(
        "--input",
        default="images.csv",
        help="Input CSV with listing_url rows (default: images.csv)",
    )
    parser.add_argument(
        "--output",
        default="images_with_plates.csv",
        help="Output CSV path (default: images_with_plates.csv)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between listing page requests in seconds (default: 0.5)",
    )
    args = parser.parse_args()

    rows = read_csv(args.input)
    listing_urls = unique_listing_urls(rows)
    print(f"Found {len(listing_urls)} unique listings in {args.input}")

    cache: Dict[str, Optional[str]] = {}
    fetch_plates(listing_urls, cache, delay_s=args.delay)

    output_rows = enrich_rows_with_plates(rows, cache)
    write_csv(args.output, output_rows)

    found = sum(1 for plate in cache.values() if plate)
    print(f"Done. Wrote {args.output}")
    print(f"Plates found: {found}/{len(listing_urls)}")


if __name__ == "__main__":
    main()
