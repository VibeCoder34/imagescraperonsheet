import os
from pathlib import Path

import requests
from dotenv import load_dotenv


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))

    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    api_key = os.environ["CARSTUDIO_API_KEY"]
    base_url = os.environ.get("CARSTUDIO_BASE_URL", "https://tokyo.carstudio.ai")
    callback_url = os.environ.get("CARSTUDIO_CALLBACK_URL", "")

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }

    jobs = requests.get(
        f"{supabase_url}/rest/v1/carstudio_jobs",
        headers=headers,
        params={"select": "*", "order": "created_at.desc", "limit": 20},
        timeout=30,
    ).json()

    print("=== SUPABASE JOBS ===")
    for job in jobs:
        print(
            f"- listing {job['listing_id']} | supabase={job['status']} | "
            f"jobId={job.get('carstudio_job_id')} | carStudioId={job.get('car_studio_id')}"
        )

    print("\n=== CAR STUDIO POLL ===")
    for job in jobs:
        job_id = job.get("carstudio_job_id")
        if not job_id:
            continue
        response = requests.get(
            f"{base_url}/ai/api/v1/webEditor/asyncJob/{job_id}",
            headers={"apiKey": api_key},
            timeout=30,
        )
        payload = response.json()
        print(
            f"- listing {job['listing_id']} | carstudio={payload.get('status')} | "
            f"carStudioId={payload.get('carStudioId')}"
        )

    if callback_url:
        print("\n=== WEBHOOK REACHABILITY ===")
        response = requests.post(
            callback_url,
            json={"status": "COMPLETED", "jobId": "health-check"},
            timeout=30,
        )
        print(f"- POST {callback_url}")
        print(f"- HTTP {response.status_code}")
        if response.status_code == 401:
            print(
                "  Webhook is blocked (401). Car Studio cannot call it. "
                "Disable Vercel Deployment Protection for this project."
            )
        elif response.status_code == 500 and "SUPABASE" in response.text:
            print(
                "  Webhook is reachable but missing Vercel env vars. "
                "Add SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, CARSTUDIO_API_KEY."
            )

    images = requests.get(
        f"{supabase_url}/rest/v1/carstudio_images",
        headers=headers,
        params={
            "select": "processed_url",
            "processed_url": "not.is.null",
            "limit": 1,
        },
        timeout=30,
    ).json()
    print("\n=== RESULT ===")
    if images:
        print("At least one processed_url exists. Pipeline is working.")
    else:
        print("No processed_url yet.")
        print("If Car Studio shows COMPLETED but Supabase is PENDING:")
        print("1) webhook is probably blocked")
        print("2) run: python3 sync_completed_jobs.py")


if __name__ == "__main__":
    main()
