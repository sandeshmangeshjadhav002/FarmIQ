import { useTranslation } from "react-i18next";

import {
  browsableModules,
  canAccessAdminTools,
  sections,
} from "@/data/modules";
import ModuleIcon from "@/components/modules/ModuleIcon";

/**
 * Sticky left sidebar shown on lg+ breakpoints.
 *
 * Mirrors the mobile bottom navigation (Home / My Farm / Advisor / Insights)
 * and then lists the tools of each section beneath its heading, so the desktop
 * and mobile builds present the same six-section structure. Administrative and
 * MLOps tools appear only for the authorised role.
 *
 * @param {object}   props
 * @param {object}   [props.user]         - Signed-in user, used for the admin gate.
 * @param {string}   [props.activeNav]    - Active top-level destination key.
 * @param {string}   [props.activeModule] - Currently open module key.
 * @param {Function} props.onNavigate     - Navigate to a screen ("home", "farm"…).
 * @param {Function} props.onAssistant    - Open the conversational assistant.
 * @param {Function} props.onOpen         - Open a module by key.
 */
export default function DesktopNavigation({
  user,
  activeNav,
  activeModule,
  onNavigate,
  onAssistant,
  onOpen,
}) {
  const { t } = useTranslation();
  const visible = browsableModules(user);
  const topLevel = [
    { key: "home", icon: "home" },
    { key: "farm", icon: "farm" },
    { key: "advisor", icon: "sparkles" },
    { key: "insights", icon: "chart" },
  ];

  // Every section except "admin" (rendered separately, gated) that still has a
  // visible tool to offer.
  const groups = sections
    .filter((section) => section.key !== "admin")
    .map((section) => ({
      section,
      items: visible.filter((item) => item.section === section.key),
    }))
    .filter((group) => group.items.length > 0);

  const adminTools = visible.filter((item) => item.section === "admin");
  const showAdmin = canAccessAdminTools(user) && adminTools.length > 0;

  return (
    <aside className="sticky top-6 hidden h-[calc(100vh-3rem)] w-64 shrink-0 flex-col overflow-hidden rounded-[24px] bg-[#17392A]/60 text-white shadow-xl backdrop-blur-2xl border border-white/10 lg:flex print:hidden">
      <div className="border-b border-white/10 p-5">
        <div className="text-[20px] font-extrabold">FarmIQ</div>
        <div className="text-[9px] uppercase tracking-[.14em] text-white/50">
          {t("nav.appTagline")}
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto p-3">
        {topLevel.map((item) => (
          <button
            key={item.key}
            onClick={() => onNavigate(item.key)}
            aria-current={activeNav === item.key ? "page" : undefined}
            className={`mb-1 flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[11px] font-bold ${
              activeNav === item.key
                ? "bg-white/15 text-white"
                : "text-white/70 hover:bg-white/10"
            }`}
          >
            <ModuleIcon name={item.icon} size={16} />
            {t(`sections.${item.key}.label`)}
          </button>
        ))}

        <button
          onClick={onAssistant}
          className="mb-3 mt-1 flex w-full items-center gap-3 rounded-xl bg-[#2C7B54] px-3 py-2.5 text-left text-[11px] font-bold"
        >
          <ModuleIcon name="bot" size={16} />
          {t("nav.askFarmIQ")}
        </button>

        {groups.map(({ section, items }) => (
          <div key={section.key} className="mb-3">
            <p className="px-3 pb-1 pt-2 text-[8px] font-extrabold uppercase tracking-[.14em] text-white/40">
              {t(`sections.${section.key}.label`)}
            </p>
            {items.map((item) => (
              <button
                key={item.key}
                onClick={() => onOpen(item.key)}
                className={`mb-1 flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-[10px] font-semibold ${
                  activeModule === item.key
                    ? "bg-white/15 text-white"
                    : "text-white/65 hover:bg-white/10"
                }`}
              >
                <ModuleIcon name={item.icon} size={15} />
                {t(`modules.${item.key}.title`)}
              </button>
            ))}
          </div>
        ))}
      </nav>

      {showAdmin && (
        <div className="border-t border-white/10 p-3">
          <p className="px-1 pb-1 text-[8px] font-extrabold uppercase tracking-[.14em] text-white/40">
            {t("sections.admin.label")}
          </p>
          {adminTools.map((item) => (
            <button
              key={item.key}
              onClick={() => onOpen(item.key)}
              className={`mb-1 flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-[10px] font-semibold ${
                activeModule === item.key
                  ? "bg-white/15 text-white"
                  : "text-white/65 hover:bg-white/10"
              }`}
            >
              <ModuleIcon name={item.icon} size={15} />
              {t(`modules.${item.key}.title`)}
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
