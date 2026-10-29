/**
 * FarmActionPlan — Today's Farm Decision Engine output.
 *
 * Fetches GET /api/dashboard/plan and renders:
 *   - Overall summary badge
 *   - Prioritised action cards (critical → high → moderate → low)
 *   - Farm conditions strip (weather + sensor)
 *
 * Used on the HomeScreen. Entirely data-driven — shows meaningful empty states.
 */
import { useState } from "react";
import useApi from "@/hooks/useApi";
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

function fmt(val, unit = "") {
  if (val == null) return "—";
  return `${typeof val === "number" ? val.toFixed(1) : val}${unit}`;
}

// ── Action Card ───────────────────────────────────────────────────────────────
function ActionCard({ action }) {
  const [open, setOpen] = useState(false);
  const cfg = PRIORITY_CONFIG[action.priority] ?? PRIORITY_CONFIG.low;
  const icon = CATEGORY_ICON[action.category] ?? "check";

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
              {cfg.label}
            </span>
            <span className="text-[9px] font-semibold uppercase tracking-[.08em] text-[#7A8C82]">
              {action.category?.replace("_", " ")}
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

      {/* Expandable details */}
      {(action.warnings?.length > 0 ||
        action.assumptions?.length > 0 ||
        Object.keys(action.supporting_data || {}).length > 0) && (
        <button
          onClick={() => setOpen(!open)}
          className={`mt-2 text-[9px] font-bold ${cfg.text} hover:underline`}
        >
          {open ? "Hide details ▲" : "Show details ▼"}
        </button>
      )}

      {open && (
        <div className="mt-2 space-y-1.5 border-t border-white/40 pt-2">
          {Object.entries(action.supporting_data || {}).map(([k, v]) => (
            <p key={k} className="text-[9px] text-[#5A6F63]">
              <span className="font-bold">{k.replace(/_/g, " ")}:</span> {String(v)}
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
    </div>
  );
}

// ── Conditions strip ──────────────────────────────────────────────────────────
function ConditionsStrip({ weather, sensor }) {
  if (!weather && !sensor) return null;

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {weather?.temperature_c != null && (
        <CondTile
          icon="sun"
          label="Temperature"
          value={fmt(weather.temperature_c, "°C")}
          note="Current"
        />
      )}
      {weather?.humidity_pct != null && (
        <CondTile
          icon="drop"
          label="Humidity"
          value={fmt(weather.humidity_pct, "%")}
          note="Current"
        />
      )}
      {weather?.forecast_rain_7d_mm != null && (
        <CondTile
          icon="drop"
          label="7-day forecast rain"
          value={fmt(weather.forecast_rain_7d_mm, " mm")}
          note="Not confirmed"
          warn
        />
      )}
      {sensor?.soil_moisture != null && (
        <CondTile
          icon="soil"
          label="Soil moisture"
          value={fmt(sensor.soil_moisture, "%")}
          note={sensor.is_demo ? "Simulated" : "Sensor"}
          demo={sensor.is_demo}
        />
      )}
      {sensor?.soil_temperature != null && (
        <CondTile
          icon="soil"
          label="Soil temp"
          value={fmt(sensor.soil_temperature, "°C")}
          note={sensor.is_demo ? "Simulated" : "Sensor"}
          demo={sensor.is_demo}
        />
      )}
    </div>
  );
}

function CondTile({ icon, label, value, note, warn = false, demo = false }) {
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
      <p className={`text-[18px] font-extrabold tracking-tight ${warn ? "text-[#D99A2B]" : "text-[#1D3A2B]"}`}>
        {value}
      </p>
      <p className={`text-[8px] mt-0.5 ${demo ? "text-[#D99A2B]" : "text-[#9AA79F]"}`}>
        {demo ? "Demo / simulated" : note}
      </p>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function FarmActionPlan({ openModule, isDemo = false }) {
  const url = isDemo ? "/api/demo/plan" : "/api/dashboard/plan";
  const { data, loading, error, refetch } = useApi(
    isDemo ? null : "/api/dashboard/plan"
  );

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="h-5 w-48 animate-pulse rounded-full bg-[#E8F0EB]" />
        {[1, 2].map((n) => (
          <div key={n} className="h-24 animate-pulse rounded-[20px] bg-[#E8F0EB]" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-[20px] bg-[#FCE9E5] p-4">
        <p className="text-[11px] font-bold text-[#9D4C3E]">
          Could not load action plan.{" "}
          <button onClick={refetch} className="underline">
            Retry
          </button>
        </p>
      </div>
    );
  }

  if (!data) return null;

  const actions = data.actions ?? [];
  const topActions = actions.slice(0, 5); // show top 5 on home screen
  const hasMore = actions.length > 5;

  return (
    <div className="space-y-3">
      {/* Summary badge */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[11px] font-bold text-[#5D7B6B] uppercase tracking-[.08em]">
            Today's action plan
          </p>
          <p className="text-[12px] font-semibold text-[#3A5A4A] mt-0.5">
            {data.summary}
          </p>
        </div>
        {data.critical_count > 0 && (
          <span className="rounded-full bg-[#E8493B] px-3 py-1 text-[10px] font-extrabold text-white">
            {data.critical_count} critical
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
            No recommendations yet
          </p>
          <p className="mt-1.5 text-[10px] text-[#7B8C82]">
            Add a farm with a location, then connect a sensor or run a
            prediction to get personalised advice.
          </p>
          <button
            onClick={() => openModule?.("farm-management")}
            className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-[#216B45] px-4 py-2 text-[11px] font-bold text-white"
          >
            <ModuleIcon name="farm" size={14} />
            Add a farm
          </button>
        </div>
      )}

      {/* Action cards */}
      {topActions.map((action, i) => (
        <ActionCard key={`${action.category}-${i}`} action={action} />
      ))}

      {hasMore && (
        <button
          onClick={() => openModule?.("advice")}
          className="w-full rounded-[20px] border border-[#DDE6DF] bg-white/60 py-3 text-[11px] font-bold text-[#216B45] hover:bg-white transition"
        >
          View {actions.length - 5} more recommendations →
        </button>
      )}

      {data.generated_at && (
        <p className="text-[9px] text-[#9AA79F] text-right">
          Plan generated: {new Date(data.generated_at).toLocaleTimeString("en-IN", {
            hour: "2-digit",
            minute: "2-digit",
          })}
          {data.data_inputs?.sensor_available === false && " · No sensor data"}
          {data.data_inputs?.weather_available === false && " · No weather"}
        </p>
      )}
    </div>
  );
}
