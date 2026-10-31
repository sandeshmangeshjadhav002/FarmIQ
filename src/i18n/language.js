/**
 * FarmIQ supports exactly two languages: English and Marathi (मराठी).
 *
 * The language is stored as a BCP-47 base code ("en" | "mr"). Everything that
 * reads or writes the preference goes through this module so there is a single
 * source of truth for:
 *
 *   * which languages exist (``SUPPORTED_LANGUAGES``),
 *   * where the guest preference lives (localStorage),
 *   * how a first-time user's language is chosen (device language → English).
 *
 * The signed-in preference lives in the Supabase-backed profile
 * (``profiles.language``, see backend/supabase/migrations/0007_*). Reading the
 * profile is done by the caller; this module only normalises values.
 */

/** The two supported languages, in the order the selector shows them. */
export const SUPPORTED_LANGUAGES = [
  { code: "en", englishLabel: "English", nativeLabel: "English" },
  { code: "mr", englishLabel: "Marathi", nativeLabel: "मराठी" },
];

/** Just the codes, for validation and i18next's ``supportedLngs``. */
export const LANGUAGE_CODES = SUPPORTED_LANGUAGES.map((item) => item.code);

/** Used whenever nothing else indicates a preference. */
export const DEFAULT_LANGUAGE = "en";

/** localStorage key holding a guest's (or a signed-in user's) preference. */
export const LANGUAGE_STORAGE_KEY = "farmiq_language";

/** True when *code* is one of the two languages FarmIQ supports. */
export function isSupportedLanguage(code) {
  return LANGUAGE_CODES.includes(code);
}

/**
 * Reduce a locale tag to a supported language code.
 *
 * Accepts the shapes we actually see: "mr", "mr-IN", "mr_IN", "EN". Anything
 * unsupported (including "hi") returns ``null`` so it is never silently
 * reinterpreted — we must not fall back to Hindi for an Indian device.
 */
export function normalizeLanguage(code) {
  if (!code) return null;
  const base = String(code).trim().toLowerCase().split(/[-_]/)[0];
  return isSupportedLanguage(base) ? base : null;
}

/** The preference saved on this device, or ``null`` if none/invalid. */
export function readStoredLanguage() {
  try {
    return normalizeLanguage(localStorage.getItem(LANGUAGE_STORAGE_KEY));
  } catch {
    return null; // localStorage can throw in private mode / sandboxed webviews
  }
}

/** Save (or clear) the device preference. Returns the normalised code. */
export function writeStoredLanguage(code) {
  const normalized = normalizeLanguage(code);
  try {
    if (normalized) localStorage.setItem(LANGUAGE_STORAGE_KEY, normalized);
    else localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  } catch {
    // Ignore: the in-memory i18next language still changes for this session.
  }
  return normalized;
}

/**
 * The device/browser language, if it is one we support.
 *
 * ``navigator.languages`` is preferred because it is ordered by preference and
 * lets a user whose first language is unsupported (e.g. Hindi) still match a
 * supported one further down the list.
 */
export function deviceLanguage() {
  if (typeof navigator === "undefined") return null;
  const candidates = [
    ...(Array.isArray(navigator.languages) ? navigator.languages : []),
    navigator.language,
  ];
  for (const candidate of candidates) {
    const normalized = normalizeLanguage(candidate);
    if (normalized) return normalized;
  }
  return null;
}

/**
 * Decide which language to start in.
 *
 * Order: saved preference → saved profile → device language → English.
 */
export function resolveInitialLanguage(profileLanguage) {
  return (
    readStoredLanguage() ??
    normalizeLanguage(profileLanguage) ??
    deviceLanguage() ??
    DEFAULT_LANGUAGE
  );
}

/** The label shown in the selector for *code*, always in its own script. */
export function languageLabel(code) {
  const normalized = normalizeLanguage(code);
  const match = SUPPORTED_LANGUAGES.find((item) => item.code === normalized);
  return match?.nativeLabel ?? "English";
}
