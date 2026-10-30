/**
 * Drought Management & Water Conservation Advisor
 *
 * Collects farm, crop, soil, water, and budget information, submits to
 * POST /api/drought/assess, and displays a categorised set of recommendations
 * with urgency levels, cost estimates, and source references.
 *
 * Design rules enforced here:
 * - Forecast rainfall is never presented as confirmed.
 * - Cost figures are shown as estimates with a verification note.
 * - Data gaps are displayed when inputs were missing.
 * - RAG context (if available) is shown as advisory text, clearly labelled.
 */
import { useState } from "react";
import { apiPost } from "@/lib/apiClient";
import ModuleIcon from "./ModuleIcon";
import { Field, ModuleButton } from "./ModuleShared";

// ── Constants ────────────────────────────────────────────────────────────────

const GROWTH_STAGES = [
  "Not yet sown",
  "Germination",
  "Seedling",
  "Vegetative",
  "Tillering",
  "Jointing",
  "Heading",
  "Flowering",
  "Grain Filling",
  "Pod Filling",
  "Boll Formation",
  "Maturity",
  "Harvest",
];

const SOIL_TYPES = [
  "Black (Vertisol)",
  "Red (Alfisol)",
  "Alluvial",
  "Sandy Loam",
  "Loam",
  "Sandy",
  "Clay",
  "Laterite",
  "Saline/Alkaline",
];

const WATER_AVAILABILITY = [
  { value: "none", label: "None — no water source" },
  { value: "limited", label: "Limited — irregular / small supply" },
  { value: "moderate", label: "Moderate — some supply available" },
  { value: "good", label: "Good — regular supply" },
];

const IRRIGATION_TYPES = [
  { value: "none", label: "None (rainfed only)" },
  { value: "canal", label: "Canal / flow irrigation" },
  { value: "borewell", label: "Borewell / tube well" },
  { value: "drip", label: "Drip irrigation" },
  { value: "sprinkler", label: "Sprinkler irrigation" },
  { value: "other", label: "Other" },
];

const SOWING_STATUSES = [
  { value: "not_yet_sown", label: "Not yet sown" },
  { value: "already_sown", label: "Already sown / established" },
  { value: "germination", label: "Germination / emergence" },
  { value: "tillering", label: "Tillering / vegetative" },
];

const AREA_UNITS = ["acres", "hectares", "guntha", "bigha"];

const URGENCY_CONFIG = {
  critical: {
    bg: "bg-[#FCE9E5]",
    border: "border-[#E8B4AE]",
    text: "text-[#9D3E2E]",
    badge: "bg-[#E8493B] text-white",
    dot: "bg-[#E8493B]",
    label: "Critical",
  },
  high: {
    bg: "bg-[#FFF5DE]",
    border: "border-[#F0D090]",
    text: "text-[#8A6D2B]",
    badge: "bg-[#D99A2B] text-white",
    dot: "bg-[#D99A2B]",
    label: "High",
  },
  moderate: {
    bg: "bg-[#E8EEF8]",
    border: "border-[#C0CDE8]",
    text: "text-[#3F5A90]",
    badge: "bg-[#4F6590] text-white",
    dot: "bg-[#4F6590]",
    label: "Moderate",
  },
  low: {
    bg: "bg-[#EDF1EE]",
    border: "border-[#CDD8D1]",
    text: "text-[#52665B]",
    badge: "bg-[#7A9585] text-white",
    dot: "bg-[#7A9585]",
    label: "Low",
  },
};

const SEVERITY_CONFIG = {
  extreme: { bg: "bg-[#FCE9E5]", text: "text-[#9D3E2E]", dot: "bg-[#E8493B]" },
  severe: { bg: "bg-[#FFF0DE]", text: "text-[#9A5E1A]", dot: "bg-[#E07B28]" },
  moderate: { bg: "bg-[#FFF5DE]", text: "text-[#8A6D2B]", dot: "bg-[#D99A2B]" },
  mild: { bg: "bg-[#E8EEF8]", text: "text-[#3F5A90]", dot: "bg-[#4F6590]" },
  none: { bg: "bg-[#EAF6EF]", text: "text-[#216B45]", dot: "bg-[#3F9C6A]" },
};

