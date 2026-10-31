import { Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";

import {
  moduleCatalog,
  sectionByKey,
  canAccessAdminTools,
} from "@/data/modules";
import ScreenLoader from "@/components/common/ScreenLoader";
import ModuleIcon from "./ModuleIcon";

// Module panels are split into individual chunks. ModuleHub lists every module
// in the catalogue, so importing them all eagerly would put the entire app in
// the entry bundle; this way opening one module downloads only that module.
const GenericModule = lazy(() => import("./GenericModule"));
const MlModule = lazy(() => import("./MlModule"));
const FarmManager = lazy(() => import("./FarmManager"));
const ImageAnalysis = lazy(() => import("./ImageAnalysis"));
const CalendarManager = lazy(() => import("./CalendarManager"));
const KnowledgeCenter = lazy(() => import("./KnowledgeCenter"));
const SettingsPanel = lazy(() => import("./SettingsPanel"));
const DeviceManager = lazy(() => import("./DeviceManager"));
const SensorSimulator = lazy(() => import("./SensorSimulator"));
const Schemes = lazy(() => import("./Schemes"));
const MlopsDashboard = lazy(() => import("./MlopsDashboard"));
const OrganicFarmingAdvisor = lazy(() => import("./OrganicFarmingAdvisor"));
const DroughtAdvisor = lazy(() => import("./DroughtAdvisor"));
const HackathonDemo = lazy(() => import("./HackathonDemo"));
const AlertsPanel = lazy(() => import("./AlertsPanel"));

/**
 * Renders the correct content component for a given module key,
 * wrapped in a consistent header with back button and module identity.
 *
 * @param {object}   props
 * @param {string}   props.moduleKey      - Active module key.
 * @param {Function} props.onBack         - Navigate back to the module hub.
 * @param {Function} props.onAsk          - Navigate to the chat screen.
 * @param {string}   props.currentLanguage
 * @param {Function} props.onLanguage     - Update language from settings.
 * @param {object}   [props.user]         - Signed-in user, used for the admin gate.
 */
export default function ModuleScreen({
  moduleKey,
  onBack,
  onAsk,
  currentLanguage,
  onLanguage,
  user,
}) {
  const { t } = useTranslation();
  const info = moduleCatalog.find((item) => item.key === moduleKey);
  const section = sectionByKey(info?.section);

  // Administrative/MLOps modules are hidden from the browse grid, but the route
  // can still be reached (deep link, stale state). Refuse it here rather than
  // rendering a technical panel to a farmer.
  if (info?.adminOnly && !canAccessAdminTools(user)) {
    return (
      <div className="px-5 pb-8 pt-5">
        <header className="mb-5 flex items-start gap-3">
          <button
            onClick={onBack}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[#DDE6DF] bg-white text-[#3F5A4B]"
          >
            <ModuleIcon name="back" size={19} />
          </button>
          <div className="min-w-0">
            <p className="text-[9px] font-bold uppercase tracking-[.12em] text-[#6D8377]">
              {t("moduleScreen.restricted")}
            </p>
            <h1 className="text-[20px] font-extrabold leading-tight tracking-[-.03em] text-[#17392A]">
              {t(`modules.${moduleKey}.title`, t("moduleScreen.adminTool"))}
            </h1>
          </div>
        </header>
        <div className="rounded-[20px] border border-dashed border-[#B0C9B8] p-6 text-center">
          <p className="text-[12px] font-bold text-[#3C5C49]">
            {t("moduleScreen.adminOnly")}
          </p>
          <p className="mt-1.5 text-[10px] leading-5 text-[#7B8C82]">
            {t("moduleScreen.adminOnlyBody")}
          </p>
        </div>
      </div>
    );
  }

  const renderContent = () => {
    switch (moduleKey) {
      case "farm-management":
        return <FarmManager />;
      case "image-analysis":
        return <ImageAnalysis />;
      case "calendar":
        return <CalendarManager />;
      case "knowledge":
        return <KnowledgeCenter onAsk={onAsk} />;
      case "settings":
        return (
          <SettingsPanel
            currentLanguage={currentLanguage}
            onLanguage={onLanguage}
          />
        );
      case "devices":
        return <DeviceManager />;
      case "sensor-simulator":
        return <SensorSimulator />;
      case "schemes":
        return <Schemes />;
      case "organic-farming":
        return <OrganicFarmingAdvisor onAsk={onAsk} />;
      case "drought-management":
        return <DroughtAdvisor />;
      case "hackathon-demo":
        return <HackathonDemo />;
      case "alerts":
        return <AlertsPanel />;
      case "mlops":
        return <MlopsDashboard />;
      case "crop-recommendation":
      case "fertilizer":
      case "irrigation":
      case "yield":
        return <MlModule moduleKey={moduleKey} onAsk={onAsk} />;
      default:
        return <GenericModule moduleKey={moduleKey} onAsk={onAsk} />;
    }
  };

  return (
    <div className="px-5 pb-8 pt-5">
      <header className="mb-5 flex items-start gap-3">
        <button
          onClick={onBack}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[#DDE6DF] bg-white text-[#3F5A4B]"
        >
          <ModuleIcon name="back" size={19} />
        </button>
        <span
          className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${info?.color}`}
        >
          <ModuleIcon name={info?.icon} size={19} />
        </span>
        <div className="min-w-0">
          <p className="text-[9px] font-bold uppercase tracking-[.12em] text-[#6D8377]">
            {section
              ? t(`sections.${section.key}.label`)
              : t("moduleScreen.fallbackSection")}
          </p>
          <h1 className="text-[20px] font-extrabold leading-tight tracking-[-.03em] text-[#17392A]">
            {t(`modules.${moduleKey}.title`)}
          </h1>
        </div>
      </header>

      {/* The header above paints immediately; only the panel itself waits for
          its chunk. */}
      <Suspense fallback={<ScreenLoader label={t("common.loadingModule")} />}>
        {renderContent()}
      </Suspense>
    </div>
  );
}
