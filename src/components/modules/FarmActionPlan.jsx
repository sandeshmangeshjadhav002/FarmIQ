/**
 * FarmActionPlan — Today's Farm Decision Engine output.
 *
 * Fetches GET /api/dashboard/plan and renders:
 *   - Overall summary badge
 *   - Prioritised action cards (critical → high → moderate → low)
 *   - Farm conditions strip (weather + sensor)
 *   - What the plan could not assess (missing sensor / weather / crop / location)
 *
 * Used on the HomeScreen. Entirely data-driven — shows meaningful empty states.
 *
 * Nothing is computed here and no model is called: the plan is built once on
 * the backend from data the app already has, so opening Home does not run every
 * ML model.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import useApi from "@/hooks/useApi";
import { moduleByKey } from "@/data/modules";
import ModuleIcon from "./ModuleIcon";

const PRIORITY_CONFIG = {
  critical: {
    bg: "bg-[#FCE9E5]",
    border: "border-[#E8B4AE]",
    text: "text-[#9D3E2E]",
    dot: "bg-[#E8493B]",
    badge: "bg-[#E8493B] text-white",
    label: "Critical",
  },
  high: {
    bg: "bg-[#FFF5DE]",
    border: "border-[#F0D090]",
    text: "text-[#8A6D2B]",
    dot: "bg-[#D99A2B]",
    badge: "bg-[#D99A2B] text-white",
    label: "High",
  },
  moderate: {
    bg: "bg-[#E8EEF8]",
    border: "border-[#C0CDE8]",
    text: "text-[#3F5A90]",
    dot: "bg-[#4F6590]",
    badge: "bg-[#4F6590] text-white",
    label: "Moderate",
  },
  low: {
    bg: "bg-white",
    border: "border-[#E0E8E2]",
    text: "text-[#52665B]",
    dot: "bg-[#9ABBA6]",
    badge: "bg-[#9ABBA6] text-white",
    label: "Low",
  },
};

const CATEGORY_ICON = {
  irrigation: "drop",
  soil: "soil",
  fertilizer: "flask",
  weather: "sun",
  data_quality: "signal",
};

/**
 * Which existing tool explains or acts on each action category.
 *
 * "weather" is deliberately absent: there is no weather module to open, and
 * sending the farmer somewhere unrelated would be worse than no link.
 */
const CATEGORY_MODULE = {
  irrigation: "irrigation",
  soil: "soil",
  fertilizer: "fertilizer",
  data_quality: "devices",
};

function fmt(val, unit = "") {
  if (val == null) return "—";
  return `${typeof val === "number" ? val.toFixed(1) : val}${unit}`;
}

