/**
 * Promise wrapper around the device/browser geolocation API.
 *
 * `navigator.geolocation` reports failures as a numeric code (1/2/3) that means
 * nothing to a user, so each one is mapped to a sentence they can act on. The
 * wrapped promise never rejects with a raw GeolocationPositionError.
 *
 * Two things this deliberately does NOT do:
 *  - It never runs on page load. The OS/browser permission dialog only appears
 *    while this is executing, so callers must invoke it from a user action
 *    (a button tap) — otherwise the prompt arrives with no visible context and
 *    users deny it. Android stops re-prompting after two denials.
 *  - It never guesses a position. There is no default or fallback coordinate;
 *    a failure is surfaced so the caller can offer manual entry.
 */

/** Thrown when a position cannot be obtained. `code` is stable for branching. */
export class GeolocationError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "GeolocationError";
    this.code = code;
  }
}

const MESSAGES = {
  unsupported: "This device does not provide location. Type the location instead.",
  insecure:
    "Location needs a secure (https) connection. Type the location instead.",
  denied: "Location permission was denied. You can type the location instead.",
  unavailable: "Your position could not be determined right now. Type the location instead.",
  timeout: "Getting your location took too long. Try again, or type the location.",
};

const ERROR_CODES = {
  1: "denied", // PERMISSION_DENIED
  2: "unavailable", // POSITION_UNAVAILABLE
  3: "timeout", // TIMEOUT
};

/**
 * Resolve the current position.
 *
 * @param {object} [options]
 * @param {number} [options.timeout]     - Milliseconds before giving up.
 * @param {number} [options.maximumAge]  - Accept a cached fix up to this old.
 * @param {boolean}[options.highAccuracy]- Request a precise (slower, costlier)
 *                                         fix. Defaults to false: a farm's
 *                                         weather does not need GPS precision.
 * @returns {Promise<{latitude: number, longitude: number, accuracy_m: number|null}>}
 * @throws {GeolocationError}
 */
export function getCurrentPosition({
  timeout = 10000,
  maximumAge = 600000,
  highAccuracy = false,
} = {}) {
  return new Promise((resolve, reject) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      reject(new GeolocationError("unsupported", MESSAGES.unsupported));
      return;
    }
    // Browsers only expose geolocation in a secure context; on a plain http://
    // LAN address the API object exists but every call fails. Surfacing this
    // distinctly avoids blaming the user's permission choice.
    if (typeof window !== "undefined" && window.isSecureContext === false) {
      reject(new GeolocationError("insecure", MESSAGES.insecure));
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) =>
        resolve({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy_m:
            typeof pos.coords.accuracy === "number" ? pos.coords.accuracy : null,
        }),
      (err) => {
        const code = ERROR_CODES[err?.code] ?? "unavailable";
        reject(new GeolocationError(code, MESSAGES[code]));
      },
      { enableHighAccuracy: highAccuracy, timeout, maximumAge }
    );
  });
}
