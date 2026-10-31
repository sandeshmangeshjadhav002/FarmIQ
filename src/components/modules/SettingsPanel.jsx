import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SelectField } from "./ModuleShared";
import ModuleIcon from "./ModuleIcon";
import { SUPPORTED_LANGUAGES } from "@/i18n/language";
import useApi from "@/hooks/useApi";

/** Area units whose stored value is a fixed model/API token. */
const AREA_UNITS = ["Acres", "Hectares", "Guntha"];

/**
 * Profile & Settings module — shows the real logged-in user (from /api/users/me),
 * language picker, area units, voice toggle.
 *
 * @param {object}   props
 * @param {string}   props.currentLanguage - Currently selected language code.
 * @param {Function} props.onLanguage      - Called with the new language code.
 */
export default function SettingsPanel({ currentLanguage, onLanguage }) {
  const { t } = useTranslation();
  const [units, setUnits] = useState("Acres");
  const [voice, setVoice] = useState(true);

  const { data: profile } = useApi("/api/users/me");

  /** Derive initials from a full name string. */
  const initials = (name = "") =>
    name
      .trim()
      .split(/\s+/)
      .map((w) => w[0]?.toUpperCase() ?? "")
      .slice(0, 2)
      .join("");

  const displayName = profile?.full_name ?? t("settings.placeholder");
  const displayRole = profile
    ? t(`roles.${profile.role}`, { defaultValue: profile.role })
    : t("settings.placeholder");

  return (
    <div className="space-y-4">
      {/* User profile */}
      <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <div className="flex items-center gap-3">
          <span className="grid h-12 w-12 place-items-center rounded-full bg-[#E7F2E9] text-[16px] font-extrabold text-[#216B45]">
            {initials(displayName)}
          </span>
          <div>
            <h2 className="text-[14px] font-extrabold text-[#213D2F]">
              {displayName}
            </h2>
            <p className="text-[10px] text-[#7D8E84]">{displayRole}</p>
          </div>
        </div>
      </section>

      {/* Language */}
      <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <h2 className="text-[14px] font-extrabold text-[#213D2F]">
          {t("settings.language")}
        </h2>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {SUPPORTED_LANGUAGES.map(({ code, nativeLabel }) => (
            <button
              key={code}
              onClick={() => onLanguage(code)}
              className={`flex h-10 items-center justify-between rounded-xl border px-3 text-left text-[10px] font-bold ${
                currentLanguage === code
                  ? "border-[#216B45] bg-[#EAF3EC] text-[#216B45]"
                  : "border-[#E2E9E4] text-[#4F6559]"
              }`}
            >
              {nativeLabel}
              {currentLanguage === code && <ModuleIcon name="check" size={14} />}
            </button>
          ))}
        </div>
      </section>

      {/* Preferences */}
      <section className="space-y-3 rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <SelectField
          label={t("settings.farmAreaUnits")}
          value={units}
          onChange={setUnits}
          options={AREA_UNITS.map((unit) => ({
            value: unit,
            label: t(`units.${unit}`),
          }))}
        />
        <button
          onClick={() => setVoice(!voice)}
          className="flex w-full items-center justify-between rounded-xl bg-[#F3F6F2] p-3 text-[11px] font-bold text-[#40594B]"
        >
          <span>{t("settings.readAloud")}</span>
          <span
            className={`relative h-6 w-11 rounded-full ${
              voice ? "bg-[#216B45]" : "bg-[#B8C4BC]"
            }`}
          >
            <span
              className={`absolute top-1 h-4 w-4 rounded-full bg-white transition ${
                voice ? "left-6" : "left-1"
              }`}
            />
          </span>
        </button>
      </section>
    </div>
  );
}