// ── Action Card ───────────────────────────────────────────────────────────────
function ActionCard({ action, onOpen }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const cfg = PRIORITY_CONFIG[action.priority] ?? PRIORITY_CONFIG.low;
  const priorityLabel = t(`actionPlan.priority.${action.priority}`, {
    defaultValue: cfg.label,
  });
  const categoryLabel = action.category
    ? t(`actionPlan.category.${action.category}`, {
        defaultValue: action.category.replace("_", " "),
      })
    : "";
  const icon = CATEGORY_ICON[action.category] ?? "check";
  const moduleKey = CATEGORY_MODULE[action.category];
  const target = moduleKey ? moduleByKey(moduleKey) : null;
  const hasDetails =
    action.warnings?.length > 0 ||
    action.assumptions?.length > 0 ||
    Object.keys(action.supporting_data || {}).length > 0;

  return (
    <div className={`rounded-[20px] border p-4 ${cfg.bg} ${cfg.border}`}>
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-white/70 ${cfg.text}`}
        >
          <ModuleIcon name={icon} size={16} />
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span
              className={`rounded-full px-2 py-0.5 text-[8px] font-extrabold uppercase tracking-[.06em] ${cfg.badge}`}
            >
              {priorityLabel}
            </span>
            <span className="text-[9px] font-semibold uppercase tracking-[.08em] text-[#7A8C82]">
              {categoryLabel}
            </span>
          </div>
          <p className={`text-[12px] font-extrabold leading-5 ${cfg.text}`}>
            {action.action}
          </p>
          <p className="mt-0.5 text-[10px] leading-5 text-[#5A6F63]">
            {action.reason}
          </p>
        </div>
      </div>

      {/* Expandable evidence */}
      {hasDetails && (
        <button
          onClick={() => setOpen(!open)}
          className={`mt-2 text-[9px] font-bold ${cfg.text} hover:underline`}
        >
          {open ? t("actionPlan.hideEvidence") : t("actionPlan.showEvidence")}
        </button>
      )}

      {open && (
        <div className="mt-2 space-y-1.5 border-t border-white/40 pt-2">
          {Object.entries(action.supporting_data || {}).map(([k, v]) => (
            <p key={k} className="text-[9px] text-[#5A6F63]">
              <span className="font-bold">{k.replace(/_/g, " ")}:</span>{" "}
              {String(v)}
            </p>
          ))}
          {action.warnings?.map((w, i) => (
            <p key={i} className="text-[9px] text-[#8A6D2B]">
              ⚠ {w}
            </p>
          ))}
          {action.assumptions?.map((a, i) => (
            <p key={i} className="text-[9px] italic text-[#7A8C82]">
              * {a}
            </p>
          ))}
        </div>
      )}

      {/* Deep link into the tool that owns this recommendation */}
      {target && (
        <button
          onClick={() => onOpen?.(moduleKey)}
          className={`mt-2.5 inline-flex items-center gap-1.5 rounded-xl bg-white/70 px-3 py-2 text-[10px] font-bold ${cfg.text}`}
        >
          <ModuleIcon name={target.icon} size={13} />
          {t("actionPlan.openTool", { name: t(`modules.${moduleKey}.title`) })}
          <ModuleIcon name="arrow" size={13} />
        </button>
      )}
    </div>
  );
}

// ── Missing information ───────────────────────────────────────────────────────
/**
 * What the plan could not assess, stated plainly.
 *
 * The decision engine reports which inputs it actually had; naming the gaps
 * stops an incomplete plan from reading like a complete one.
 */
function MissingInformation({ inputs }) {
  const { t } = useTranslation();
  if (!inputs) return null;
  const gaps = [];
  if (inputs.sensor_available === false)
    gaps.push(t("actionPlan.missing.noSensor"));
  if (inputs.weather_available === false)
    gaps.push(t("actionPlan.missing.noWeather"));
  if (!inputs.crop) gaps.push(t("actionPlan.missing.noCrop"));
  if (!inputs.location) gaps.push(t("actionPlan.missing.noLocation"));

  if (gaps.length === 0) return null;

  return (
    <div className="rounded-[18px] border border-[#E8DFC6] bg-[#FFFBF0] p-3.5">
      <p className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#8A6D2B]">
        {t("actionPlan.missing.title")}
      </p>
      <ul className="mt-1.5 space-y-1">
        {gaps.map((gap) => (
          <li key={gap} className="text-[10px] leading-5 text-[#7A6A43]">
            • {gap}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Conditions strip ──────────────────────────────────────────────────────────
function ConditionsStrip({ weather, sensor }) {
  const { t } = useTranslation();
  if (!weather && !sensor) return null;

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {weather?.temperature_c != null && (
        <CondTile
          icon="sun"
          label={t("actionPlan.conditions.temperature")}
          value={fmt(weather.temperature_c, "°C")}
          note={t("actionPlan.conditions.current")}
        />
      )}
      {weather?.humidity_pct != null && (
        <CondTile
          icon="drop"
          label={t("actionPlan.conditions.humidity")}
          value={fmt(weather.humidity_pct, "%")}
          note={t("actionPlan.conditions.current")}
        />
      )}
      {weather?.forecast_rain_7d_mm != null && (
        <CondTile
          icon="drop"
          label={t("actionPlan.conditions.rain7d")}
          value={fmt(weather.forecast_rain_7d_mm, " mm")}
          note={t("actionPlan.conditions.notConfirmed")}
          warn
        />
      )}
      {sensor?.soil_moisture != null && (
        <CondTile
          icon="soil"
          label={t("actionPlan.conditions.soilMoisture")}
          value={fmt(sensor.soil_moisture, "%")}
          note={
            sensor.is_demo
              ? t("actionPlan.conditions.demoSimulated")
              : t("actionPlan.conditions.sensor")
          }
          demo={sensor.is_demo}
        />
      )}
      {sensor?.soil_temperature != null && (
        <CondTile
          icon="soil"
          label={t("actionPlan.conditions.soilTemp")}
          value={fmt(sensor.soil_temperature, "°C")}
          note={
            sensor.is_demo
              ? t("actionPlan.conditions.demoSimulated")
              : t("actionPlan.conditions.sensor")
          }
          demo={sensor.is_demo}
        />
      )}
    </div>
  );
}

function CondTile({ icon, label, value, note, warn = false, demo = false }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-2xl border border-[#E0E8E2] bg-white p-3">
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-[#6D8377]">
          <ModuleIcon name={icon} size={12} />
        </span>
        <span className="text-[9px] font-bold uppercase tracking-[.06em] text-[#7A8B82]">
          {label}
        </span>
      </div>
      <p
        className={`text-[18px] font-extrabold tracking-tight ${
          warn ? "text-[#D99A2B]" : "text-[#1D3A2B]"
        }`}
      >
        {value}
      </p>
      <p
        className={`text-[8px] mt-0.5 ${
          demo ? "text-[#D99A2B]" : "text-[#9AA79F]"
        }`}
      >
        {demo ? t("actionPlan.conditions.demoSimulated") : note}
      </p>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function FarmActionPlan({ openModule }) {
  const { t } = useTranslation();
  const { data, loading, error, refetch } = useApi("/api/dashboard/plan");
  const [expanded, setExpanded] = useState(false);

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="h-5 w-48 animate-pulse rounded-full bg-[#E8F0EB]" />
        {[1, 2].map((n) => (
          <div
            key={n}
            className="h-24 animate-pulse rounded-[20px] bg-[#E8F0EB]"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-[20px] bg-[#FCE9E5] p-4">
        <p className="text-[11px] font-bold text-[#9D4C3E]">
          {t("actionPlan.couldNotLoad")}{" "}
          <button onClick={refetch} className="underline">
            {t("actionPlan.retry")}
          </button>
        </p>
      </div>
    );
  }

  if (!data) return null;

  const actions = data.actions ?? [];
  const visibleActions = expanded ? actions : actions.slice(0, 5);
  const hiddenCount = actions.length - visibleActions.length;

  return (
    <div className="space-y-3">
      {/* Summary badge */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[11px] font-bold text-[#5D7B6B] uppercase tracking-[.08em]">
            {t("actionPlan.todayPlan")}
          </p>
          <p className="text-[12px] font-semibold text-[#3A5A4A] mt-0.5">
            {data.summary}
          </p>
        </div>
        {data.critical_count > 0 && (
          <span className="rounded-full bg-[#E8493B] px-3 py-1 text-[10px] font-extrabold text-white">
            {t("actionPlan.criticalCount", { count: data.critical_count })}
          </span>
        )}
      </div>

      {/* Farm conditions */}
      <ConditionsStrip
        weather={data.weather_summary}
        sensor={data.sensor_summary}
      />

      {/* No data empty state */}
      {actions.length === 0 && (
        <div className="rounded-[20px] border border-dashed border-[#B0C9B8] p-6 text-center">
          <p className="text-[12px] font-bold text-[#3C5C49]">
            {t("actionPlan.noRecommendations")}
          </p>
          <p className="mt-1.5 text-[10px] text-[#7B8C82]">
            {t("actionPlan.noRecommendationsBody")}
          </p>
          <button
            onClick={() => openModule?.("farm-management")}
            className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-[#216B45] px-4 py-2 text-[11px] font-bold text-white"
          >
            <ModuleIcon name="farm" size={14} />
            {t("actionPlan.addFarm")}
          </button>
        </div>
      )}

      {/* Action cards — most important first */}
      {visibleActions.map((action, i) => (
        <ActionCard
          key={`${action.category}-${i}`}
          action={action}
          onOpen={openModule}
        />
      ))}

      {hiddenCount > 0 && (
        <button
          onClick={() => setExpanded(true)}
          className="w-full rounded-[20px] border border-[#DDE6DF] bg-white/60 py-3 text-[11px] font-bold text-[#216B45] hover:bg-white transition"
        >
          {t("actionPlan.showMore", { count: hiddenCount })}
        </button>
      )}

      {/* What the plan could not assess */}
      <MissingInformation inputs={data.data_inputs} />

      {data.generated_at && (
        <p className="text-[9px] text-[#9AA79F] text-right">
          {t("actionPlan.planGenerated", {
            time: new Date(data.generated_at).toLocaleTimeString("en-IN", {
              hour: "2-digit",
              minute: "2-digit",
            }),
          })}
        </p>
      )}
    </div>
  );
}
