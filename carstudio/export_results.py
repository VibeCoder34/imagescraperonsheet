import csv
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


def fetch_all(supabase_url: str, service_key: str, table: str) -> list:
    rows = []
    offset = 0
    page_size = 1000
    while True:
        response = requests.get(
            f"{supabase_url.rstrip('/')}/rest/v1/{table}",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            },
            params={
                "select": "*",
                "order": "created_at.asc",
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


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))

    supabase_url = os.environ["SUPABASE_URL"]
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    output_path = os.environ.get(
        "OUTPUT_CSV",
        str(Path(__file__).resolve().parent / "processed_listings.csv"),
    )

    jobs = fetch_all(supabase_url, service_key, "carstudio_jobs")
    images = fetch_all(supabase_url, service_key, "carstudio_images")

    jobs_by_id = {job["id"]: job for job in jobs}
    export_rows = []

    for image in images:
        job = jobs_by_id.get(image["job_id"], {})
        export_rows.append(
            {
                "listing_order": job.get("listing_order", ""),
                "listing_url": job.get("listing_url", ""),
                "listing_id": image.get("listing_id", ""),
                "plate_number": job.get("plate_number", ""),
                "batch_index": job.get("batch_index", 0),
                "job_status": job.get("status", ""),
                "image_index": image.get("image_index", ""),
                "original_image_url": image.get("original_url", ""),
                "processed_image_url": image.get("processed_url", ""),
                "car_studio_id": job.get("car_studio_id", ""),
            }
        )

    export_rows.sort(
        key=lambda row: (
            int(row["listing_order"] or 0),
            int(row["batch_index"] or 0),
            int(row["image_index"] or 0),
        )
    )

    fieldnames = [
        "listing_order",
        "listing_url",
        "listing_id",
        "plate_number",
        "batch_index",
        "job_status",
        "image_index",
        "original_image_url",
        "processed_image_url",
        "car_studio_id",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(export_rows)

    completed = sum(1 for row in export_rows if row["processed_image_url"])
    print(f"Wrote {output_path}")
    print(f"Rows: {len(export_rows)}")
    print(f"Processed images: {completed}/{len(export_rows)}")


if __name__ == "__main__":
    main()
