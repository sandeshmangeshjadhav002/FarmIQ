-- FarmIQ — initial schema for Supabase PostgreSQL.
--
-- Run in the Supabase SQL editor (or `supabase db push`):
--   supabase/migrations/0001_init.sql
--
-- Design notes:
--   * ``auth.users`` is the Supabase Auth users table. Our ``profiles.id`` is a
--     1:1 foreign key to it.
--   * Every user-owned table has an ``owner_id`` and Row Level Security policies
--     scoped to ``auth.uid()``. The backend (service-role key) bypasses RLS, so
--     app/db.py ALSO filters by owner_id explicitly — defence in depth.
--   * Profiles are created by the FastAPI backend on /api/auth/register (not by
--     a trigger), so the service role inserts the row.

create extension if not exists "pgcrypto";

-- ─────────────────────────────────────────────────────────────────────────
-- profiles
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.profiles (
    id          uuid primary key references auth.users(id) on delete cascade,
    full_name   text        not null,
    email       text        not null,
    mobile      text        not null,
    role        text        not null check (role in ('farmer','farm_manager','agricultural_expert')),
    created_at  timestamptz not null default now()
);

-- ─────────────────────────────────────────────────────────────────────────
-- farms
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.farms (
    id              uuid primary key default gen_random_uuid(),
    owner_id        uuid not null references auth.users(id) on delete cascade,
    name            text not null,
    location        text not null,
    area_value      double precision,
    area_unit       text not null default 'acres',
    irrigation_type text not null default 'drip',
    soil_type       text,
    current_crop    text,
    created_at      timestamptz not null default now()
);
create index if not exists farms_owner_id_idx on public.farms (owner_id);

-- ─────────────────────────────────────────────────────────────────────────
-- devices
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.devices (
    id            uuid primary key default gen_random_uuid(),
    owner_id      uuid not null references auth.users(id) on delete cascade,
    name          text not null,
    farm_id       uuid references public.farms(id) on delete set null,
    config        text not null default 'soil_sensor',
    device_token  text not null,
    is_online     boolean not null default true,
    last_seen_at  timestamptz,
    created_at    timestamptz not null default now()
);
create index if not exists devices_owner_id_idx on public.devices (owner_id);
create index if not exists devices_device_token_idx on public.devices (device_token);

-- ─────────────────────────────────────────────────────────────────────────
-- sensor_readings
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.sensor_readings (
    id                uuid primary key default gen_random_uuid(),
    owner_id          uuid not null references auth.users(id) on delete cascade,
    farm_id           uuid references public.farms(id) on delete set null,
    device_id         text not null,
    soil_moisture     double precision,
    soil_temperature  double precision,
    temperature       double precision,
    humidity          double precision,
    soil_moisture_raw double precision,
    created_at        timestamptz not null default now()
);
create index if not exists sensor_readings_owner_id_created_idx
    on public.sensor_readings (owner_id, created_at desc);
create index if not exists sensor_readings_device_id_idx on public.sensor_readings (device_id);

-- ─────────────────────────────────────────────────────────────────────────
-- predictions (ML prediction history)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.predictions (
    id          uuid primary key default gen_random_uuid(),
    owner_id    uuid not null references auth.users(id) on delete cascade,
    domain      text not null check (domain in ('crop','fertilizer','yield','irrigation')),
    input       jsonb not null,
    output      jsonb not null,
    source      text not null default 'model',
    created_at  timestamptz not null default now()
);
create index if not exists predictions_owner_id_created_idx
    on public.predictions (owner_id, created_at desc);

-- ─────────────────────────────────────────────────────────────────────────
-- Row Level Security
-- ─────────────────────────────────────────────────────────────────────────
alter table public.profiles        enable row level security;
alter table public.farms           enable row level security;
alter table public.devices         enable row level security;
alter table public.sensor_readings enable row level security;
alter table public.predictions     enable row level security;

-- profiles: a user can read/update only their own profile.
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
    for select using (auth.uid() = id);
drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own" on public.profiles
    for update using (auth.uid() = id);
-- (insert is performed by the backend service role, which bypasses RLS.)

-- farms: full CRUD for the owner.
drop policy if exists "farms_owner_all" on public.farms;
create policy "farms_owner_all" on public.farms
    for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- devices: full CRUD for the owner.
drop policy if exists "devices_owner_all" on public.devices;
create policy "devices_owner_all" on public.devices
    for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- sensor_readings: owner can read & insert.
drop policy if exists "sensor_readings_owner_select" on public.sensor_readings;
create policy "sensor_readings_owner_select" on public.sensor_readings
    for select using (auth.uid() = owner_id);
drop policy if exists "sensor_readings_owner_insert" on public.sensor_readings;
create policy "sensor_readings_owner_insert" on public.sensor_readings
    for insert with check (auth.uid() = owner_id);

-- predictions: owner can read & insert.
drop policy if exists "predictions_owner_select" on public.predictions;
create policy "predictions_owner_select" on public.predictions
    for select using (auth.uid() = owner_id);
drop policy if exists "predictions_owner_insert" on public.predictions;
create policy "predictions_owner_insert" on public.predictions
    for insert with check (auth.uid() = owner_id);
