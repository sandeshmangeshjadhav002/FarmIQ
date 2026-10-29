-- FarmIQ — drought management and enhanced farming plans tables.
-- Run in the Supabase SQL editor after 0001_init.sql.

-- ─────────────────────────────────────────────────────────────────────────
-- farming_plans  (saved comparison / transition plans)
-- Created here so the farming advisor can persist results.
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.farming_plans (
    id          uuid primary key default gen_random_uuid(),
    owner_id    uuid not null references auth.users(id) on delete cascade,
    kind        text not null default 'comparison'
                    check (kind in ('comparison','transition_plan')),
    crop        text,
    preference  text,
    farm_id     uuid references public.farms(id) on delete set null,
    input       jsonb not null default '{}',
    result      jsonb not null default '{}',
    created_at  timestamptz not null default now()
);

create index if not exists farming_plans_owner_id_created_idx
    on public.farming_plans (owner_id, created_at desc);

alter table public.farming_plans enable row level security;

drop policy if exists "farming_plans_owner_all" on public.farming_plans;
create policy "farming_plans_owner_all" on public.farming_plans
    for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- ─────────────────────────────────────────────────────────────────────────
-- drought_assessments
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.drought_assessments (
    id              uuid primary key default gen_random_uuid(),
    owner_id        uuid not null references auth.users(id) on delete cascade,
    farm_id         uuid references public.farms(id) on delete set null,
    -- Key inputs kept for quick listing (no PII, just agronomic context)
    location        text,
    crop            text,
    growth_stage    text,
    soil_type       text,
    area_value      double precision,
    area_unit       text default 'acres',
    -- Full input + result blobs
    input           jsonb not null default '{}',
    result          jsonb not null default '{}',
    -- Snapshot of weather at assessment time (may be null if unavailable)
    weather_snapshot jsonb,
    created_at      timestamptz not null default now()
);

create index if not exists drought_assessments_owner_id_created_idx
    on public.drought_assessments (owner_id, created_at desc);
create index if not exists drought_assessments_owner_crop_idx
    on public.drought_assessments (owner_id, crop);

alter table public.drought_assessments enable row level security;

drop policy if exists "drought_assessments_owner_all" on public.drought_assessments;
create policy "drought_assessments_owner_all" on public.drought_assessments
    for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);
