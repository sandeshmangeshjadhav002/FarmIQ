import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { browsableModules, sections } from "@/data/modules";
import ModuleIcon from "./ModuleIcon";

/**
 * All-tools browser — searchable, section-grouped list of every FarmIQ module.
 *
 * Modules flagged ``contextual`` (device pairing, sensor simulation) are
 * deliberately absent: they are opened from the screen that owns them, so they
 * would only add noise here. Modules flagged ``adminOnly`` appear only for the
 * authorised role.
 *
 * @param {object}   props
 * @param {Function} props.onBack - Navigate back to the home screen.
 * @param {Function} props.onOpen - Open a module by its key.
 * @param {object}   [props.user] - Signed-in user, used for the admin gate.
 */
export default function ModuleHub({ onBack, onOpen, user }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [activeSection, setActiveSection] = useState("all");

  const modules = useMemo(() => browsableModules(user), [user]);

  // Only offer a section filter when that section actually has visible tools —
  // an empty chip would promise something the user cannot reach.
  const availableSections = useMemo(
    () => sections.filter((s) => modules.some((m) => m.section === s.key)),
    [modules],
  );

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return modules.filter((item) => {
      const title = t(`modules.${item.key}.title`);
      const short = t(`modules.${item.key}.short`);
      return (
        (activeSection === "all" || item.section === activeSection) &&
        (!needle || `${title} ${short}`.toLowerCase().includes(needle))
      );
    });
  }, [modules, activeSection, query, t]);

  const groups = useMemo(
    () =>
      availableSections
        .map((section) => ({
          section,
          items: matches.filter((m) => m.section === section.key),
        }))
        .filter((group) => group.items.length > 0),
    [availableSections, matches],
  );

  return (
    <div className="px-5 pb-8 pt-5">
      <header className="flex items-center gap-3">
        <button
          onClick={onBack}
          aria-label={t("moduleHub.backToHome")}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/30 bg-white/40 text-[#3F5A4B] backdrop-blur-md shadow-sm"
        >
          <ModuleIcon name="back" size={19} />
        </button>
        <h1 className="text-[25px] font-extrabold tracking-[-.04em] text-[#17392A]">
          {t("moduleHub.title")}
        </h1>
      </header>

      <label className="mt-5 flex h-12 items-center gap-3 rounded-2xl border border-white/30 bg-white/40 px-4 backdrop-blur-md shadow-sm">
        <ModuleIcon name="search" size={18} />
        <input
          aria-label={t("moduleHub.searchAria")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="min-w-0 flex-1 bg-transparent text-[12px] outline-none"
          placeholder={t("moduleHub.searchPlaceholder")}
        />
      </label>

      <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
        <SectionChip
          label={t("common.all")}
          selected={activeSection === "all"}
          onClick={() => setActiveSection("all")}
        />
        {availableSections.map((section) => (
          <SectionChip
            key={section.key}
            label={t(`sections.${section.key}.label`)}
            selected={activeSection === section.key}
            onClick={() => setActiveSection(section.key)}
          />
        ))}
      </div>

      {groups.length === 0 && (
        <div className="mt-8 rounded-[20px] border border-dashed border-[#B0C9B8] p-8 text-center">
          <p className="text-[12px] font-bold text-[#3C5C49]">
            {t("moduleHub.noMatch", { query })}
          </p>
          <p className="mt-1.5 text-[10px] text-[#7B8C82]">
            {t("moduleHub.noMatchBody")}
          </p>
        </div>
      )}

      {groups.map(({ section, items }) => (
        <section key={section.key} className="mt-6">
          <div className="mb-3 flex items-start gap-2.5">
            <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-[#E6F2E9] text-[#216B45]">
              <ModuleIcon name={section.icon} size={15} />
            </span>
            <div className="min-w-0">
              <h2 className="text-[15px] font-extrabold leading-tight tracking-[-.02em] text-[#1B3A2B]">
                {t(`sections.${section.key}.label`)}
              </h2>
              <p className="mt-0.5 text-[10px] text-[#7B8C82]">
                {t(`sections.${section.key}.short`)}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {items.map((item) => (
              <button
                key={item.key}
                onClick={() => onOpen(item.key)}
                className="flex items-center gap-3 rounded-[18px] border border-white/30 bg-white/40 p-4 text-left shadow-[0_4px_14px_rgba(31,57,44,.04)] backdrop-blur-md transition hover:-translate-y-0.5"
              >
                <span
                  className={`grid h-11 w-11 shrink-0 place-items-center rounded-2xl ${item.color}`}
                >
                  <ModuleIcon name={item.icon} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-extrabold text-[#233F31]">
                    {t(`modules.${item.key}.title`)}
                  </span>
                  <span className="mt-1 block text-[10px] leading-4 text-[#75877D]">
                    {t(`modules.${item.key}.short`)}
                  </span>
                </span>
                <ModuleIcon name="arrow" size={16} />
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** Pill-shaped section filter. */
function SectionChip({ label, selected, onClick }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={selected}
      className={`shrink-0 rounded-full px-3 py-2 text-[10px] font-bold backdrop-blur-md ${
        selected
          ? "bg-[#216B45] text-white"
          : "border border-white/30 bg-white/40 text-[#607369]"
      }`}
    >
      {label}
    </button>
  );
}
