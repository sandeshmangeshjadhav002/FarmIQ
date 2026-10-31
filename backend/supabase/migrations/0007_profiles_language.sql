-- FarmIQ — migration 0007: language preference on user profiles.
--
-- Run in the Supabase SQL editor (or `supabase db push`):
--   supabase/migrations/0007_profiles_language.sql
--
-- Why:
--   FarmIQ supports exactly two interface languages: English ("en") and
--   Marathi ("mr"). The chosen language is mirrored into the signed-in user's
--   profile so the preference follows the farmer to another device. Guests
--   keep their choice in localStorage and never reach this table.
--
-- Additive and idempotent: no existing row is touched. Existing profiles (and
--   any row inserted without the column) default to English, and the CHECK
--   constraint rejects anything other than the two supported codes so a
--   language such as "hi" can never be stored.

alter table public.profiles
    add column if not exists language text not null default 'en';

alter table public.profiles
    drop constraint if exists profiles_language_check;

alter table public.profiles
    add constraint profiles_language_check check (language in ('en', 'mr'));

comment on column public.profiles.language is
    'Preferred interface language: ''en'' (English) or ''mr'' (Marathi). Defaults to English.';