const EMPTY_FORM = {
  location: "",
  crop: "",
  growth_stage: "Vegetative",
  soil_type: "",
  area_value: "",
  area_unit: "acres",
  sowing_date: "",
  sowing_status: "already_sown",
  recent_rainfall_mm: "",
  water_availability: "limited",
  irrigation_type: "none",
  irrigation_hours_available: "",
  budget_inr: "",
  fetch_weather: true,
  save: false,
};

// ── Main Component ───────────────────────────────────────────────────────────

export default function DroughtAdvisor() {
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [savedId, setSavedId] = useState(null);

  const set = (k, v) => setForm((prev) => ({ ...prev, [k]: v }));

  const validate = () => {
    const errs = {};
    if (!form.location.trim()) errs.location = "Enter a location.";
    if (!form.crop.trim()) errs.crop = "Enter the crop name.";
    if (!form.growth_stage) errs.growth_stage = "Select a growth stage.";
    if (!form.soil_type) errs.soil_type = "Select a soil type.";
    if (!form.area_value || Number(form.area_value) <= 0)
      errs.area_value = "Enter a valid farm size greater than zero.";
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = async () => {
    if (busy) return;
    if (!validate()) {
      setSubmitError(null);
      return;
    }
    setBusy(true);
    setSubmitError(null);
    setResult(null);

    const payload = {
      location: form.location.trim(),
      crop: form.crop.trim(),
      growth_stage: form.growth_stage,
      soil_type: form.soil_type,
      area_value: Number(form.area_value),
      area_unit: form.area_unit,
      sowing_status: form.sowing_status,
      sowing_date: form.sowing_date.trim() || null,
      recent_rainfall_mm:
        form.recent_rainfall_mm !== "" ? Number(form.recent_rainfall_mm) : null,
      water_availability: form.water_availability,
      irrigation_type: form.irrigation_type,
      irrigation_hours_available:
        form.irrigation_hours_available !== ""
          ? Number(form.irrigation_hours_available)
          : null,
      budget_inr: form.budget_inr !== "" ? Number(form.budget_inr) : null,
      fetch_weather: form.fetch_weather,
      save: form.save,
    };

    try {
      const res = await apiPost("/api/drought/assess", payload);
      setResult(res);
      if (res.saved_assessment_id) setSavedId(res.saved_assessment_id);
    } catch (err) {
      setSubmitError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* ── Input Form ────────────────────────────────────────────────────── */}
      <section className="rounded-[22px] border border-white/40 bg-white/50 p-4 backdrop-blur-md shadow-sm">
        <div className="flex items-center gap-2 mb-3">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-[#E5F3F7] text-[#28778A]">
            <ModuleIcon name="drought" size={16} />
          </span>
          <h2 className="text-[13px] font-extrabold text-[#1A3C4A]">
            Tell us about your farm and water situation
          </h2>
        </div>

        <div className="space-y-3">
          <Field
            label="Farm location *"
            value={form.location}
            onChange={(v) => set("location", v)}
            placeholder="Village, district, state (e.g. Solapur, Maharashtra)"
          />
          {fieldErrors.location && <FieldError text={fieldErrors.location} />}

          <Field
            label="Crop *"
            value={form.crop}
            onChange={(v) => set("crop", v)}
            placeholder="e.g. Soybean, Cotton, Jowar, Tur"
          />
          {fieldErrors.crop && <FieldError text={fieldErrors.crop} />}

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">
                Growth stage *
              </span>
              <select
                value={form.growth_stage}
                onChange={(e) => set("growth_stage", e.target.value)}
                className="h-11 w-full rounded-xl border border-[#DDE6DF] bg-white px-3 text-[12px] font-semibold text-[#203B2D] outline-none focus:border-[#5A9AB0]"
              >
                {GROWTH_STAGES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">
                Sowing status
              </span>
              <select
                value={form.sowing_status}
                onChange={(e) => set("sowing_status", e.target.value)}
                className="h-11 w-full rounded-xl border border-[#DDE6DF] bg-white px-3 text-[12px] font-semibold text-[#203B2D] outline-none"
              >
                {SOWING_STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="block">
            <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">
              Soil type *
            </span>
            <select
              value={form.soil_type}
              onChange={(e) => set("soil_type", e.target.value)}
              className="h-11 w-full rounded-xl border border-[#DDE6DF] bg-white px-3 text-[12px] font-semibold text-[#203B2D] outline-none"
            >
              <option value="">Select soil type</option>
              {SOIL_TYPES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          {fieldErrors.soil_type && <FieldError text={fieldErrors.soil_type} />}

          <div className="grid grid-cols-2 gap-2">
            <Field
              label="Farm size *"
              type="number"
              value={form.area_value}
              onChange={(v) => set("area_value", v)}
              placeholder="e.g. 2.5"
            />
            <label className="block">
              <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">
                Unit
              </span>
              <select
                value={form.area_unit}
                onChange={(e) => set("area_unit", e.target.value)}
                className="h-11 w-full rounded-xl border border-[#DDE6DF] bg-white px-3 text-[12px] font-semibold text-[#203B2D] outline-none"
              >
                {AREA_UNITS.map((u) => (
                  <option key={u}>{u}</option>
                ))}
              </select>
            </label>
          </div>
          {fieldErrors.area_value && (
            <FieldError text={fieldErrors.area_value} />
          )}
        </div>

        {/* Water situation */}
        <div className="mt-4 pt-4 border-t border-[#E2EDE5]">
          <p className="text-[10px] font-bold uppercase tracking-[.08em] text-[#28778A] mb-3">
            Water situation
          </p>
          <div className="space-y-3">
            <Field
              label="Recent rainfall (mm) — past 2–3 weeks (farmer-observed)"
              type="number"
              value={form.recent_rainfall_mm}
              onChange={(v) => set("recent_rainfall_mm", v)}
              placeholder="e.g. 25  (leave blank if unknown)"
            />

            <label className="block">
              <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">
                Water availability
              </span>
              <select
                value={form.water_availability}
                onChange={(e) => set("water_availability", e.target.value)}
                className="h-11 w-full rounded-xl border border-[#DDE6DF] bg-white px-3 text-[12px] font-semibold text-[#203B2D] outline-none"
              >
                {WATER_AVAILABILITY.map((w) => (
                  <option key={w.value} value={w.value}>
                    {w.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">
                  Irrigation type
                </span>
                <select
                  value={form.irrigation_type}
                  onChange={(e) => set("irrigation_type", e.target.value)}
                  className="h-11 w-full rounded-xl border border-[#DDE6DF] bg-white px-3 text-[12px] font-semibold text-[#203B2D] outline-none"
                >
                  {IRRIGATION_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>

              {form.irrigation_type !== "none" && (
                <Field
                  label="Irrig. hours/day (approx)"
                  type="number"
                  value={form.irrigation_hours_available}
                  onChange={(v) => set("irrigation_hours_available", v)}
                  placeholder="e.g. 4"
                />
              )}
            </div>
          </div>
        </div>

        {/* Budget + options */}
        <div className="mt-4 pt-4 border-t border-[#E2EDE5]">
          <p className="text-[10px] font-bold uppercase tracking-[.08em] text-[#28778A] mb-3">
            Budget & options
          </p>
          <Field
            label="Available budget (₹) — optional"
            type="number"
            value={form.budget_inr}
            onChange={(v) => set("budget_inr", v)}
            placeholder="e.g. 5000"
          />
          <p className="mt-1 text-[9px] text-[#84938B] leading-4">
            Leave blank to skip.
          </p>

          <div className="mt-3 space-y-2">
            <CheckRow
              label="Fetch current weather forecast for my location"
              sublabel="Forecast is advisory only."
              checked={form.fetch_weather}
              onChange={(v) => set("fetch_weather", v)}
            />
            <CheckRow
              label="Save this assessment to my account"
              checked={form.save}
              onChange={(v) => set("save", v)}
            />
          </div>
        </div>

        {submitError && (
          <div
            role="alert"
            className="mt-3 rounded-2xl bg-[#FCE9E5] p-3 text-[10px] font-semibold leading-5 text-[#9D4C3E]"
          >
            {submitError.message || "Something went wrong. Please try again."}
          </div>
        )}

        {savedId && (
          <p className="mt-3 rounded-2xl bg-[#EAF6EF] p-3 text-[10px] font-semibold text-[#216B45]">
            Assessment saved to your account.
          </p>
        )}

        <div className="mt-4">
          <ModuleButton disabled={busy} onClick={handleSubmit}>
            {busy ? "Assessing…" : "Get Drought Management Advice"}
          </ModuleButton>
        </div>
      </section>

      {/* ── Results ───────────────────────────────────────────────────────── */}
      {result && <ResultView data={result} />}
    </div>
  );
}

// ── Result View ──────────────────────────────────────────────────────────────

function ResultView({ data }) {
  const sev = SEVERITY_CONFIG[data.drought_severity] ?? SEVERITY_CONFIG.mild;
  const [expandedCat, setExpandedCat] = useState(null);

  return (
    <div className="space-y-4">
      {/* Severity header */}
      <section
        className={`rounded-[22px] border p-4 ${sev.bg} border-white/60`}
      >
        <div className="flex items-center gap-2 mb-2">
          <span className={`h-2.5 w-2.5 rounded-full ${sev.dot}`} />
          <span
            className={`text-[10px] font-extrabold uppercase tracking-[.1em] ${sev.text}`}
          >
            {data.drought_severity === "none"
              ? "No drought stress"
              : `${cap(data.drought_severity)} drought stress`}
          </span>
        </div>
        <p className={`text-[12px] font-bold leading-5 ${sev.text}`}>
          {data.crop} · {data.growth_stage} · {data.area_value} {data.area_unit}
        </p>
        <p className={`mt-1 text-[10px] leading-5 ${sev.text}`}>
          {data.drought_severity_reason}
        </p>
        <p className="mt-1.5 text-[9px] text-[#6B7C72]">
          Location: {data.location}
        </p>
      </section>

      {/* Weather snapshot */}
      {data.weather && <WeatherCard weather={data.weather} />}

      {/* Data gaps */}
      {data.data_gaps?.length > 0 && (
        <section className="rounded-[22px] border border-[#E0D8B0] bg-[#FFFBEA] p-4">
          <p className="text-[10px] font-extrabold text-[#8A7830] mb-2">
            ℹ Missing inputs — general guidance applied
          </p>
          <ul className="space-y-1">
            {data.data_gaps.map((g, i) => (
              <li key={i} className="text-[10px] leading-5 text-[#7A6A28]">
                · {g}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Category summary strip */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {data.categories?.map((cat) => {
          const u = URGENCY_CONFIG[cat.urgency] ?? URGENCY_CONFIG.low;
          return (
            <button
              key={cat.category}
              onClick={() =>
                setExpandedCat(
                  expandedCat === cat.category ? null : cat.category,
                )
              }
              className={`rounded-2xl border p-3 text-left transition active:scale-[.98] ${u.bg} ${u.border}`}
            >
              <span
                className={`inline-block rounded-full px-2 py-0.5 text-[8px] font-extrabold uppercase ${u.badge} mb-2`}
              >
                {u.label}
              </span>
              <p className={`text-[10px] font-extrabold ${u.text}`}>
                {cat.category_label}
              </p>
              <p className={`text-[9px] mt-0.5 ${u.text} opacity-70`}>
                {cat.items?.length ?? 0} recommendation
                {cat.items?.length !== 1 ? "s" : ""}
              </p>
            </button>
          );
        })}
      </div>

      {/* Expanded category */}
      {expandedCat && (
        <CategoryDetail
          category={data.categories?.find((c) => c.category === expandedCat)}
          onClose={() => setExpandedCat(null)}
        />
      )}

      {/* RAG advisory */}
      {data.rag_context && data.rag_status !== "unavailable" && (
        <section className="rounded-[22px] border border-[#D6E4D8] bg-[#F7FAF8] p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="grid h-6 w-6 place-items-center rounded-lg bg-[#E6F3E8] text-[#216B45]">
              <ModuleIcon name="book" size={13} />
            </span>
            <h3 className="text-[11px] font-extrabold text-[#213D2F]">
              Based on agricultural guidance
            </h3>
            <span className="ml-auto rounded-full bg-[#EDF5F0] px-2 py-0.5 text-[8px] font-extrabold text-[#52765E]">
              Advisory only
            </span>
          </div>
          <p className="text-[10px] leading-5 text-[#4C6355] whitespace-pre-wrap">
            {data.rag_context}
          </p>
          {data.rag_sources?.length > 0 && (
            <div className="mt-3 space-y-1">
              {data.rag_sources.map((s, i) => (
                <p key={i} className="text-[9px] text-[#7A8C82]">
                  [{i + 1}] {s.source}
                  {s.page ? `, p.${s.page}` : ""}
                </p>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Disclaimers */}
      <Disclaimers items={data.disclaimers} />
    </div>
  );
}

// ── Category Detail (expanded view) ─────────────────────────────────────────

function CategoryDetail({ category, onClose }) {
  if (!category) return null;
  const u = URGENCY_CONFIG[category.urgency] ?? URGENCY_CONFIG.low;
  return (
    <section
      className={`rounded-[22px] border p-4 space-y-3 ${u.bg} ${u.border}`}
    >
      <div className="flex items-center justify-between">
        <h3 className={`text-[13px] font-extrabold ${u.text}`}>
          {category.category_label}
        </h3>
        <button
          onClick={onClose}
          className="text-[10px] font-bold text-[#7A8C82] hover:underline"
        >
          Close
        </button>
      </div>
      {category.items?.map((item, i) => (
        <RecommendationCard key={i} item={item} />
      ))}
    </section>
  );
}

function RecommendationCard({ item }) {
  const [open, setOpen] = useState(false);
  const u = URGENCY_CONFIG[item.urgency] ?? URGENCY_CONFIG.low;

  return (
    <div className="rounded-2xl border border-white/60 bg-white p-3 space-y-2">
      <div className="flex items-start gap-2">
        <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${u.dot}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`rounded-full px-2 py-0.5 text-[8px] font-extrabold uppercase ${u.badge}`}
            >
              {u.label}
            </span>
          </div>
          <p className="mt-1 text-[11px] font-bold leading-5 text-[#1A2F22]">
            {item.action}
          </p>
          <p className="mt-0.5 text-[10px] leading-5 text-[#5A6F63]">
            {item.reason}
          </p>
        </div>
      </div>

      {/* Details toggle */}
      <button
        onClick={() => setOpen(!open)}
        className="text-[9px] font-bold text-[#28778A] hover:underline"
      >
        {open ? "Hide details ▲" : "Show details ▼"}
      </button>

      {open && (
        <div className="space-y-2 pt-1">
          {item.materials?.length > 0 && (
            <DetailRow label="Materials needed">
              <ul className="space-y-0.5">
                {item.materials.map((m, i) => (
                  <li key={i} className="text-[10px] text-[#5A6F63]">
                    · {m}
                  </li>
                ))}
              </ul>
            </DetailRow>
          )}

          {item.estimated_cost_inr && (
            <DetailRow label="Estimated cost">
              <p className="text-[10px] text-[#5A6F63]">
                {item.estimated_cost_inr}
                <span className="ml-1 text-[9px] text-[#917C3A]">
                  (estimate — verify locally)
                </span>
              </p>
            </DetailRow>
          )}

          {item.expected_benefits?.length > 0 && (
            <DetailRow label="Expected benefits">
              <ul className="space-y-0.5">
                {item.expected_benefits.map((b, i) => (
                  <li key={i} className="text-[10px] text-[#216B45]">
                    ✓ {b}
                  </li>
                ))}
              </ul>
            </DetailRow>
          )}

          {item.limitations?.length > 0 && (
            <DetailRow label="Limitations">
              <ul className="space-y-0.5">
                {item.limitations.map((l, i) => (
                  <li key={i} className="text-[10px] text-[#7C6428]">
                    · {l}
                  </li>
                ))}
              </ul>
            </DetailRow>
          )}

          {item.source && (
            <DetailRow label="Source">
              <p className="text-[9px] italic text-[#7A8C82]">{item.source}</p>
            </DetailRow>
          )}
        </div>
      )}
    </div>
  );
}

// ── Weather card ─────────────────────────────────────────────────────────────

function WeatherCard({ weather }) {
  if (!weather.fetched && !weather.fetch_error) return null;

  if (!weather.fetched) {
    return (
      <section className="rounded-[22px] border border-[#E0D8B0] bg-[#FFFBEA] p-4">
        <p className="text-[10px] font-bold text-[#8A7830]">
          Weather data unavailable —{" "}
          {weather.fetch_error || "enter rainfall manually."}
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-[22px] border border-[#C5DCE4] bg-[#EBF6FA] p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="grid h-6 w-6 place-items-center rounded-lg bg-[#D0EDF5] text-[#28778A]">
          <ModuleIcon name="drop" size={13} />
        </span>
        <h3 className="text-[11px] font-extrabold text-[#1A4A5A]">
          Weather data
        </h3>
        <span className="ml-auto text-[9px] text-[#5A8090]">
          {weather.data_as_of ? `as of ${weather.data_as_of.slice(0, 10)}` : ""}
        </span>
      </div>
      {weather.location_resolved && (
        <p className="text-[9px] text-[#5A8090] mb-2">
          Location resolved: {weather.location_resolved}
        </p>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {weather.current_temp_c != null && (
          <WeatherTile
            label="Temperature"
            value={`${weather.current_temp_c.toFixed(1)} °C`}
          />
        )}
        {weather.current_humidity_pct != null && (
          <WeatherTile
            label="Humidity"
            value={`${weather.current_humidity_pct.toFixed(0)}%`}
          />
        )}
        {weather.historical_rain_mm != null && (
          <WeatherTile
            label={`Rain last ${weather.historical_days ?? 30} days`}
            value={`${weather.historical_rain_mm.toFixed(1)} mm`}
            note="Observed"
          />
        )}
        {weather.forecast_rain_7d_mm != null && (
          <WeatherTile
            label="7-day rainfall forecast"
            value={`${weather.forecast_rain_7d_mm.toFixed(1)} mm`}
            note="Forecast only"
            warn
          />
        )}
      </div>
      <p className="mt-3 rounded-xl bg-[#D8EEF5] p-2.5 text-[9px] leading-4 text-[#2A6070]">
        ⚠ {weather.forecast_note}
      </p>
    </section>
  );
}

function WeatherTile({ label, value, note, warn = false }) {
  return (
    <div className="rounded-xl border border-[#B8D8E4] bg-white p-2.5">
      <p className="text-[9px] font-bold text-[#5A8090] uppercase tracking-[.06em]">
        {label}
      </p>
      <p
        className={`mt-1 text-[16px] font-extrabold ${
          warn ? "text-[#D99A2B]" : "text-[#1A3C4A]"
        }`}
      >
        {value}
      </p>
      {note && (
        <p
          className={`text-[8px] mt-0.5 ${
            warn ? "text-[#8A6D2B]" : "text-[#7A9090]"
          }`}
        >
          {note}
        </p>
      )}
    </div>
  );
}

// ── Disclaimers ──────────────────────────────────────────────────────────────

function Disclaimers({ items }) {
  if (!items?.length) return null;
  return (
    <section className="rounded-[22px] border border-[#E0E8E2] bg-[#F4F7F3] p-4">
      <p className="text-[10px] font-extrabold text-[#52665B] mb-2">
        Important limitations
      </p>
      <ul className="space-y-1.5">
        {items.map((d, i) => (
          <li
            key={i}
            className="flex items-start gap-1.5 text-[10px] leading-5 text-[#5B6F63]"
          >
            <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[#7A9585]" />
            {d}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── Shared helpers ───────────────────────────────────────────────────────────

function FieldError({ text }) {
  return (
    <p className="text-[9px] font-semibold text-[#C05050] mt-0.5">{text}</p>
  );
}

function DetailRow({ label, children }) {
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-[.07em] text-[#7A8C82] mb-1">
        {label}
      </p>
      {children}
    </div>
  );
}

function CheckRow({ label, sublabel, checked, onChange }) {
  return (
    <label className="flex items-start gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-[#DDE6DF] flex-shrink-0"
      />
      <span className="text-[10px] font-semibold text-[#52675B] leading-4">
        {label}
        {sublabel && (
          <span className="block mt-0.5 text-[9px] font-normal text-[#84938B]">
            {sublabel}
          </span>
        )}
      </span>
    </label>
  );
}

function cap(str) {
  return str ? str.charAt(0).toUpperCase() + str.slice(1) : str;
}
