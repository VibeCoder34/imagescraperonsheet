import os
from pathlib import Path

import requests
from dotenv import load_dotenv


def headers(service_key: str) -> dict:
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }


def extract_urls_from_record(record: dict) -> list:
    if isinstance(record.get("afterStudioImages"), list):
        return [
            item.get("imageUrl")
            for item in record["afterStudioImages"]
            if item.get("imageUrl")
        ]
    if isinstance(record.get("afterStudioImageUrls"), list):
        return [url for url in record["afterStudioImageUrls"] if url]
    if isinstance(record.get("images"), list):
        return [url for url in record["images"] if url]
    return []


def fetch_processed_image_urls(
    base_url: str,
    api_key: str,
    car_studio_id: str,
    transaction_id: str,
    plate_number: str,
) -> list:
    headers = {"apiKey": api_key}
    base = base_url.rstrip("/")

    attempts = [
        (
            "carStudioId",
            f"{base}/home/api/v1/car-studio/search",
            {"carStudioId": car_studio_id},
        ),
        (
            "transactionId",
            f"{base}/home/api/v1/car-studio/search",
            {"transactionId": transaction_id},
        ),
    ]
    if plate_number:
        attempts.append(
            (
                "plateNumber",
                f"{base}/v1/external-api/projects",
                {
                    "page": 0,
                    "size": 5,
                    "plateNumber": plate_number,
                    "sortBy": "createdDate",
                    "sortDirection": "DESC",
                },
            )
        )

    for label, url, params in attempts:
        response = requests.get(url, headers=headers, params=params, timeout=90)
        if not response.ok or not response.text.strip():
            continue
        record = response.json()
        if label == "plateNumber":
            items = record.get("content") or record.get("data") or []
            for item in items:
                urls = extract_urls_from_record(item)
                if urls:
                    return urls
            continue
        urls = extract_urls_from_record(record)
        if urls:
            return urls

    all_projects = requests.get(
        f"{base}/v1/external-api/projects/all",
        headers=headers,
        timeout=120,
    )
    if all_projects.ok and all_projects.text.strip():
        items = all_projects.json()
        if isinstance(items, dict):
            items = items.get("data") or items.get("content") or []
        for item in items:
            item_blob = str(item)
            if car_studio_id in item_blob or transaction_id in item_blob:
                urls = extract_urls_from_record(item)
                if urls:
                    return urls

    return []


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))

    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    api_key = os.environ["CARSTUDIO_API_KEY"]
    base_url = os.environ.get("CARSTUDIO_BASE_URL", "https://tokyo.carstudio.ai")

    pending_jobs = requests.get(
        f"{supabase_url}/rest/v1/carstudio_jobs",
        headers=headers(service_key),
        params={
            "select": "id,listing_id,plate_number,transaction_id,carstudio_job_id,car_studio_id,status",
            "status": "in.(PENDING,SUBMITTED,PROCESSING,UNKNOWN)",
            "order": "created_at.asc",
        },
        timeout=30,
    ).json()

    if not pending_jobs:
        print("No pending jobs to sync.")
        return

    print(f"Found {len(pending_jobs)} pending job(s) in Supabase.")

    for job in pending_jobs:
        job_id = job["carstudio_job_id"]
        if not job_id:
            print(f"Listing {job['listing_id']}: missing carstudio_job_id, skip")
            continue

        poll = requests.get(
            f"{base_url}/ai/api/v1/webEditor/asyncJob/{job_id}",
            headers={"apiKey": api_key},
            timeout=30,
        )
        poll.raise_for_status()
        payload = poll.json()
        remote_status = payload.get("status", "UNKNOWN")
        car_studio_id = payload.get("carStudioId")

        print(
            f"Listing {job['listing_id']}: supabase={job['status']} "
            f"carstudio={remote_status}"
        )

        if remote_status != "COMPLETED":
            requests.patch(
                f"{supabase_url}/rest/v1/carstudio_jobs",
                headers=headers(service_key),
                params={"id": f"eq.{job['id']}"},
                json={"status": remote_status},
                timeout=30,
            )
            continue

        if not car_studio_id:
            print(f"  COMPLETED but no carStudioId, skip")
            continue

        processed_urls = fetch_processed_image_urls(
            base_url,
            api_key,
            car_studio_id,
            job.get("transaction_id", ""),
            job.get("plate_number", ""),
        )
        images = requests.get(
            f"{supabase_url}/rest/v1/carstudio_images",
            headers=headers(service_key),
            params={
                "select": "id,image_index",
                "job_id": f"eq.{job['id']}",
                "order": "image_index.asc",
            },
            timeout=30,
        ).json()

        for index, image in enumerate(images):
            processed_url = processed_urls[index] if index < len(processed_urls) else None
            requests.patch(
                f"{supabase_url}/rest/v1/carstudio_images",
                headers=headers(service_key),
                params={"id": f"eq.{image['id']}"},
                json={"processed_url": processed_url},
                timeout=30,
            )

        requests.patch(
            f"{supabase_url}/rest/v1/carstudio_jobs",
            headers=headers(service_key),
            params={"id": f"eq.{job['id']}"},
            json={
                "status": "COMPLETED",
                "car_studio_id": car_studio_id,
                "completed_at": payload.get("completedAt"),
            },
            timeout=30,
        )
        print(
            f"  synced {len(processed_urls)} processed url(s) "
            f"for {len(images)} image row(s)"
        )

    print("Done.")


if __name__ == "__main__":
    main()
