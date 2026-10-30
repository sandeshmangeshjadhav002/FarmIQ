import { useMemo, useState } from "react";

import { moduleCatalog } from "@/data/modules";
import { apiPost } from "@/lib/apiClient";
import useApi from "@/hooks/useApi";
import ModuleIcon from "./ModuleIcon";
import WeatherAssist from "./WeatherAssist";
import PredictionExplanation from "./PredictionExplanation";
import { DemoBadge, Field, ModuleButton, SelectField } from "./ModuleShared";

/**
 * Live prediction module for the four ML-backed modules:
 * crop-recommendation, fertilizer, irrigation, yield.
 *
 * Features layered on the original form:
 *   1. Weather auto-fill (temperature/humidity/accumulated rainfall) — optional,
 *      and every auto-filled value stays editable.
 *   2. Input validation against the model's real supported + training ranges
 *      (fetched from GET /api/predictions/schema/<domain>). Invalid values block
 *      the request; unusual-but-valid values warn but still run. The backend
 *      re-validates and returns structured 422 errors, which are shown too.
 *   3. Top-3 crop recommendations, using the model's own probability output and
 *      labelling the score type honestly.
 *
 * @param {string}   props.moduleKey - One of the four ML module keys.
 * @param {Function} props.onAsk     - Navigate to the chat/assistant screen.
 */
