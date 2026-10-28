import { useState } from "react";

import useApi from "@/hooks/useApi";
import { apiPost } from "@/lib/apiClient";
import ModuleIcon from "./ModuleIcon";
import { Field, ModuleButton } from "./ModuleShared";

/**
 * Organic Farming Advisor.
 *
 * Compares conventional, organic and integrated farming for the farmer's crop,
 * soil, resources and preference, lists suitable organic alternatives, and
 * generates a gradual transition plan.
 *
 * Everything shown comes from the backend's curated reference content plus the
 * farmer's own inputs. FarmIQ never estimates cost, yield, labour or water
 * figures here — those fields are labelled "unavailable" and point at a local
 * source instead.
 */

const STATUS_TONE = {
  guidance: "bg-[#EDF1EE] text-[#52665B]",
  verified: "bg-[#EAF6EF] text-[#216B45]",
  estimate: "bg-[#E8EEF8] text-[#4F6590]",
  unavailable: "bg-[#FFF5DE] text-[#916112]",
};

const STATUS_LABEL = {
  guidance: "Guidance",
  verified: "Verified",
  estimate: "Estimate",
  unavailable: "Unavailable",
};

const EMPTY_FORM = {
  crop: "",
  location: "",
  soil_type: "",
  area_acres: "",
  current_fertilizer: "",
  current_pesticide: "",
  cow_dung: false,
  compost: false,
  crop_residues: false,
  other: "",
  preference: "integrated",
  save: false,
};

