import { createClient } from "@supabase/supabase-js";

const CARSTUDIO_BASE_URL =
  process.env.CARSTUDIO_BASE_URL || "https://tokyo.carstudio.ai";

function getSupabase() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    throw new Error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY");
  }
  return createClient(url, key);
}

function metadataValue(payload, key) {
  const items = payload?.metadata;
  if (!Array.isArray(items)) {
    return null;
  }
  const match = items.find((item) => item?.key === key);
  return match?.value || null;
}

function normalizePayload(payload) {
  const result = payload?.result || {};
  const afterStudioImages =
    result.afterStudioImages || payload.afterStudioImages || [];

  let status = payload?.status;
  if (
    !status &&
    payload?.success === true &&
    (payload?.code === "200" || payload?.code === 200)
  ) {
    status = "COMPLETED";
  }
  if (!status && afterStudioImages.length > 0) {
    status = "COMPLETED";
  }

  return {
    status: status || "UNKNOWN",
    jobId: payload?.jobId || null,
    transactionId: payload?.transactionId || metadataValue(payload, "transaction_id"),
    listingId: metadataValue(payload, "listing_id"),
    carStudioId: result.carStudioId || payload?.carStudioId || null,
    completedAt: payload?.completedAt || null,
    processedUrls: afterStudioImages
      .map((item) => item?.afterStudioImageUrl || item?.imageUrl)
      .filter(Boolean),
    afterStudioImages,
  };
}

function extractUrls(record) {
  if (Array.isArray(record?.afterStudioImages)) {
    return record.afterStudioImages
      .map((item) => item?.afterStudioImageUrl || item?.imageUrl)
      .filter(Boolean);
  }
  if (Array.isArray(record?.afterStudioImageUrls)) {
    return record.afterStudioImageUrls.filter(Boolean);
  }
  if (Array.isArray(record?.images)) {
    return record.images.filter(Boolean);
  }
  return [];
}

async function parseJsonResponse(response) {
  const text = await response.text();
  if (!text.trim()) {
    return null;
  }
  return JSON.parse(text);
}

async function fetchProcessedImageUrls(carStudioId, apiKey, job, normalized) {
  if (normalized.processedUrls.length > 0) {
    return normalized.processedUrls;
  }

  const attempts = [
    {
      url: `${CARSTUDIO_BASE_URL}/home/api/v1/car-studio/search?carStudioId=${encodeURIComponent(carStudioId)}`,
    },
  ];

  if (job?.transaction_id) {
    attempts.push({
      url: `${CARSTUDIO_BASE_URL}/home/api/v1/car-studio/search?transactionId=${encodeURIComponent(job.transaction_id)}`,
    });
  }

  if (job?.plate_number) {
    attempts.push({
      url: `${CARSTUDIO_BASE_URL}/v1/external-api/projects?page=0&size=5&plateNumber=${encodeURIComponent(job.plate_number)}&sortBy=createdDate&sortDirection=DESC`,
      list: true,
    });
  }

  for (const attempt of attempts) {
    const response = await fetch(attempt.url, { headers: { apiKey } });
    if (!response.ok) {
      continue;
    }

    const record = await parseJsonResponse(response);
    if (!record) {
      continue;
    }

    if (attempt.list) {
      const items = record.content || record.data || [];
      for (const item of items) {
        const urls = extractUrls(item);
        if (urls.length > 0) {
          return urls;
        }
      }
      continue;
    }

    const urls = extractUrls(record);
    if (urls.length > 0) {
      return urls;
    }
  }

  return [];
}

function findJob(jobs, normalized) {
  const openStatuses = new Set([
    "PENDING",
    "SUBMITTED",
    "PROCESSING",
    "UNKNOWN",
  ]);

  return (
    jobs.find((job) => job.carstudio_job_id === normalized.jobId) ||
    jobs.find((job) => job.transaction_id === normalized.transactionId) ||
    jobs.find(
      (job) =>
        normalized.listingId &&
        job.listing_id === normalized.listingId &&
        openStatuses.has(job.status)
    )
  );
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const payload = req.body ?? {};
    const normalized = normalizePayload(payload);

    const supabase = getSupabase();
    const { data: jobs, error: jobsError } = await supabase
      .from("carstudio_jobs")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(200);

    if (jobsError) {
      throw jobsError;
    }

    const job = findJob(jobs || [], normalized);
    if (!job) {
      return res.status(404).json({
        error: "Matching job not found",
        jobId: normalized.jobId,
        status: normalized.status,
      });
    }

    if (normalized.status === "FAILED") {
      await supabase
        .from("carstudio_jobs")
        .update({
          status: "FAILED",
          error_message: payload.message || payload.errorMessage || "Car Studio job failed",
          completed_at: new Date().toISOString(),
        })
        .eq("id", job.id);

      return res.status(200).json({ ok: true, handled: "failed" });
    }

    if (normalized.status !== "COMPLETED") {
      await supabase
        .from("carstudio_jobs")
        .update({
          status: normalized.status,
          carstudio_job_id: normalized.jobId || job.carstudio_job_id,
          car_studio_id: normalized.carStudioId || job.car_studio_id,
        })
        .eq("id", job.id);

      return res.status(200).json({ ok: true, handled: "status_update" });
    }

    const carStudioId = normalized.carStudioId;
    if (!carStudioId && normalized.processedUrls.length === 0) {
      throw new Error("Completed callback missing carStudioId and image URLs");
    }

    const apiKey = process.env.CARSTUDIO_API_KEY;
    if (!apiKey) {
      throw new Error("Missing CARSTUDIO_API_KEY");
    }

    const processedUrls = carStudioId
      ? await fetchProcessedImageUrls(carStudioId, apiKey, job, normalized)
      : normalized.processedUrls;

    const { data: images, error: imagesError } = await supabase
      .from("carstudio_images")
      .select("*")
      .eq("job_id", job.id)
      .order("image_index", { ascending: true });

    if (imagesError) {
      throw imagesError;
    }

    for (let index = 0; index < (images || []).length; index += 1) {
      const image = images[index];
      const processedUrl = processedUrls[index] || null;
      await supabase
        .from("carstudio_images")
        .update({ processed_url: processedUrl })
        .eq("id", image.id);
    }

    await supabase
      .from("carstudio_jobs")
      .update({
        status: "COMPLETED",
        carstudio_job_id: normalized.jobId || job.carstudio_job_id,
        car_studio_id: carStudioId || job.car_studio_id,
        completed_at: normalized.completedAt || new Date().toISOString(),
      })
      .eq("id", job.id);

    return res.status(200).json({
      ok: true,
      handled: "completed",
      processedCount: processedUrls.length,
      imageRows: (images || []).length,
      source: normalized.processedUrls.length > 0 ? "callback" : "api_fallback",
    });
  } catch (error) {
    console.error("Webhook error:", error);
    return res.status(500).json({
      error: error.message || "Webhook failed",
    });
  }
}
