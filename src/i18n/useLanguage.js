/**
 * ``useLanguage`` — the single entry point components use to read or change the
 * app language.
 *
 * Changing the language does three things:
 *   1. saves it on the device (localStorage) so the choice survives a reload
 *      and an Android app restart,
 *   2. switches i18next immediately, so the whole UI re-renders in the new
 *      language without a page load,
 *   3. mirrors it into the signed-in user's Supabase profile (``profiles.language``)
 *      so the preference follows them to another device.
 *
 * Guest users (no token) skip step 3 — the request would simply 401.
 */
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { apiPatch, getAuthToken, loadUser, saveUser } from "@/lib/apiClient";

import {
  DEFAULT_LANGUAGE,
  normalizeLanguage,
  SUPPORTED_LANGUAGES,
  writeStoredLanguage,
} from "./language";

export default function useLanguage() {
  const { i18n, t } = useTranslation();

  const language =
    normalizeLanguage(i18n.resolvedLanguage || i18n.language) ?? DEFAULT_LANGUAGE;

  /**
   * @param {string} next            - "en" | "mr" (or any locale we can normalise).
   * @param {object} [options]
   * @param {boolean} [options.persist=true] - Save to localStorage + profile.
   *   Pass ``false`` for a one-off override that must not change the preference.
   */
  const changeLanguage = useCallback(
    (next, { persist = true } = {}) => {
      const code = normalizeLanguage(next);
      if (!code) return language;

      if (persist) writeStoredLanguage(code);
      if (code !== language) i18n.changeLanguage(code);

      // Mirror into the Supabase-backed profile. Fire-and-forget: the device
      // preference is already saved, and a guest has nothing to patch.
      if (persist && getAuthToken()) {
        const user = loadUser();
        apiPatch("/api/users/me", { language: code })
          .then((updated) => {
            if (user) saveUser({ ...user, ...updated, language: code });
          })
          .catch(() => {
            /* Non-fatal — keep the local preference. */
          });
      }

      return code;
    },
    [i18n, language],
  );

  return { language, changeLanguage, languages: SUPPORTED_LANGUAGES, t, i18n };
}