export default function OrganicFarmingAdvisor() {
  const { data, loading, error, refetch } = useApi("/api/farming-methods");

  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(null);
  const [savedId, setSavedId] = useState(null);

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const buildPayload = () => ({
    crop: form.crop,
    location: form.location.trim() || null,
    soil_type: form.soil_type,
    area_acres: Number(form.area_acres),
    current_fertilizer: form.current_fertilizer.trim() || null,
    current_pesticide: form.current_pesticide.trim() || null,
    resources: {
      cow_dung: form.cow_dung,
      compost: form.compost,
      crop_residues: form.crop_residues,
      other: form.other
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    },
    preference: form.preference,
    save: form.save,
  });

  const validate = () => {
    const errs = {};
    if (!form.crop) errs.crop = "Select a crop.";
    if (!form.soil_type) errs.soil_type = "Select a soil type.";
    if (!form.area_acres || Number(form.area_acres) <= 0)
      errs.area_acres = "Enter a farm size greater than zero.";
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const submit = async (path, kind) => {
    if (busy) return; // re-entrancy guard (the buttons are also disabled)
    if (!validate()) {
      setSubmitError(null);
      return;
    }
    setBusy(kind);
    setSubmitError(null);
    try {
      const res = await apiPost(path, buildPayload());
      if (kind === "compare") {
        setComparison(res);
        setPlan(null);
        setSavedId(res.saved_plan?.id ?? null);
      } else {
        setPlan(res);
        setSavedId(res.saved_plan?.id ?? null);
      }
    } catch (err) {
      setSubmitError(err);
      if (err.status === 422 && Array.isArray(err.data?.errors)) {
        setFieldErrors(mapServerErrors(err.data.errors));
      }
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((n) => (
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
      <div className="space-y-3">
        <p className="rounded-2xl bg-[#FCE9E5] p-4 text-[11px] font-semibold text-[#9D4C3E]">
          Could not load the farming methods
          {error.status ? ` (${error.status})` : ""}.
        </p>
        <ModuleButton secondary onClick={refetch}>
          Try again
        </ModuleButton>
      </div>
    );
  }

  const crops = data?.crops ?? [];
  const soilTypes = data?.soil_types ?? [];
  const preferences = data?.preferences ?? [];

  if (!crops.length || !soilTypes.length) {
    return (
      <p className="rounded-2xl bg-[#F4F7F3] p-4 text-[11px] font-semibold text-[#5B6F63]">
        No farming-method reference data is available yet.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <section className="rounded-[22px] border border-white/40 bg-white/50 p-4 backdrop-blur-md shadow-sm">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-[#E6F3E8] text-[#216B45]">
            <ModuleIcon name="leaf" size={16} />
          </span>
          <h2 className="text-[13px] font-extrabold text-[#213D2F]">
            Tell us about your farm
          </h2>
        </div>

        <div className="mt-3 space-y-3">
          <SelectInput
            label="Crop"
            value={form.crop}
            onChange={(v) => set("crop", v)}
            options={crops}
            placeholder="Select a crop"
            error={fieldErrors.crop}
          />
          <Field
            label="Farm location"
            value={form.location}
            onChange={(v) => set("location", v)}
            placeholder="Village, district, state"
          />
          <SelectInput
            label="Soil type"
            value={form.soil_type}
            onChange={(v) => set("soil_type", v)}
            options={soilTypes}
            placeholder="Select a soil type"
            error={fieldErrors.soil_type}
          />
          <Field
            label="Farm size (acres)"
            type="number"
            value={form.area_acres}
            onChange={(v) => set("area_acres", v)}
            placeholder="e.g. 2.5"
          />
          {fieldErrors.area_acres && (
            <FieldError text={fieldErrors.area_acres} />
          )}
          <Field
            label="Current fertiliser use"
            value={form.current_fertilizer}
            onChange={(v) => set("current_fertilizer", v)}
            placeholder="e.g. Urea 18 kg/acre, DAP 12 kg/acre"
          />
          <Field
            label="Current pesticide use"
            value={form.current_pesticide}
            onChange={(v) => set("current_pesticide", v)}
            placeholder="e.g. Imidacloprid as needed"
          />
        </div>

        <fieldset className="mt-4">
          <legend className="text-[10px] font-bold text-[#52675B]">
            Organic materials available on your farm
          </legend>
          <div className="mt-2 space-y-2">
            <Check
              label="Cow dung / farmyard manure"
              checked={form.cow_dung}
              onChange={(v) => set("cow_dung", v)}
            />
            <Check
              label="Compost"
              checked={form.compost}
              onChange={(v) => set("compost", v)}
            />
            <Check
              label="Crop residues"
              checked={form.crop_residues}
              onChange={(v) => set("crop_residues", v)}
            />
          </div>
          <div className="mt-3">
            <Field
              label="Other organic materials"
              value={form.other}
              onChange={(v) => set("other", v)}
              placeholder="Vermicompost, green manure... (comma separated)"
            />
          </div>
        </fieldset>

        <div className="mt-4">
          <label className="block">
            <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">
              Farming preference
            </span>
            <select
              value={form.preference}
              onChange={(e) => set("preference", e.target.value)}
              className="h-11 w-full rounded-xl border border-[#DDE6DF] bg-white px-3 text-[12px] font-semibold text-[#203B2D] outline-none focus:border-[#76A58A]"
            >
              {preferences.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-1.5 text-[9px] leading-4 text-[#84938B]">
            {preferences.find((p) => p.id === form.preference)?.short}
          </p>
        </div>

        <label className="mt-3 flex items-center gap-2 text-[10px] font-semibold text-[#52675B]">
          <input
            type="checkbox"
            checked={form.save}
            onChange={(e) => set("save", e.target.checked)}
            className="h-4 w-4 rounded border-[#DDE6DF]"
          />
          Save the result to my account
        </label>

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
            Saved to your account.
          </p>
        )}

        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <ModuleButton
            disabled={busy === "compare"}
            onClick={() => submit("/api/farming-methods/compare", "compare")}
          >
            {busy === "compare" ? "Comparing..." : "Compare Farming Methods"}
          </ModuleButton>
          {comparison && (
            <ModuleButton
              secondary
              disabled={busy === "plan"}
              onClick={() =>
                submit("/api/farming-methods/transition-plan", "plan")
              }
            >
              {busy === "plan"
                ? "Preparing plan..."
                : "Generate transition plan"}
            </ModuleButton>
          )}
        </div>
      </section>

      <Legend legend={data?.legend} />

      {comparison && <ComparisonView data={comparison} />}
      {plan && <PlanView plan={plan} />}
    </div>
  );
}

/* ── Sub-views ─────────────────────────────────────────────────────────── */

function ComparisonView({ data }) {
  return (
    <div className="space-y-4">
      <section className="rounded-[22px] border border-[#DCE6DF] bg-[#F7FAF8] p-4">
        <h2 className="text-[13px] font-extrabold text-[#213D2F]">
          Comparison for {data.crop}
        </h2>
        <p className="mt-1 text-[10px] leading-5 text-[#75867C]">
          {data.recommendation.summary}
        </p>
        <p className="mt-2 rounded-xl bg-white p-3 text-[10px] leading-5 text-[#4C6355]">
          {data.recommendation.nutrient_note}
        </p>
        <p className="mt-2 text-[10px] leading-5 text-[#75867C]">
          {data.recommendation.next_step}
        </p>
      </section>

      {data.warnings?.length > 0 && (
        <section className="rounded-[22px] border border-[#F0DFC0] bg-[#FFF8EA] p-4">
          <h3 className="text-[11px] font-extrabold text-[#8A6D2B]">
            Things to be careful about
          </h3>
          <ul className="mt-2 space-y-1.5">
            {data.warnings.map((w, i) => (
              <li
                key={i}
                className="flex gap-2 text-[10px] leading-5 text-[#7C6428]"
              >
                <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[#D99A2B]" />
                {w}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        {data.methods.map((method) => (
          <MethodCard key={method.id} method={method} />
        ))}
      </div>

      <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <h3 className="text-[12px] font-extrabold text-[#203C2E]">
          Your resources and how they can be used
        </h3>
        <ul className="mt-3 space-y-2">
          {data.resource_assessment.map((r) => (
            <li key={r.resource} className="flex items-start gap-2">
              <span
                className={`mt-[6px] h-1.5 w-1.5 shrink-0 rounded-full ${
                  r.available ? "bg-[#2F7D52]" : "bg-[#C4CEC8]"
                }`}
              />
              <span className="text-[10px] leading-5 text-[#5B6F63]">
                <b>{r.resource}</b> —{" "}
                {r.available ? "available" : "not reported"}
                {r.usable_for?.length > 0 && (
                  <> · usable for: {r.usable_for.join(", ")}</>
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <AlternativesList
        alternatives={data.organic_alternatives}
        crop={data.crop}
      />
      <Cautions cautions={data.cautions} />
      <SourcesFooter sources={data.sources} disclaimer={data.disclaimer} />
    </div>
  );
}

function PlanView({ plan }) {
  return (
    <div className="space-y-4">
      <section className="rounded-[22px] border border-[#DCE6DF] bg-[#F7FAF8] p-4">
        <h2 className="text-[13px] font-extrabold text-[#213D2F]">
          Gradual transition plan for {plan.crop}
        </h2>
        <p className="mt-1 text-[10px] leading-5 text-[#75867C]">
          Preference: {plan.preference_title} · {plan.area_acres} acres
        </p>
        <p className="mt-2 rounded-xl bg-white p-3 text-[10px] leading-5 text-[#4C6355]">
          {plan.uncertainty_note}
        </p>
      </section>

      {plan.phases.map((phase) => (
        <section
          key={phase.id}
          className="rounded-[22px] border border-[#E0E8E2] bg-white p-4"
        >
          <h3 className="text-[12px] font-extrabold text-[#203C2E]">
            {phase.title}
          </h3>
          <p className="mt-1 text-[10px] leading-5 text-[#75867C]">
            {phase.objective}
          </p>
          <p className="mt-1 text-[9px] font-bold uppercase tracking-[.08em] text-[#9AA79F]">
            {phase.timeframe}
          </p>
          <ol className="mt-2 space-y-2">
            {phase.steps.map((step, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="mt-[3px] grid h-4 w-4 shrink-0 place-items-center rounded-full bg-[#E9F1EA] text-[8px] font-extrabold text-[#3C6A4D]">
                  {i + 1}
                </span>
                <span className="text-[10px] leading-5 text-[#5B6F63]">
                  {step.text} <StatusBadge status={step.status} />
                </span>
              </li>
            ))}
          </ol>
        </section>
      ))}

      <section className="rounded-[22px] border border-[#F0DFC0] bg-[#FFF8EA] p-4">
        <h3 className="text-[11px] font-extrabold text-[#8A6D2B]">
          Costs and resources
        </h3>
        <p className="mt-1 text-[10px] leading-5 text-[#7C6428]">
          {plan.costs_and_resources.note}
        </p>
        {plan.costs_and_resources.reported_on_farm_materials?.length > 0 && (
          <p className="mt-2 text-[10px] leading-5 text-[#7C6428]">
            You reported:{" "}
            {plan.costs_and_resources.reported_on_farm_materials.join(", ")}.
          </p>
        )}
      </section>

      <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <h3 className="text-[12px] font-extrabold text-[#203C2E]">
          Indicators for continuing or adjusting
        </h3>
        <ul className="mt-2 space-y-1.5">
          {plan.decision_indicators.map((d) => (
            <li key={d.id} className="flex items-start gap-2">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[#7EAE8E]" />
              <span className="text-[10px] leading-5 text-[#5B6F63]">
                {d.text}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 rounded-xl bg-[#F4F7F3] p-3 text-[10px] leading-5 text-[#4C6355]">
          {plan.professional_advice_note}
        </p>
      </section>

      <Cautions cautions={plan.cautions} />
      <SourcesFooter sources={plan.sources} disclaimer={plan.disclaimer} />
    </div>
  );
}

function MethodCard({ method }) {
  return (
    <article className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
      <div className="flex items-start gap-2">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[#E9F1EA] text-[#3C6A4D]">
          <ModuleIcon name="leaf" size={17} />
        </span>
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold text-[#213D2F]">
            {method.title}
          </h3>
          <p className="mt-0.5 text-[9px] leading-4 text-[#84938B]">
            {method.short}
          </p>
        </div>
      </div>
      <p className="mt-2 text-[10px] leading-5 text-[#5B6F63]">
        {method.summary}
      </p>
      {method.fit_note && (
        <p className="mt-2 rounded-xl bg-[#F4F7F3] p-2.5 text-[9px] leading-4 text-[#4C6355]">
          {method.fit_note}
        </p>
      )}

      <LabeledList
        label="Recommended practices"
        block={method.recommended_practices}
      />
      <Labeled
        label="Fertiliser & nutrition"
        item={method.fertilizer_and_nutrition}
      />
      <Labeled
        label="Pest management"
        item={method.pest_and_disease_management}
      />
      <CostBlock item={method.estimated_cost_per_acre} />
      <Labeled label="Labour requirement" item={method.labour_requirement} />
      <Labeled label="Water requirement" item={method.water_requirement} />
      <LabeledList label="Benefits" block={method.benefits} />
      <LabeledList label="Limitations" block={method.limitations} />
      <Labeled label="Soil health" item={method.soil_health} />
      <Labeled label="Yield impact" item={method.yield_impact} />
      <Labeled
        label="Environmental impact"
        item={method.environmental_impact}
      />
      <Labeled
        label="Transition difficulty"
        item={method.transition_difficulty}
      />

      <div className="mt-3 border-t border-[#EDF1EE] pt-3">
        <p className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
          Sources
        </p>
        <ul className="mt-1 space-y-0.5">
          {method.sources?.map((s, i) => (
            <li key={i} className="text-[9px] leading-4 text-[#84938B]">
              • {s}
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

function AlternativesList({ alternatives, crop }) {
  if (!alternatives?.length) {
    return (
      <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <h3 className="text-[12px] font-extrabold text-[#203C2E]">
          Organic alternatives
        </h3>
        <p className="mt-2 text-[10px] text-[#84938B]">
          No curated alternatives apply to {crop} yet.
        </p>
      </section>
    );
  }
  return (
    <section className="space-y-3">
      <h3 className="text-[13px] font-extrabold text-[#1D382A]">
        Organic alternatives for {crop}
      </h3>
      {alternatives.map((alt) => (
        <details
          key={alt.id}
          className="rounded-[22px] border border-[#E0E8E2] bg-white"
        >
          <summary className="cursor-pointer list-none p-4">
            <span className="flex items-center gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[#E6F3E8] text-[#216B45]">
                <ModuleIcon name="leaf" size={16} />
              </span>
              <span className="min-w-0 flex-1">
                <b className="block text-[12px] text-[#294234]">{alt.name}</b>
                <span className="mt-0.5 block text-[9px] text-[#84938B]">
                  {alt.category}
                </span>
              </span>
            </span>
          </summary>
          <div className="space-y-2.5 border-t border-[#EDF1EE] p-4">
            <TextBlock label="What it does" text={alt.what_it_does} />
            <TextBlock label="How it is used" text={alt.how_used} />
            <TextBlock label="Limitations" text={alt.limitations} />
            <TextBlock label="Precautions" text={alt.precautions} tone="warn" />
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
                  Nutrient content
                </span>
                <StatusBadge status={alt.nutrient_content?.status} />
              </div>
              <p className="mt-1 text-[10px] leading-5 text-[#5B6F63]">
                {alt.nutrient_content?.note}
              </p>
            </div>
            <p className="text-[9px] text-[#9AA79F]">
              {alt.sources?.join(" · ")} · {alt.last_updated}
            </p>
          </div>
        </details>
      ))}
    </section>
  );
}

function Cautions({ cautions }) {
  if (!cautions?.length) return null;
  return (
    <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
      <h3 className="text-[12px] font-extrabold text-[#203C2E]">
        Important cautions
      </h3>
      <ul className="mt-2 space-y-1.5">
        {cautions.map((c, i) => (
          <li
            key={i}
            className="flex gap-2 text-[10px] leading-5 text-[#5B6F63]"
          >
            <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[#D99A2B]" />
            {c}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SourcesFooter({ sources, disclaimer }) {
  return (
    <section className="rounded-[22px] border border-[#E0E8E2] bg-[#F7FAF8] p-4">
      <p className="text-[9px] leading-4 text-[#84938B]">
        Source: {sources?.note}
      </p>
      <p className="mt-1.5 text-[9px] leading-4 text-[#84938B]">
        Integrity: {sources?.integrity_note || sources?.content_source}
      </p>
      <p className="mt-1.5 text-[9px] leading-4 text-[#84938B]">
        Reference content last updated: {sources?.last_updated}. Content served
        from: {sources?.content_source}.
      </p>
      <p className="mt-1.5 text-[9px] leading-4 text-[#84938B]">{disclaimer}</p>
    </section>
  );
}

function Legend({ legend }) {
  if (!legend) return null;
  return (
    <section className="rounded-[22px] border border-[#E0E8E2] bg-[#F7FAF8] p-4">
      <p className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
        How to read these labels
      </p>
      <ul className="mt-2 space-y-1.5">
        {Object.entries(legend).map(([key, text]) => (
          <li key={key} className="flex items-start gap-2">
            <StatusBadge status={key} />
            <span className="text-[9px] leading-4 text-[#84938B]">{text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ── Small building blocks ─────────────────────────────────────────────── */

function StatusBadge({ status }) {
  if (!status) return null;
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-1.5 py-0.5 text-[8px] font-extrabold uppercase tracking-[.06em] ${
        STATUS_TONE[status] || STATUS_TONE.guidance
      }`}
    >
      {STATUS_LABEL[status] || status}
    </span>
  );
}

function Labeled({ label, item }) {
  if (!item) return null;
  return (
    <div className="mt-3">
      <div className="flex items-center gap-2">
        <span className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
          {label}
        </span>
        <StatusBadge status={item.status} />
      </div>
      {item.level && (
        <p className="mt-1 text-[11px] font-extrabold text-[#294234]">
          {item.level}
        </p>
      )}
      {item.text && (
        <p className="mt-0.5 text-[10px] leading-5 text-[#5B6F63]">
          {item.text}
        </p>
      )}
      {item.note && (
        <p className="mt-1 text-[9px] italic leading-4 text-[#8A6D2B]">
          {item.note}
        </p>
      )}
    </div>
  );
}

function LabeledList({ label, block }) {
  if (!block?.items?.length) return null;
  return (
    <div className="mt-3">
      <div className="flex items-center gap-2">
        <span className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
          {label}
        </span>
        <StatusBadge status={block.status} />
      </div>
      <ul className="mt-1.5 space-y-1">
        {block.items.map((item, i) => (
          <li
            key={i}
            className="flex gap-2 text-[10px] leading-5 text-[#5B6F63]"
          >
            <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[#7EAE8E]" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CostBlock({ item }) {
  if (!item) return null;
  return (
    <div className="mt-3">
      <div className="flex items-center gap-2">
        <span className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
          Estimated cost per acre
        </span>
        <StatusBadge status={item.status} />
      </div>
      <p className="mt-1 text-[11px] font-extrabold text-[#916112]">
        {item.value == null
          ? "Not estimated by FarmIQ"
          : `${item.value} ${item.unit}`}
      </p>
      {item.note && (
        <p className="mt-0.5 text-[9px] leading-4 text-[#8A6D2B]">
          {item.note}
        </p>
      )}
    </div>
  );
}

function TextBlock({ label, text, tone }) {
  if (!text) return null;
  return (
    <div>
      <p className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
        {label}
      </p>
      <p
        className={`mt-1 text-[10px] leading-5 ${
          tone === "warn" ? "text-[#8A6D2B]" : "text-[#5B6F63]"
        }`}
      >
        {text}
      </p>
    </div>
  );
}

function SelectInput({ label, value, onChange, options, placeholder, error }) {
  return (
    <div>
      <label className="block">
        <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">
          {label}
        </span>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-11 w-full rounded-xl border border-[#DDE6DF] bg-white px-3 text-[12px] font-semibold text-[#203B2D] outline-none focus:border-[#76A58A]"
        >
          <option value="">{placeholder}</option>
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      {error && <FieldError text={error} />}
    </div>
  );
}

function Check({ label, checked, onChange }) {
  return (
    <label className="flex items-center gap-2 text-[11px] font-semibold text-[#3F5A4B]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-[#DDE6DF]"
      />
      {label}
    </label>
  );
}

function FieldError({ text }) {
  return <p className="mt-1 text-[9px] font-semibold text-[#9D4C3E]">{text}</p>;
}

/** Map backend validation errors (semantic `field` or schema `loc`) to the form. */
export function mapServerErrors(errors) {
  const out = {};
  for (const e of errors || []) {
    const key =
      e.field || (Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : null);
    if (key && !out[key]) out[key] = e.message || e.msg || "Invalid value.";
  }
  return out;
}
