-- 0005_alerts.sql
--
-- Alerts & Notifications store.
--
-- Why: the "Alerts & Notifications" module previously showed hardcoded sample
-- rows. This table holds *real* alerts derived from the account's own data
-- (device contact, sensor plausibility, saved drought assessments, ML
-- predictions), so nothing in the module is fabricated.
--
-- Column notes:
--   * ``dedup_key`` is unique per owner. The rule engine is re-run on every
--     refresh; an alert that still applies is UPDATE-ed in place instead of
--     being inserted again, which is what keeps the list free of duplicates.
--   * ``reason`` records the supporting evidence behind the alert (the same
--     "reason / supporting data" contract the decision engine uses).
--   * ``is_demo`` propagates the simulator marker: an alert raised from
--     simulated readings can never be mistaken for a hardware event.
--   * ``is_read`` gives the read/unread state the UI needs.
--
-- The migration is additive and idempotent; it touches no existing data.

create table if not exists public.alerts (
    id          uuid primary key default gen_random_uuid(),
    owner_id    uuid not null references auth.users(id) on delete cascade,
    kind        text not null check (kind in ('weather','irrigation','sensor','prediction','reminder')),
    priority    text not null check (priority in ('critical','high','medium','low')),
    title       text not null,
    body        text,
    reason      text,
    subject_id  text,
    dedup_key   text not null,
    is_read     boolean not null default false,
    is_demo     boolean not null default false,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint alerts_owner_dedup_unique unique (owner_id, dedup_key)
);

-- Listing: newest first, owner-scoped.
create index if not exists alerts_owner_created_idx
    on public.alerts (owner_id, created_at desc);

-- Unread badge / "unread only" filter.
create index if not exists alerts_owner_unread_idx
    on public.alerts (owner_id, is_read, created_at desc);

comment on table public.alerts is
    'Owner-scoped alerts derived from real account data. dedup_key prevents duplicates.';
comment on column public.alerts.is_demo is
    'true = raised from simulated (DEMO) readings; false = real account data.';

-- ─────────────────────────────────────────────────────────────────────────
-- Row Level Security
-- ─────────────────────────────────────────────────────────────────────────
alter table public.alerts enable row level security;

-- A user can read only their own alerts.
drop policy if exists "alerts_owner_select" on public.alerts;
create policy "alerts_owner_select" on public.alerts
    for select using (auth.uid() = owner_id);

-- A user can update only their own alerts (read/unread toggling).
drop policy if exists "alerts_owner_update" on public.alerts;
create policy "alerts_owner_update" on public.alerts
    for update using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- A user can delete only their own alerts.
drop policy if exists "alerts_owner_delete" on public.alerts;
create policy "alerts_owner_delete" on public.alerts
    for delete using (auth.uid() = owner_id);

-- Inserts are performed by the FastAPI service role on POST /api/alerts/refresh,
-- which bypasses RLS (same convention as profiles/predictions).
