-- 0004_farm_coordinates.sql
--
-- Adds optional geographic coordinates to farms.
--
-- Why: the farm form can now fill itself in from the device's location instead
-- of making the farmer type a place name. `farms.location` stays the
-- human-readable, NOT NULL label (so every existing row and API contract
-- remains valid); these two nullable columns hold the precise point used by
-- the weather module to skip geocoding entirely.
--
-- Both columns are nullable and independent of `location`, so this migration is
-- safe to apply to a live table: existing rows keep NULL coordinates and
-- continue to work through the place-name path.

alter table public.farms
    add column if not exists latitude double precision;

alter table public.farms
    add column if not exists longitude double precision;

-- Guard against transposed or malformed coordinates arriving from a device.
-- NULL is allowed (coordinate unknown), out-of-range values are not.
alter table public.farms
    drop constraint if exists farms_latitude_range;

alter table public.farms
    add constraint farms_latitude_range
    check (latitude is null or (latitude >= -90 and latitude <= 90));

alter table public.farms
    drop constraint if exists farms_longitude_range;

alter table public.farms
    add constraint farms_longitude_range
    check (longitude is null or (longitude >= -180 and longitude <= 180));

-- A point is only usable for weather lookup when both halves are present.
alter table public.farms
    drop constraint if exists farms_coordinates_pair;

alter table public.farms
    add constraint farms_coordinates_pair
    check (
        (latitude is null and longitude is null)
        or (latitude is not null and longitude is not null)
    );

comment on column public.farms.latitude is
    'WGS84 latitude of the farm. NULL when only a place name is known.';
comment on column public.farms.longitude is
    'WGS84 longitude of the farm. NULL when only a place name is known.';
