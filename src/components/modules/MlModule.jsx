import { useState } from "react";

import { moduleCatalog, moduleConfigs } from "@/data/modules";
import { apiPost } from "@/lib/apiClient";
import ModuleIcon from "./ModuleIcon";
import { DemoBadge, Field, ModuleButton, SelectField, MiniChart, Metric } from "./ModuleShared";

/**
 * Live prediction module for the four ML-backed modules:
 * crop-recommendation, fertilizer, irrigation, yield.
 *
 * Renders an input form matching the EXACT feature order expected by the
 * FastAPI /api/predictions/<domain> endpoint, calls it, and shows the result.
 * The existing static demo content (title/detail/metrics/rows) is kept below
 * so the original UI is preserved.
 *
 * @param {string}   props.moduleKey - One of the four ML module keys.
 * @param {Function} props.onAsk     - Navigate to the chat/assistant screen.
 */
export default function MlModule({ moduleKey, onAsk }) {
  const config = DOMAIN_CONFIG[moduleKey];
  const info = moduleCatalog.find((item) => item.key === moduleKey);
  const demo = moduleConfigs[moduleKey] ?? moduleConfigs.reports;

  // Build initial form state from the field defaults.
  const [values, setValues] = useState(() =>
    Object.fromEntries((config?.fields ?? []).map((f) => [f.key, f.default]))
  );
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null); // { prediction, source, label, details }
  const [error, setError] = useState(null);

  if (!config) return null;

  const setField = (key, value) => setValues((prev) => ({ ...prev, [key]: value }));

  const handlePredict = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      // Coerce numeric fields to numbers for the backend.
      const payload = {};
      for (const f of config.fields) {
        payload[f.key] = f.type === "number" ? Number(values[f.key]) : values[f.key];
      }
      const data = await apiPost(config.endpoint, payload);
      setResult(data);
    } catch (err) {
      if (err.status === 501) {
        setError(
          "No trained model for this domain yet. A backend admin must run `python -m ml.train_models`. " +
            (err.message || "")
        );
      } else if (err.status === 401) {
        setError("Your session expired. Please sign in again.");
      } else {
        setError(err.message || "Prediction failed. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <DemoBadge status="Live prediction" />
        <span className="text-[9px] font-semibold text-[#829188]">FastAPI · {config.endpoint}</span>
      </div>

      {/* ── Input form ─────────────────────────────────────────────── */}
      <section className="space-y-3 rounded-[22px] border border-[#DCE6DF] bg-white p-4">
        <div className="flex items-center gap-2">
          <span className={`grid h-8 w-8 place-items-center rounded-xl ${info?.color}`}>
            <ModuleIcon name={info?.icon} size={16} />
          </span>
          <h2 className="text-[14px] font-extrabold text-[#213D2F]">
            {config.label} prediction inputs
          </h2>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {config.fields.map((f) =>
            f.type === "select" ? (
              <SelectField
                key={f.key}
                label={f.label}
                value={values[f.key]}
                onChange={(v) => setField(f.key, v)}
                options={f.options}
              />
            ) : (
              <Field
                key={f.key}
                label={f.label}
                type={f.type}
                value={values[f.key]}
                onChange={(v) => setField(f.key, v)}
                placeholder={String(f.default)}
              />
            )
          )}
        </div>

        <div className="flex gap-2">
          <ModuleButton onClick={handlePredict} disabled={loading}>
            <ModuleIcon name={loading ? "sparkles" : "check"} size={16} />
            {loading ? "Predicting…" : "Get prediction"}
          </ModuleButton>
          <ModuleButton secondary onClick={() => onAsk?.()}>
            Ask FarmIQ
          </ModuleButton>
        </div>
      </section>

      {/* ── Result ─────────────────────────────────────────────────── */}
      {error && (
        <section className="rounded-2xl bg-[#FCE9E5] p-4 text-[11px] font-semibold leading-5 text-[#9D4C3E]">
          {error}
        </section>
      )}
      {result && (
        <section className="rounded-[22px] border border-[#CDEBDA] bg-[#EAF6EF] p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-[14px] font-extrabold text-[#1D4A33]">Prediction</h3>
            <span className="rounded-full bg-white px-2.5 py-1 text-[9px] font-extrabold uppercase tracking-[.06em] text-[#216B45]">
              {result.source === "baseline" ? "Rule-based baseline" : "ML model"}
            </span>
          </div>
          <p className="mt-3 text-[26px] font-extrabold tracking-[-.03em] text-[#17392A]">
            {result.label ?? result.prediction}
            {moduleKey === "yield" ? " t/ha" : ""}
          </p>
          {result.details?.top && (
            <div className="mt-3 space-y-1">
              {result.details.top.map((t) => (
                <div key={t.crop} className="flex justify-between text-[11px] text-[#3C5C49]">
                  <span>{t.crop}</span>
                  <span className="font-bold">{(t.probability * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── Preserved static demo content ──────────────────────────── */}
      {demo && (
        <>
          <div className="grid grid-cols-3 gap-2">
            {demo.metrics.map(([label, value, note]) => (
              <Metric key={label} label={label} value={value} note={note} />
            ))}
          </div>
          <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
            <h2 className="text-[16px] font-extrabold text-[#203C2E]">{demo.title}</h2>
            <p className="mt-1 text-[11px] leading-5 text-[#75867C]">{demo.detail}</p>
            <div className="mt-4">
              <MiniChart />
            </div>
          </section>
          <section className="overflow-hidden rounded-[22px] border border-[#E0E8E2] bg-white">
            {demo.rows.map(([name, value, note], index) => (
              <div
                key={name}
                className={`flex items-center gap-3 p-4 ${index ? "border-t border-[#EDF1EE]" : ""}`}
              >
                <span className="min-w-0 flex-1">
                  <b className="block text-[12px] text-[#294234]">{name}</b>
                  <span className="mt-1 block text-[9px] text-[#84938B]">{note}</span>
                </span>
                <span className="text-right text-[11px] font-extrabold text-[#426653]">{value}</span>
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  );
}

// Per-domain field configs. Keys match the FastAPI request schemas exactly
// (see backend/app/schemas.py) and preserve the ML feature order.
const DOMAIN_CONFIG = {
  "crop-recommendation": {
    endpoint: "/api/predictions/crop",
    label: "Crop",
    fields: [
      { key: "N", label: "Nitrogen (N) kg/ha", type: "number", default: 90 },
      { key: "P", label: "Phosphorus (P) kg/ha", type: "number", default: 40 },
      { key: "K", label: "Potassium (K) kg/ha", type: "number", default: 40 },
      { key: "temperature", label: "Temperature °C", type: "number", default: 25 },
      { key: "humidity", label: "Humidity %", type: "number", default: 80 },
      { key: "ph", label: "Soil pH", type: "number", default: 6.5 },
      { key: "rainfall", label: "Rainfall mm", type: "number", default: 200 },
    ],
  },
  fertilizer: {
    endpoint: "/api/predictions/fertilizer",
    label: "Fertilizer",
    fields: [
      { key: "temparature", label: "Temperature °C", type: "number", default: 26 },
      { key: "humidity", label: "Humidity %", type: "number", default: 60 },
      { key: "moisture", label: "Soil moisture %", type: "number", default: 40 },
      { key: "nitrogen", label: "Nitrogen kg/ha", type: "number", default: 80 },
      { key: "potassium", label: "Potassium kg/ha", type: "number", default: 20 },
      { key: "phosphorous", label: "Phosphorous kg/ha", type: "number", default: 30 },
      {
        key: "soil_type",
        label: "Soil type",
        type: "select",
        default: "Loamy",
        options: ["Sandy", "Loamy", "Black", "Red", "Clayey", "Sandy loam"],
      },
      {
        key: "crop_type",
        label: "Crop type",
        type: "select",
        default: "Wheat",
        options: ["Wheat", "Maize", "Paddy", "Cotton", "Ground Nuts", "Sugarcane", "Barley", "Oil seeds", "Pulses", "Millets", "Tobacco"],
      },
    ],
  },
  irrigation: {
    endpoint: "/api/predictions/irrigation",
    label: "Irrigation",
    fields: [
      { key: "soil_moisture", label: "Soil moisture (raw 0–2000)", type: "number", default: 20 },
      { key: "soil_temperature", label: "Soil temperature °C", type: "number", default: 25 },
      { key: "temperature", label: "Air temperature °C", type: "number", default: 28 },
      { key: "humidity", label: "Humidity %", type: "number", default: 65 },
      { key: "crop_days", label: "Days since planting", type: "number", default: 10 },
      { key: "crop_type", label: "Crop type", type: "select", default: "Paddy", options: ["Paddy", "Ground Nuts"] },
    ],
  },
  yield: {
    endpoint: "/api/predictions/yield",
    label: "Yield",
    fields: [
      { key: "state_name", label: "State", type: "text", default: "Maharashtra" },
      { key: "season", label: "Season", type: "select", default: "Kharif", options: ["Kharif", "Rabi", "Whole Year", "Summer", "Winter", "Autumn"] },
      { key: "crop", label: "Crop", type: "text", default: "Rice" },
      { key: "crop_year", label: "Crop year", type: "number", default: 2018 },
      { key: "area", label: "Area (hectares)", type: "number", default: 1.0 },
      { key: "annual_rainfall", label: "Annual rainfall mm", type: "number", default: 1000 },
      { key: "fertilizer", label: "Fertilizer kg", type: "number", default: 50 },
      { key: "pesticide", label: "Pesticide kg", type: "number", default: 5 },
    ],
  },
};
