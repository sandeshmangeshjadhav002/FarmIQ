/**
 * i18next bootstrap for FarmIQ.
 *
 * English and Marathi each live in their own folder of JSON files
 * (``src/i18n/locales/en/*.json`` and ``src/i18n/locales/mr/*.json``). One file
 * per area keeps the translations reviewable — a translator can work on the
 * chat copy without scrolling past the settings panel — while every file is
 * merged into a single namespace so components just call ``t("home.title")``.
 *
 * ``import.meta.glob`` means a new area file is picked up automatically: no
 * central registry to forget to update.
 */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { DEFAULT_LANGUAGE, LANGUAGE_CODES, normalizeLanguage, resolveInitialLanguage } from "./language";

/** Merge every ``*.json`` in a language folder into one resource object. */
const mergeJson = (modules) =>
  Object.assign({}, ...Object.keys(modules).sort().map((path) => modules[path]));

const enFiles = import.meta.glob("./locales/en/*.json", {
  eager: true,
  import: "default",
});
const mrFiles = import.meta.glob("./locales/mr/*.json", {
  eager: true,
  import: "default",
});

export const resources = {
  en: { translation: mergeJson(enFiles) },
  mr: { translation: mergeJson(mrFiles) },
};

/**
 * Keep ``<html lang>`` in step with the selected language.
 *
 * WebView/Android font fallback and screen readers both key off this, so
 * Marathi (Devanagari) text is rendered with the right font stack.
 */
export function syncDocumentLanguage(code) {
  if (typeof document === "undefined") return;
  const lang = normalizeLanguage(code) ?? DEFAULT_LANGUAGE;
  document.documentElement.lang = lang;
  document.documentElement.setAttribute("data-language", lang);
}

i18n.use(initReactI18next).init({
  resources,
  lng: resolveInitialLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: LANGUAGE_CODES,
  nonExplicitSupportedLngs: true,
  // The dictionaries are bundled, so initialise synchronously: the first paint
  // is already translated (and tests can assert on real copy immediately).
  initImmediate: false,
  interpolation: { escapeValue: false },
  returnNull: false,
  react: { useSuspense: false },
});

syncDocumentLanguage(i18n.language);
i18n.on("languageChanged", syncDocumentLanguage);

export default i18n;
