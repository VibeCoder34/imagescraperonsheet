-- Run this in Supabase: SQL Editor -> New query -> Run

create table if not exists carstudio_jobs (
  id uuid primary key default gen_random_uuid(),
  listing_id text not null,
  listing_url text not null,
  listing_order integer,
  plate_number text,
  batch_index integer not null default 0,
  transaction_id text not null unique,
  carstudio_job_id text,
  car_studio_id text,
  status text not null default 'PENDING',
  error_message text,
  image_count integer not null default 0,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists carstudio_images (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references carstudio_jobs(id) on delete cascade,
  listing_id text not null,
  image_index integer not null,
  original_url text not null,
  position text not null,
  processed_url text,
  created_at timestamptz not null default now(),
  unique (job_id, image_index)
);

create index if not exists carstudio_jobs_status_idx on carstudio_jobs(status);
create index if not exists carstudio_jobs_listing_id_idx on carstudio_jobs(listing_id);
create index if not exists carstudio_images_listing_id_idx on carstudio_images(listing_id);

alter table carstudio_jobs enable row level security;
alter table carstudio_images enable row level security;

-- Webhook + scripts use the service role key (bypasses RLS).
-- If you want read-only dashboard access with anon key, add policies later.
