/**
 * Shared location store — the single source of truth for the farmer's selected
 * location across the entire FarmIQ application.
 *
 * Uses React Context + localStorage persistence (the same pattern the auth
 * token uses in apiClient.js). No external state management library is needed.
 *
 * The store holds:
 *  - `label`: human-readable place name (e.g. "Nashik, Maharashtra")
 *  - `latitude` / `longitude`: numeric coordinates (null when not set)
 *  - `source`: "gps" | "manual" | "farm" — where the location came from
 *  - `setAt`: ISO timestamp of when it was last set
 *
 * Components consume it via the `useLocation()` hook:
 *   const { location, setLocation, clearLocation } = useLocation();
 *
 * The store syncs from the farmer's first saved farm record when one exists,
 * so a farmer who already created a farm doesn't need to set location again.
 */
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import i18n from "@/i18n";

import { getCurrentPosition } from "@/lib/geolocation";
import { apiGet } from "@/lib/apiClient";

const STORAGE_KEY = "farmiq_shared_location";

/**
 * @typedef {Object} SharedLocation
 * @property {string|null} label        - Human-readable place name.
 * @property {number|null} latitude     - Numeric latitude.
 * @property {number|null} longitude    - Numeric longitude.
 * @property {"gps"|"manual"|"farm"|null} source - Origin of the location.
 * @property {string|null} setAt        - ISO timestamp when set.
 */

/** @type {SharedLocation} */
const EMPTY_LOCATION = {
  label: null,
  latitude: null,
  longitude: null,
  source: null,
  setAt: null,
};

const LocationContext = createContext(null);

/** Read the persisted location from localStorage (survives reloads / app restarts). */
function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      return { ...EMPTY_LOCATION, ...parsed };
    }
  } catch {
    // corrupt JSON — ignore
  }
  return null;
}

/** Persist the location to localStorage. */
function saveToStorage(location) {
  try {
    if (location && location.label) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(location));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // storage full / unavailable — non-fatal
  }
}

/**
 * LocationProvider — wraps the app and provides the shared location to all
 * children via context. Mount once near the root (in App.jsx).
 *
 * On mount, it:
 *  1. Restores the persisted location from localStorage.
 *  2. If no shared location exists, tries to sync from the farmer's first
 *     saved farm record (which may have lat/lon from FarmManager).
 */
export function LocationProvider({ children }) {
  const [location, setLocationState] = useState(() => loadFromStorage());
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState(null);

  // Sync from the farmer's first saved farm when no shared location is set.
  // This runs once on mount and when the auth state changes.
  const [farmSynced, setFarmSynced] = useState(false);

  useEffect(() => {
    if (location || farmSynced) return;

    let cancelled = false;

    (async () => {
      try {
        const data = await apiGet("/api/farms");
        const farm = data?.items?.[0];
        if (cancelled) return;
        if (farm?.latitude != null && farm?.longitude != null) {
          const synced = {
            label: farm.location || farm.name || i18n.t("locationStore.savedFarm"),
            latitude: farm.latitude,
            longitude: farm.longitude,
            source: "farm",
            setAt: new Date().toISOString(),
          };
          setLocationState(synced);
          saveToStorage(synced);
        }
      } catch {
        // Not signed in, no farms, or API unavailable — non-fatal.
        // The farmer can set location manually via the LocationSelector.
      } finally {
        if (!cancelled) setFarmSynced(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [location, farmSynced]);

  /** Set the shared location. Persists immediately. */
  const setLocation = useCallback((next) => {
    const updated = {
      ...EMPTY_LOCATION,
      ...next,
      setAt: new Date().toISOString(),
    };
    setLocationState(updated);
    saveToStorage(updated);
  }, []);

  /** Clear the shared location. */
  const clearLocation = useCallback(() => {
    setLocationState(null);
    saveToStorage(null);
  }, []);

  /** Detect location via GPS. Returns a promise so callers can chain. */
  const detectLocation = useCallback(async () => {
    if (locating) return;
    setLocating(true);
    setLocationError(null);
    try {
      const pos = await getCurrentPosition();
      // Try to resolve the coordinates to a readable label.
      let label = `${pos.latitude.toFixed(4)}, ${pos.longitude.toFixed(4)}`;
      try {
        const rep = await apiGet(
          `/api/weather/reverse?lat=${pos.latitude}&lon=${pos.longitude}`,
        );
        if (rep?.name) label = rep.name;
      } catch {
        // reverse geocoding failed — use raw coords as the label
      }
      setLocation({
        label,
        latitude: pos.latitude,
        longitude: pos.longitude,
        source: "gps",
      });
    } catch (err) {
      setLocationError(err.message || i18n.t("locationStore.detectError"));
      throw err;
    } finally {
      setLocating(false);
    }
  }, [locating, setLocation]);

  /** Set location from a manual place-name search. */
  const setManualLocation = useCallback(
    async (placeName) => {
      const name = placeName.trim();
      if (name.length < 2) return;
      setLocating(true);
      setLocationError(null);
      try {
        // Use the existing weather geocoding to resolve the name to coordinates.
        const rep = await apiGet(`/api/weather/current?location=${encodeURIComponent(name)}`);
        const loc = rep?.location;
        if (loc?.latitude != null && loc?.longitude != null) {
          setLocation({
            label: loc.name || name,
            latitude: loc.latitude,
            longitude: loc.longitude,
            source: "manual",
          });
        } else {
          // No coordinates resolved — store the name only.
          setLocation({ label: name, latitude: null, longitude: null, source: "manual" });
        }
      } catch (err) {
        // Weather service unavailable — store the name only, no coordinates.
        setLocation({ label: name, latitude: null, longitude: null, source: "manual" });
      } finally {
        setLocating(false);
      }
    },
    [setLocation],
  );

  const value = {
    location,
    locating,
    locationError,
    setLocation,
    setManualLocation,
    detectLocation,
    clearLocation,
    /** True when a location has been set (even without coordinates). */
    hasLocation: !!(location?.label),
    /** True when coordinates are available (needed for weather/geocoding). */
    hasCoordinates: location?.latitude != null && location?.longitude != null,
  };

  return (
    <LocationContext.Provider value={value}>
      {children}
    </LocationContext.Provider>
  );
}

/**
 * useLocation — the hook every component uses to read or set the shared location.
 *
 * Must be used inside a <LocationProvider>.
 *
 * @returns {Object} The location context value.
 */
export function useLocation() {
  const ctx = useContext(LocationContext);
  if (!ctx) {
    throw new Error("useLocation must be used inside a <LocationProvider>.");
  }
  return ctx;
}
