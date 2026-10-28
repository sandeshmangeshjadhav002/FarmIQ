-- FarmIQ — migration 0003: Organic vs. modern farming advisor.
--
-- Run in the Supabase SQL editor (or `supabase db push`):
--   supabase/migrations/0003_farming_methods.sql
--
-- Why these tables:
--   * ``farming_methods`` and ``organic_alternatives`` hold the curated,
--     human-reviewed reference content (farming methods, crop-specific organic
--     alternatives, application guidance, sources and update dates). Each row
--     keeps its content in a ``payload`` JSONB column so the shape stays exactly
--     what the frontend renders — the bundled file
--     ``backend/app/data/farming_methods.json`` is the seed and the offline
--     fallback (see ``backend/scripts/seed_farming_methods.py``).
--   * ``farming_plans`` stores the farmer's own saved comparison / transition
--     plans, owner-scoped like every other user table.
--
-- This migration is additive and idempotent: it does not touch existing data.

-- ─────────────────────────────────────────────────────────────────────────
-- farming_methods  (reference content — no user data)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.farming_methods (
    id           text primary key,
    sort_order   integer not null default 0,
    payload      jsonb   not null,
    last_updated timestamptz not null default now()
);

comment on table public.farming_methods is
    'Curated farming-method reference content (conventional / organic / integrated). Seeded from backend/app/data/farming_methods.json.';

-- ─────────────────────────────────────────────────────────────────────────
-- organic_alternatives  (reference content — no user data)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.organic_alternatives (
    id           text primary key,
    category     text,
    -- Crop tags the alternative applies to; "{*}" means any crop. Kept as its
    -- own column so the catalogue can be filtered without parsing the payload.
    crops        text[] not null default '{*}',
    payload      jsonb  not null,
    last_updated timestamptz not null default now()
);

comment on table public.organic_alternatives is
    'Curated organic / integrated input alternatives with application guidance and precautions.';

create index if not exists organic_alternatives_crops_idx
    on public.organic_alternatives using gin (crops);

-- ─────────────────────────────────────────────────────────────────────────
-- farming_plans  (user-owned saved plans)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.farming_plans (
    id          uuid primary key default gen_random_uuid(),
    owner_id    uuid not null references auth.users(id) on delete cascade,
    kind        text not null check (kind in ('comparison','transition_plan')),
    crop        text,
    preference  text,
    farm_id     uuid references public.farms(id) on delete set null,
    input       jsonb not null,
    result      jsonb not null,
    created_at  timestamptz not null default now()
);
create index if not exists farming_plans_owner_created_idx
    on public.farming_plans (owner_id, created_at desc);

-- ─────────────────────────────────────────────────────────────────────────
-- Row Level Security
-- ─────────────────────────────────────────────────────────────────────────
alter table public.farming_methods      enable row level security;
alter table public.organic_alternatives enable row level security;
alter table public.farming_plans        enable row level security;

-- Reference content is public read-only (it contains no user data).
drop policy if exists "farming_methods_read_all" on public.farming_methods;
create policy "farming_methods_read_all" on public.farming_methods
    for select using (true);

drop policy if exists "organic_alternatives_read_all" on public.organic_alternatives;
create policy "organic_alternatives_read_all" on public.organic_alternatives
    for select using (true);

-- Saved plans: full CRUD for the owner only.
drop policy if exists "farming_plans_owner_all" on public.farming_plans;
create policy "farming_plans_owner_all" on public.farming_plans
    for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);
