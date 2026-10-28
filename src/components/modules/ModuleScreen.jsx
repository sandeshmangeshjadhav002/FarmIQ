import { Suspense, lazy } from "react";
import { moduleCatalog } from "@/data/modules";
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
 */
export default function ModuleScreen({
  moduleKey,
  onBack,
  onAsk,
  currentLanguage,
  onLanguage,
}) {
  const info = moduleCatalog.find((item) => item.key === moduleKey);

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
        return <OrganicFarmingAdvisor />;
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
            {info?.group}
          </p>
          <h1 className="text-[20px] font-extrabold leading-tight tracking-[-.03em] text-[#17392A]">
            {info?.title}
          </h1>
          <p className="mt-1 text-[10px] text-[#7B8C82]">{info?.short}</p>
        </div>
      </header>

      {/* The header above paints immediately; only the panel itself waits for
          its chunk. */}
      <Suspense fallback={<ScreenLoader label="Loading module…" />}>
        {renderContent()}
      </Suspense>
    </div>
  );
}
