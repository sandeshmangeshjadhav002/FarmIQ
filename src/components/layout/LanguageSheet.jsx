import { useTranslation } from "react-i18next";

import Icon from "@/components/common/Icon";
import { SUPPORTED_LANGUAGES } from "@/i18n/language";

/**
 * Bottom-sheet overlay for selecting the display language.
 *
 * Only the two languages FarmIQ supports are offered. Each is shown in its own
 * script ("English" / "मराठी") so a Marathi speaker can recognise it without
 * reading English.
 *
 * @param {object}   props
 * @param {string}   props.selected   - Currently selected language code ("en" | "mr").
 * @param {Function} props.onSelect   - Called with the chosen language code.
 * @param {Function} props.onClose    - Dismisses the sheet.
 */
export default function LanguageSheet({ selected, onSelect, onClose }) {
  const { t } = useTranslation();

  return (
    <div
      className="absolute inset-0 z-50 flex items-end bg-[#143526]/35 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <section
        aria-label={t("languageSheet.aria")}
        className="max-h-[76%] w-full overflow-hidden rounded-t-[28px] bg-white/70 px-5 pb-6 shadow-2xl backdrop-blur-2xl border-t border-white/30"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mx-auto my-3 h-1.5 w-10 rounded-full bg-[#D7DFD9]" />
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-[20px] font-extrabold text-[#17392A]">
              {t("languageSheet.title")}
            </h2>
            <p className="mt-1 text-[12px] text-[#73857B]">
              {t("languageSheet.subtitle")}
            </p>
          </div>
          <button
            className="rounded-full bg-[#F1F5F1] px-3 py-2 text-xs font-bold text-[#52665B]"
            onClick={onClose}
          >
            {t("common.close")}
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2 overflow-y-auto">
          {SUPPORTED_LANGUAGES.map((language) => (
            <button
              key={language.code}
              className={`flex h-12 items-center justify-between rounded-xl border px-4 text-left text-sm font-semibold backdrop-blur-md ${
                selected === language.code
                  ? "border-[#216B45] bg-[#EAF3EC]/60 text-[#216B45]"
                  : "border-white/30 bg-white/40 text-[#354D40]"
              }`}
              onClick={() => onSelect(language.code)}
            >
              {language.nativeLabel}
              {selected === language.code && <Icon name="check" size={17} />}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
