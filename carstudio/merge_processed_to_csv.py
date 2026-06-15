import csv
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from dotenv import load_dotenv


def fetch_all_images(supabase_url: str, service_key: str) -> list:
    rows = []
    offset = 0
    page_size = 1000
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }

    while True:
        response = requests.get(
            f"{supabase_url.rstrip('/')}/rest/v1/carstudio_images",
            headers=headers,
            params={
                "select": "listing_id,image_index,original_url,processed_url",
                "order": "listing_id.asc,image_index.asc",
                "offset": offset,
                "limit": page_size,
            },
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    return rows


def build_lookup(images: list) -> Tuple[Dict[Tuple[str, int], str], Dict[Tuple[str, int], str]]:
    by_listing_id: Dict[Tuple[str, int], str] = {}
    by_original_url: Dict[str, str] = {}

    for image in images:
        processed_url = (image.get("processed_url") or "").strip()
        if not processed_url:
            continue

        listing_id = str(image.get("listing_id", "")).strip()
        image_index = int(image.get("image_index") or 0)
        original_url = (image.get("original_url") or "").strip()

        if listing_id and image_index:
            by_listing_id[(listing_id, image_index)] = processed_url
        if original_url:
            by_original_url[original_url] = processed_url

    return by_listing_id, by_original_url


def find_processed_url(
    row: dict,
    by_listing_id: Dict[Tuple[str, int], str],
    by_original_url: Dict[str, str],
) -> str:
    listing_id = str(row.get("listing_id", "")).strip()
    image_index = int(row.get("image_index") or 0)
    original_url = (row.get("image_url") or row.get("original_image_url") or "").strip()

    if listing_id and image_index:
        match = by_listing_id.get((listing_id, image_index))
        if match:
            return match

    return by_original_url.get(original_url, "")


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))

    supabase_url = os.environ["SUPABASE_URL"]
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    input_csv = os.environ.get(
        "INPUT_CSV",
        str(Path(__file__).resolve().parent.parent / "listings_by_order.csv"),
    )
    output_csv = os.environ.get(
        "MERGED_OUTPUT_CSV",
        str(
            Path(__file__).resolve().parent.parent
            / "listings_by_order_with_processed.csv"
        ),
    )

    print("Fetching processed images from Supabase...")
    images = fetch_all_images(supabase_url, service_key)
    by_listing_id, by_original_url = build_lookup(images)
    print(f"Loaded {len(images)} image rows from Supabase")
    print(f"Processed URLs available: {len(by_listing_id)}")

    with open(input_csv, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        source_fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "processed_image_url" in source_fieldnames:
        output_fieldnames = source_fieldnames
    else:
        output_fieldnames = source_fieldnames + ["processed_image_url"]

    merged_rows = []
    matched = 0
    for row in rows:
        processed_url = find_processed_url(row, by_listing_id, by_original_url)
        if processed_url:
            matched += 1
        merged_rows.append({**row, "processed_image_url": processed_url})

    with open(output_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged_rows)

    print(f"Wrote {output_csv}")
    print(f"Rows: {len(merged_rows)}")
    print(f"Rows with processed_image_url: {matched}/{len(merged_rows)}")


if __name__ == "__main__":
    main()