export default function MlModule({ moduleKey, onAsk }) {
  const config = DOMAIN_CONFIG[moduleKey];
  const info = moduleCatalog.find((item) => item.key === moduleKey);

  const [values, setValues] = useState(() =>
    Object.fromEntries((config?.fields ?? []).map((f) => [f.key, f.default])),
  );
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  // The exact inputs that produced `result`, kept so the explanation describes
  // the prediction that was actually made — not edits made afterwards.
  const [resultInput, setResultInput] = useState(null);
  const [error, setError] = useState(null);
  const [serverIssues, setServerIssues] = useState(null); // { errors, warnings, advisory }

  // Real ranges from the backend (training-derived). Failure is non-fatal: the
  // form still submits and the backend enforces the same rules.
  const { data: schema } = useApi(
    config ? `/api/predictions/schema/${config.domain}` : null,
  );

  // The most recent farm, so the weather panel can offer a one-tap location
  // from the farm's own saved coordinates. Requires auth; when that call fails
  // (signed out, or no farms) this stays empty and the weather panel simply
  // falls back to the phone position / typed place name.
  const { data: farmsData } = useApi("/api/farms");
  const farm = farmsData?.items?.[0] ?? null;

  const liveIssues = useMemo(
    () => evaluateLocally(config, schema, values),
    [config, schema, values],
  );

  if (!config) return null;

  const setField = (key, value) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleAutofill = (applied) => {
    setValues((prev) => ({ ...prev, ...applied }));
  };

  const handlePredict = async () => {
    if (liveIssues.invalid.length > 0) {
      setServerIssues(null);
      setError("Fix the highlighted fields before running the prediction.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setServerIssues(null);
    try {
      const payload = {};
      for (const f of config.fields) {
        payload[f.key] =
          f.type === "number" ? Number(values[f.key]) : values[f.key];
      }
      const data = await apiPost(config.endpoint, payload);
      setResultInput(payload);
      setResult(data);
    } catch (err) {
      if (err.status === 422 && err.data?.errors) {
        setServerIssues({
          errors: err.data.errors ?? [],
          warnings: err.data.warnings ?? [],
          advisory: err.data.advisory ?? [],
        });
        setError(err.message || "Some inputs failed validation.");
      } else if (err.status === 501) {
        setError(
          "This prediction isn't available yet. Please try again later.",
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

  const invalidByField = Object.fromEntries(
    liveIssues.invalid.map((i) => [i.field, i]),
  );
  const unusualByField = Object.fromEntries(
    liveIssues.unusual.map((i) => [i.field, i]),
  );
  const weatherMap = WEATHER_MAP[moduleKey] ?? {};

  return (
    <div className="space-y-4">
      <DemoBadge status="Live prediction" />

      {/* ── Weather auto-fill (optional) ───────────────────────────── */}
      {Object.keys(weatherMap).length > 0 && (
        <WeatherAssist
          fieldMap={weatherMap}
          onAutofill={handleAutofill}
          farm={farm}
        />
      )}

      {/* ── Input form ─────────────────────────────────────────────── */}
      <section className="space-y-3 rounded-[22px] border border-[#DCE6DF] bg-white p-4">
        <div className="flex items-center gap-2">
          <span
            className={`grid h-8 w-8 place-items-center rounded-xl ${info?.color}`}
          >
            <ModuleIcon name={info?.icon} size={16} />
          </span>
          <h2 className="text-[14px] font-extrabold text-[#213D2F]">
            {config.label} prediction inputs
          </h2>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {config.fields.map((f) => (
            <div key={f.key} className="space-y-1">
              {f.type === "select" ? (
                <SelectField
                  label={f.label}
                  value={values[f.key]}
                  onChange={(v) => setField(f.key, v)}
                  options={f.options}
                />
              ) : (
                <Field
                  label={f.label}
                  type={f.type}
                  value={values[f.key]}
                  onChange={(v) => setField(f.key, v)}
                  placeholder={String(f.default)}
                />
              )}
              <FieldHint
                invalid={invalidByField[f.key]}
                unusual={unusualByField[f.key]}
                spec={schema?.fields?.find((s) => s.field === f.key)}
              />
            </div>
          ))}
        </div>

        <div className="flex gap-2">
          <ModuleButton
            onClick={handlePredict}
            disabled={loading || liveIssues.invalid.length > 0}
          >
            <ModuleIcon name={loading ? "sparkles" : "check"} size={16} />
            {loading ? "Predicting…" : "Get prediction"}
          </ModuleButton>
          <ModuleButton secondary onClick={() => onAsk?.()}>
            Ask FarmIQ
          </ModuleButton>
        </div>

        {liveIssues.invalid.length > 0 && (
          <p className="rounded-xl bg-[#FCE9E5] p-3 text-[10px] font-semibold leading-5 text-[#9D4C3E]">
            {liveIssues.invalid.length} field
            {liveIssues.invalid.length > 1 ? "s need" : " needs"} attention
            before a prediction can run. Values are never changed for you.
          </p>
        )}
        {liveIssues.invalid.length === 0 && liveIssues.unusual.length > 0 && (
          <p className="rounded-xl bg-[#FFF5DE] p-3 text-[10px] font-semibold leading-5 text-[#8A6D2B]">
            {liveIssues.unusual.length} value
            {liveIssues.unusual.length > 1 ? "s are" : " is"} outside the normal
            range for this crop. The prediction will still run.
          </p>
        )}
      </section>

      {/* ── Errors (client or server) ──────────────────────────────── */}
      {error && (
        <section className="rounded-2xl bg-[#FCE9E5] p-4 text-[11px] font-semibold leading-5 text-[#9D4C3E]">
          {error}
        </section>
      )}
      {serverIssues?.errors?.length > 0 && (
        <section className="space-y-1 rounded-2xl bg-[#FCE9E5] p-4">
          <p className="text-[10px] font-extrabold uppercase tracking-[.06em] text-[#9D4C3E]">
            Please fix these
          </p>
          {serverIssues.errors.map((e, i) => (
            <p
              key={`${e.field}-${i}`}
              className="text-[10px] leading-5 text-[#9D4C3E]"
            >
              • {e.message || `${e.label ?? e.field}: ${e.kind}`}
            </p>
          ))}
        </section>
      )}

      {/* ── Result ─────────────────────────────────────────────────── */}
      {result && (
        <section className="space-y-3 rounded-[22px] border border-[#CDEBDA] bg-[#EAF6EF] p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-[14px] font-extrabold text-[#1D4A33]">
              Prediction
            </h3>
            <span className="rounded-full bg-white px-2.5 py-1 text-[9px] font-extrabold uppercase tracking-[.06em] text-[#216B45]">
              {result.source === "baseline"
                ? "General estimate"
                : "Model estimate"}
            </span>
          </div>
          <p className="text-[26px] font-extrabold tracking-[-.03em] text-[#17392A]">
            {result.label ?? result.prediction}
            {moduleKey === "yield" ? " t/ha" : ""}
          </p>

          {/* Top-3 recommendations (crop). Falls back to details.top if present. */}
          <Recommendations result={result} />

          {result.warnings?.length > 0 && (
            <ul className="space-y-1 rounded-xl bg-[#FFF5DE] p-3">
              {result.warnings.map((w, i) => (
                <li key={i} className="text-[10px] leading-5 text-[#8A6D2B]">
                  • {w}
                </li>
              ))}
            </ul>
          )}
          {result.advisory && (
            <p className="text-[9px] leading-5 text-[#5C7A67]">
              {result.advisory}
            </p>
          )}
        </section>
      )}

      {/* ── Plain-language explanation (AI; never blocks the result) ── */}
      {result && (
        <PredictionExplanation
          farmName={farm?.name}
          input={resultInput}
          moduleKey={moduleKey}
          onAsk={() => onAsk?.()}
          result={result}
        />
      )}
    </div>
  );
}

/** Inline per-field validation hint. */
function FieldHint({ invalid, unusual, spec }) {
  if (invalid) {
    return (
      <p className="text-[9px] font-semibold leading-4 text-[#A55243]">
        {invalid.message}
      </p>
    );
  }
  if (unusual) {
    return (
      <p className="text-[9px] font-semibold leading-4 text-[#8A6D2B]">
        {unusual.message}
      </p>
    );
  }
  if (spec?.type === "number" && spec.supported_min != null) {
    return (
      <p className="text-[9px] leading-4 text-[#9AA79F]">
        {fmtNum(spec.supported_min)}–{fmtNum(spec.supported_max)} {spec.unit}
      </p>
    );
  }
  return null;
}

/** Top-3 recommendation cards from the backend's real model output. */
function Recommendations({ result }) {
  const recs = result.recommendations ?? [];
  if (recs.length === 0 && !result.details?.top) return null;

  // Backward-compatible view of the older details.top payload.
  const items =
    recs.length > 0
      ? recs
      : result.details.top.map((t, i) => ({
          rank: i + 1,
          crop: t.crop,
          score: t.probability,
          score_type: "probability",
        }));

  return (
    <div className="space-y-2">
      <h4 className="text-[11px] font-extrabold text-[#1D4A33]">
        Top {items.length} crop recommendation{items.length > 1 ? "s" : ""}
      </h4>
      <div className="grid grid-cols-3 gap-2">
        {items.map((r) => (
          <div
            key={`${r.rank}-${r.crop}`}
            className="rounded-2xl border border-[#CDEBDA] bg-white p-3"
          >
            <div className="flex items-center justify-between">
              <span className="grid h-5 w-5 place-items-center rounded-full bg-[#E8F3EA] text-[9px] font-extrabold text-[#216B45]">
                {r.rank}
              </span>
              <span className="text-[8px] font-bold uppercase tracking-[.06em] text-[#8A998F]">
                {r.crop === items[0].crop ? "best match" : ""}
              </span>
            </div>
            <p className="mt-2 text-[13px] font-extrabold capitalize leading-tight text-[#17392A]">
              {r.crop}
            </p>
            <p className="mt-1 text-[15px] font-extrabold text-[#216B45]">
              {formatScore(r)}
            </p>
          </div>
        ))}
      </div>
      {items.length < 3 && (
        <p className="text-[9px] leading-4 text-[#8A6D2B]">
          Only {items.length} recommendation{items.length > 1 ? "s" : ""}{" "}
          available.
        </p>
      )}
      <p className="text-[9px] leading-4 text-[#5C7A67]">
        Scores rank the options — they are not a guarantee of success in your
        field.
      </p>
    </div>
  );
}

function formatScore(r) {
  if (r.score_type === "probability" && typeof r.score === "number") {
    return `${(r.score * 100).toFixed(1)}%`;
  }
  return typeof r.score === "number" ? r.score.toFixed(4) : String(r.score);
}

function fmtNum(value) {
  if (typeof value !== "number") return value;
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/**
 * Client-side mirror of the backend's validation, so problems show up before
 * the request is sent. Uses the real supported + training ranges from
 * GET /api/predictions/schema/<domain>; never modifies the user's values.
 */
function evaluateLocally(config, schema, values) {
  const invalid = [];
  const unusual = [];
  if (!config || !schema?.fields) return { invalid, unusual };

  const specByField = Object.fromEntries(
    schema.fields.map((s) => [s.field, s]),
  );

  for (const f of config.fields) {
    const spec = specByField[f.key];
    const raw = values[f.key];

    if (spec?.type === "category") {
      const options = spec.options ?? [];
      if (raw == null || String(raw).trim() === "") {
        invalid.push({
          field: f.key,
          label: f.label,
          message: `${f.label} is required.`,
        });
      } else if (
        options.length > 0 &&
        !options.some(
          (o) => o.toLowerCase() === String(raw).trim().toLowerCase(),
        )
      ) {
        unusual.push({
          field: f.key,
          label: f.label,
          message:
            `"${raw}" does not appear in the training data for ${f.label}; the model will treat ` +
            "it as an unknown category.",
        });
      }
      continue;
    }

    if (spec?.type !== "number") continue;

    const num = Number(raw);
    if (raw === "" || raw == null || Number.isNaN(num)) {
      invalid.push({
        field: f.key,
        label: f.label,
        message: `${f.label} must be a number.`,
      });
      continue;
    }
    if (spec.supported_min != null && num < spec.supported_min) {
      invalid.push({
        field: f.key,
        label: f.label,
        message: `${f.label} must be at least ${fmtNum(spec.supported_min)} ${
          spec.unit
        }.`,
      });
      continue;
    }
    if (spec.supported_max != null && num > spec.supported_max) {
      invalid.push({
        field: f.key,
        label: f.label,
        message: `${f.label} must be at most ${fmtNum(spec.supported_max)} ${
          spec.unit
        }.`,
      });
      continue;
    }
    const below = spec.training_min != null && num < spec.training_min;
    const above = spec.training_max != null && num > spec.training_max;
    if (below || above) {
      unusual.push({
        field: f.key,
        label: f.label,
        message:
          `${f.label} = ${fmtNum(num)} ${
            spec.unit
          } is valid but outside the training range ` +
          `(${fmtNum(spec.training_min)}–${fmtNum(spec.training_max)} ${
            spec.unit
          }).`,
      });
    }
  }
  return { invalid, unusual };
}

// Per-domain field configs. Keys match the FastAPI request schemas exactly
// (see backend/app/schemas.py) and preserve the ML feature order.
const DOMAIN_CONFIG = {
  "crop-recommendation": {
    domain: "crop",
    endpoint: "/api/predictions/crop",
    label: "Crop",
    fields: [
      { key: "N", label: "Nitrogen (N) kg/ha", type: "number", default: 90 },
      { key: "P", label: "Phosphorus (P) kg/ha", type: "number", default: 40 },
      { key: "K", label: "Potassium (K) kg/ha", type: "number", default: 40 },
      {
        key: "temperature",
        label: "Temperature °C",
        type: "number",
        default: 25,
      },
      { key: "humidity", label: "Humidity %", type: "number", default: 80 },
      { key: "ph", label: "Soil pH", type: "number", default: 6.5 },
      { key: "rainfall", label: "Rainfall mm", type: "number", default: 200 },
    ],
  },
  fertilizer: {
    domain: "fertilizer",
    endpoint: "/api/predictions/fertilizer",
    label: "Fertilizer",
    fields: [
      {
        key: "temparature",
        label: "Temperature °C",
        type: "number",
        default: 26,
      },
      { key: "humidity", label: "Humidity %", type: "number", default: 60 },
      {
        key: "moisture",
        label: "Soil moisture %",
        type: "number",
        default: 40,
      },
      { key: "nitrogen", label: "Nitrogen kg/ha", type: "number", default: 80 },
      {
        key: "potassium",
        label: "Potassium kg/ha",
        type: "number",
        default: 20,
      },
      {
        key: "phosphorous",
        label: "Phosphorous kg/ha",
        type: "number",
        default: 30,
      },
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
        options: [
          "Wheat",
          "Maize",
          "Paddy",
          "Cotton",
          "Ground Nuts",
          "Sugarcane",
          "Barley",
          "Oil seeds",
          "Pulses",
          "Millets",
          "Tobacco",
        ],
      },
    ],
  },
  irrigation: {
    domain: "irrigation",
    endpoint: "/api/predictions/irrigation",
    label: "Irrigation",
    fields: [
      {
        key: "soil_moisture",
        label: "Soil moisture (raw 0–2000)",
        type: "number",
        default: 20,
      },
      {
        key: "soil_temperature",
        label: "Soil temperature °C",
        type: "number",
        default: 25,
      },
      {
        key: "temperature",
        label: "Air temperature °C",
        type: "number",
        default: 28,
      },
      { key: "humidity", label: "Humidity %", type: "number", default: 65 },
      {
        key: "crop_days",
        label: "Days since planting",
        type: "number",
        default: 10,
      },
      {
        key: "crop_type",
        label: "Crop type",
        type: "select",
        default: "Paddy",
        options: ["Paddy", "Ground Nuts"],
      },
    ],
  },
  yield: {
    domain: "yield",
    endpoint: "/api/predictions/yield",
    label: "Yield",
    fields: [
      {
        key: "state_name",
        label: "State",
        type: "text",
        default: "Maharashtra",
      },
      {
        key: "season",
        label: "Season",
        type: "select",
        default: "Kharif",
        options: ["Kharif", "Rabi", "Whole Year", "Summer", "Winter", "Autumn"],
      },
      { key: "crop", label: "Crop", type: "text", default: "Rice" },
      { key: "crop_year", label: "Crop year", type: "number", default: 2018 },
      { key: "area", label: "Area (hectares)", type: "number", default: 1.0 },
      {
        key: "annual_rainfall",
        label: "Annual rainfall mm",
        type: "number",
        default: 1000,
      },
      {
        key: "fertilizer",
        label: "Fertilizer kg",
        type: "number",
        default: 50,
      },
      { key: "pesticide", label: "Pesticide kg", type: "number", default: 5 },
    ],
  },
};

/**
 * Which weather values may auto-fill which form field, per module.
 *
 * Yield is deliberately absent: its `annual_rainfall` input is a *yearly* total,
 * and the weather autofill value is a 30-day accumulation — substituting one for
 * the other would be misleading, so no auto-fill is offered there.
 */
const WEATHER_MAP = {
  "crop-recommendation": {
    temperature: "temperature",
    humidity: "humidity",
    rainfall: "rainfall",
  },
  fertilizer: { temparature: "temperature", humidity: "humidity" },
  irrigation: { temperature: "temperature", humidity: "humidity" },
};
