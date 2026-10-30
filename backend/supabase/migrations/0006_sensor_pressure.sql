-- FarmIQ — migration 0006: barometric pressure from BME680 air-quality nodes.
--
-- Run in the Supabase SQL editor (or `supabase db push`):
--   supabase/migrations/0006_sensor_pressure.sql
--
-- Why:
--   The ESP32 + BME680 field node reports air pressure alongside the
--   temperature and humidity the schema already stores. Without a column the
--   pressure value would be silently dropped at ingestion, so a measurement
--   the hardware actually takes would never be usable downstream.
--
-- Additive and idempotent: no existing row is touched. The column is nullable
--   on purpose — soil-only probes and the DEMO simulator do not measure
--   pressure, and a missing measurement must stay missing rather than be
--   filled with a placeholder value.

alter table public.sensor_readings
    add column if not exists pressure double precision;

comment on column public.sensor_readings.pressure is
    'Barometric pressure in hPa from a BME680-type node. NULL when the node has no pressure sensor.';
