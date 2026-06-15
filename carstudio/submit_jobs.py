import csv
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv


MAX_IMAGES_PER_JOB = 25
# Car Studio only documents PHOTO_ONE..PHOTO_FOUR; other slots use OTHER.
PHOTO_POSITIONS = ("PHOTO_ONE", "PHOTO_TWO", "PHOTO_THREE", "PHOTO_FOUR")


def position_for_index(index: int) -> str:
    if 1 <= index <= len(PHOTO_POSITIONS):
        return PHOTO_POSITIONS[index - 1]
    return "OTHER"


def load_listings(csv_path: str) -> List[dict]:
    grouped: Dict[str, dict] = {}
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            listing_url = row["listing_url"].strip()
            if listing_url not in grouped:
                grouped[listing_url] = {
                    "listing_url": listing_url,
                    "listing_id": row.get("listing_id", "").strip(),
                    "listing_order": int(row.get("listing_order") or 0),
                    "plate_number": row.get("plate_number", "").strip(),
                    "images": [],
                }
            grouped[listing_url]["images"].append(
                {
                    "image_index": int(row["image_index"]),
                    "image_url": row["image_url"].strip(),
                }
            )

    listings = list(grouped.values())
    listings.sort(key=lambda item: item["listing_order"])
    for listing in listings:
        listing["images"].sort(key=lambda item: item["image_index"])
    return listings


def chunk_images(images: List[dict], size: int) -> List[List[dict]]:
    return [images[i : i + size] for i in range(0, len(images), size)]


