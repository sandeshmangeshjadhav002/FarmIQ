/**
 * Language utilities for FarmIQ.
 *
 * The app stores the selected language as a display string (e.g. "Marathi")
 * inherited from the existing LanguageSheet component. The voice assistant and
 * backend need a BCP-47 code ("mr" | "en"). These helpers bridge the two.
 */

/** Display-name → BCP-47 code mapping. Only mr/en are voice-supported. */
export const LANG_DISPLAY_TO_CODE = {
  Marathi:  "mr",
  English:  "en",
};

/** BCP-47 code → display name */
export const LANG_CODE_TO_DISPLAY = {
  mr: "Marathi",
  en: "English",
};

/** Voice-supported language options for the voice assistant selector. */
export const VOICE_LANGUAGES = [
  { code: "mr", label: "मराठी (Marathi)", nativeLabel: "मराठी" },
  { code: "en", label: "English",         nativeLabel: "English" },
];

/** The default language code for first-time users. */
export const DEFAULT_VOICE_LANG = "mr";

/**
 * Convert a display language name to a BCP-47 code.
 * Returns DEFAULT_VOICE_LANG when the language is not voice-supported.
 */
export function toLangCode(displayName) {
  return LANG_DISPLAY_TO_CODE[displayName] ?? DEFAULT_VOICE_LANG;
}

/**
 * Convert a BCP-47 code to a display name.
 */
export function toDisplayName(code) {
  return LANG_CODE_TO_DISPLAY[code] ?? "Marathi";
}