def supabase_headers(service_key: str, prefer: Optional[str] = None) -> dict:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def supabase_get_job_by_transaction_id(
    supabase_url: str,
    service_key: str,
    transaction_id: str,
) -> Optional[dict]:
    response = requests.get(
        f"{supabase_url.rstrip('/')}/rest/v1/carstudio_jobs",
        headers=supabase_headers(service_key),
        params={
            "select": "id,status,carstudio_job_id",
            "transaction_id": f"eq.{transaction_id}",
            "limit": 1,
        },
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def supabase_reset_failed_job(
    supabase_url: str,
    service_key: str,
    job_id: str,
    payload: dict,
) -> None:
    requests.delete(
        f"{supabase_url.rstrip('/')}/rest/v1/carstudio_images",
        headers=supabase_headers(service_key),
        params={"job_id": f"eq.{job_id}"},
        timeout=30,
    ).raise_for_status()
    requests.patch(
        f"{supabase_url.rstrip('/')}/rest/v1/carstudio_jobs",
        headers=supabase_headers(service_key),
        params={"id": f"eq.{job_id}"},
        json={
            **payload,
            "status": "PENDING",
            "error_message": None,
            "carstudio_job_id": None,
            "car_studio_id": None,
            "completed_at": None,
        },
        timeout=30,
    ).raise_for_status()


def supabase_insert_job(
    supabase_url: str,
    service_key: str,
    payload: dict,
) -> str:
    response = requests.post(
        f"{supabase_url.rstrip('/')}/rest/v1/carstudio_jobs",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0]["id"]


def supabase_insert_images(
    supabase_url: str,
    service_key: str,
    rows: List[dict],
) -> None:
    response = requests.post(
        f"{supabase_url.rstrip('/')}/rest/v1/carstudio_images",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
        json=rows,
        timeout=30,
    )
    response.raise_for_status()


def submit_async_job(
    base_url: str,
    api_key: str,
    callback_url: str,
    listing: dict,
    batch_index: int,
    batch_images: List[dict],
    background_url: Optional[str],
    job_prefix: str,
) -> dict:
    transaction_id = f"{job_prefix}-{listing['listing_id']}-batch-{batch_index}"
    body = {
        "images": [
            {
                "fileUrl": image["image_url"],
                "position": position_for_index(image["image_index"]),
            }
            for image in batch_images
        ],
        "callbackUrl": callback_url,
        "transactionId": transaction_id,
        "plateNumber": listing["plate_number"] or None,
        "fileExtension": "PNG",
        "metadata": [
            {"key": "listing_id", "value": listing["listing_id"]},
            {"key": "listing_url", "value": listing["listing_url"]},
            {"key": "batch_index", "value": str(batch_index)},
            {"key": "transaction_id", "value": transaction_id},
        ],
    }
    if background_url:
        body["backgroundUrl"] = background_url

    response = requests.post(
        f"{base_url.rstrip('/')}/ai/api/v1/webEditor/uploadImagesWithUrlV2Async",
        headers={
            "apiKey": api_key,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(
            f"{response.status_code} {response.reason}: {response.text[:500]}"
        )
    return response.json()


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))

    api_key = os.environ["CARSTUDIO_API_KEY"]
    base_url = os.environ.get("CARSTUDIO_BASE_URL", "https://tokyo.carstudio.ai")
    callback_url = os.environ["CARSTUDIO_CALLBACK_URL"]
    supabase_url = os.environ["SUPABASE_URL"]
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    background_url = os.environ.get("CARSTUDIO_BACKGROUND_URL") or None

    csv_path = os.environ.get(
        "INPUT_CSV",
        str(Path(__file__).resolve().parent.parent / "listings_by_order.csv"),
    )
    limit = int(os.environ.get("LIMIT_LISTINGS", "0") or 0)
    delay_s = float(os.environ.get("SUBMIT_DELAY_SECONDS", "1"))
    job_prefix = os.environ.get("JOB_ID_PREFIX", "listing")

    listings = load_listings(csv_path)
    if limit > 0:
        listings = listings[:limit]

    print(f"Loaded {len(listings)} listings from {csv_path}")

    submitted_jobs = 0
    for listing in listings:
        batches = chunk_images(listing["images"], MAX_IMAGES_PER_JOB)
        print(
            f"Listing {listing['listing_id']} ({listing['plate_number']}): "
            f"{len(listing['images'])} images -> {len(batches)} job(s)"
        )

        for batch_index, batch_images in enumerate(batches):
            transaction_id = f"{job_prefix}-{listing['listing_id']}-batch-{batch_index}"
            job_payload = {
                "listing_id": listing["listing_id"],
                "listing_url": listing["listing_url"],
                "listing_order": listing["listing_order"],
                "plate_number": listing["plate_number"],
                "batch_index": batch_index,
                "transaction_id": transaction_id,
                "status": "PENDING",
                "image_count": len(batch_images),
            }
            image_rows = [
                {
                    "listing_id": listing["listing_id"],
                    "image_index": image["image_index"],
                    "original_url": image["image_url"],
                    "position": position_for_index(image["image_index"]),
                }
                for image in batch_images
            ]

            existing_job = supabase_get_job_by_transaction_id(
                supabase_url, service_key, transaction_id
            )
            if existing_job and existing_job["status"] in {
                "PENDING",
                "SUBMITTED",
                "PROCESSING",
                "COMPLETED",
            }:
                print(f"  batch {batch_index}: skip ({existing_job['status']})")
                continue

            if existing_job and existing_job["status"] == "FAILED":
                job_id = existing_job["id"]
                supabase_reset_failed_job(
                    supabase_url, service_key, job_id, job_payload
                )
            else:
                job_id = supabase_insert_job(
                    supabase_url, service_key, job_payload
                )

            supabase_insert_images(
                supabase_url,
                service_key,
                [{**row, "job_id": job_id} for row in image_rows],
            )

            try:
                result = submit_async_job(
                    base_url=base_url,
                    api_key=api_key,
                    callback_url=callback_url,
                    listing=listing,
                    batch_index=batch_index,
                    batch_images=batch_images,
                    background_url=background_url,
                    job_prefix=job_prefix,
                )
            except Exception as exc:
                requests.patch(
                    f"{supabase_url.rstrip('/')}/rest/v1/carstudio_jobs?id=eq.{job_id}",
                    headers={
                        "apikey": service_key,
                        "Authorization": f"Bearer {service_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "status": "FAILED",
                        "error_message": str(exc),
                    },
                    timeout=30,
                )
                print(f"  batch {batch_index}: FAILED -> {exc}")
                continue

            requests.patch(
                f"{supabase_url.rstrip('/')}/rest/v1/carstudio_jobs?id=eq.{job_id}",
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "status": result.get("status", "SUBMITTED"),
                    "carstudio_job_id": result.get("jobId"),
                },
                timeout=30,
            )
            submitted_jobs += 1
            print(
                f"  batch {batch_index}: {result.get('status')} "
                f"jobId={result.get('jobId')}"
            )
            time.sleep(delay_s)

    print(f"Done. Submitted {submitted_jobs} jobs.")


if __name__ == "__main__":
    main()
