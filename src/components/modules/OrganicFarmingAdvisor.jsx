import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";

import useApi from "@/hooks/useApi";
import { apiPost } from "@/lib/apiClient";
import { useLocation } from "@/lib/locationStore";
import i18n from "@/i18n";
import ModuleIcon from "./ModuleIcon";
import { Field, ModuleButton } from "./ModuleShared";

// ── Static educational content ───────────────────────────────────────────────

// Only presentation metadata lives in code; the visible copy is translated.
const PRACTICE_CARD_META = [
  { id: "composting", icon: "soil", color: "bg-[#EDF5E6] text-[#3C6A4D]" },
  {
    id: "vermicomposting",
    icon: "soil",
    color: "bg-[#EDF5E6] text-[#3C6A4D]",
  },
  { id: "green-manuring", icon: "crop", color: "bg-[#E6F3E8] text-[#216B45]" },
  { id: "mulching", icon: "drop", color: "bg-[#E5F3F7] text-[#28778A]" },
  { id: "crop-rotation", icon: "crop", color: "bg-[#E6F3E8] text-[#216B45]" },
  { id: "intercropping", icon: "farm", color: "bg-[#FFF2DA] text-[#986313]" },
  { id: "biofertilizers", icon: "flask", color: "bg-[#F0EAFC] text-[#6B42A2]" },
  { id: "ipm", icon: "shield", color: "bg-[#FCE9E5] text-[#A55243]" },
];

const ADVANTAGE_ASPECTS = [
  "soilHealth",
  "waterConservation",
  "inputCosts",
  "labourRequirements",
  "nutrientAvailability",
  "pestDisease",
  "yieldTransition",
  "certificationMarkets",
];

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

export default function OrganicFarmingAdvisor({ onAsk }) {
  const { t } = useTranslation();
  const { location: sharedLocation } = useLocation();
  const [activeTab, setActiveTab] = useState("learn");
  const { data, loading, error, refetch } = useApi("/api/farming-methods");

  const TABS = [
    { key: "learn", label: t("organicAdvisor.tabs.learn") },
    { key: "practices", label: t("organicAdvisor.tabs.practices") },
    { key: "compare", label: t("organicAdvisor.tabs.compare") },
    { key: "assess", label: t("organicAdvisor.tabs.assess") },
  ];

  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(null);
  const [savedId, setSavedId] = useState(null);

  // Pre-fill location from the shared location store when available.
  useEffect(() => {
    if (sharedLocation?.label && !form.location) {
      setForm((prev) => ({ ...prev, location: sharedLocation.label }));
    }
  }, [sharedLocation]);  // eslint-disable-line react-hooks/exhaustive-deps

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
    if (!form.crop) errs.crop = t("organicAdvisor.validation.selectCrop");
    if (!form.soil_type) errs.soil_type = t("organicAdvisor.validation.selectSoil");
    if (!form.area_acres || Number(form.area_acres) <= 0)
      errs.area_acres = t("organicAdvisor.validation.areaPositive");
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

  const crops = data?.crops ?? [];
  const soilTypes = data?.soil_types ?? [];
  const preferences = data?.preferences ?? [];

  // ── Tab rendering ─────────────────────────────────────────────────────────
  const renderLearnTab = () => (
    <div className="space-y-4">
      {/* What is organic farming */}
      <section className="rounded-[22px] border border-white/40 bg-white/50 p-4 backdrop-blur-md shadow-sm">
        <div className="flex items-center gap-2 mb-3">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-[#E6F3E8] text-[#216B45]">
            <ModuleIcon name="leaf" size={16} />
          </span>
          <h2 className="text-[13px] font-extrabold text-[#213D2F]">{t("organicAdvisor.learn.title")}</h2>
        </div>
        <p className="text-[11px] leading-[1.65] text-[#3C5248]">
          {t("organicAdvisor.learn.intro1")}
        </p>
        <p className="mt-2 text-[11px] leading-[1.65] text-[#3C5248]">
          {t("organicAdvisor.learn.intro2")}
        </p>

        <div className="mt-4 space-y-2">
          {t("organicAdvisor.learn.items", { returnObjects: true }).map((item) => (
            <div key={item.label} className="rounded-xl border border-[#DDE9E1] bg-white p-3">
              <p className="text-[10px] font-extrabold text-[#216B45] mb-1">{item.label}</p>
              <p className="text-[10px] leading-5 text-[#5B6F63]">{item.text}</p>
            </div>
          ))}
        </div>

        <div className="mt-4 rounded-xl border border-[#F0DFC0] bg-[#FFF8EA] p-3">
          <p className="text-[10px] font-extrabold text-[#8A6D2B] mb-1">{t("organicAdvisor.learn.limitationsTitle")}</p>
          <ul className="space-y-1">
            {t("organicAdvisor.learn.limitations", { returnObjects: true }).map((item, i) => (
              <li key={i} className="flex items-start gap-1.5 text-[10px] leading-5 text-[#7C6428]">
                <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[#D99A2B]" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* AI assistant integration */}
      {onAsk && (
        <section className="rounded-[22px] border border-[#D6E4D8] bg-[#F7FAF8] p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="grid h-7 w-7 place-items-center rounded-xl bg-[#E6F3E8] text-[#216B45]">
              <ModuleIcon name="sparkles" size={15} />
            </span>
            <h3 className="text-[12px] font-extrabold text-[#213D2F]">{t("organicAdvisor.learn.askTitle")}</h3>
          </div>
          <p className="text-[10px] leading-5 text-[#5B6F63] mb-3">
            {t("organicAdvisor.learn.askBody")}
          </p>
          <div className="space-y-1.5 mb-3">
            {t("organicAdvisor.learn.askQuestions", { returnObjects: true }).map((q, i) => (
              <p key={i} className="rounded-lg bg-white border border-[#DDE9E1] px-3 py-2 text-[10px] italic text-[#5B6F63]">
                "{q}"
              </p>
            ))}
          </div>
          <ModuleButton onClick={onAsk}>
            {t("organicAdvisor.learn.openAssistant")}
          </ModuleButton>
        </section>
      )}
    </div>
  );

  const renderPracticesTab = () => (
    <div className="space-y-3">
      <p className="rounded-xl border border-[#E0E8E2] bg-white p-3 text-[10px] leading-5 text-[#5B6F63]">
        {t("organicAdvisor.practices.intro")}
      </p>
      {PRACTICE_CARD_META.map((card) => (
        <PracticeCard key={card.id} card={card} />
      ))}
    </div>
  );

  const renderCompareTab = () => (
    <div className="space-y-4">
      <section className="rounded-[22px] border border-white/40 bg-white/50 p-4 backdrop-blur-md shadow-sm">
        <div className="flex items-center gap-2 mb-3">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-[#E6F3E8] text-[#216B45]">
            <ModuleIcon name="report" size={16} />
          </span>
          <h2 className="text-[13px] font-extrabold text-[#213D2F]">{t("organicAdvisor.compare.title")}</h2>
        </div>
        <p className="text-[10px] leading-5 text-[#5B6F63] mb-4">
          {t("organicAdvisor.compare.intro")}
        </p>
        <div className="space-y-3">
          {ADVANTAGE_ASPECTS.map((id) => (
            <div key={id} className="rounded-xl border border-[#DDE9E1] bg-white overflow-hidden">
              <div className="bg-[#E6F3E8] px-3 py-2">
                <p className="text-[10px] font-extrabold text-[#216B45]">{t(`organicAdvisor.compare.rows.${id}.aspect`)}</p>
              </div>
              <div className="grid grid-cols-1 gap-0 sm:grid-cols-2">
                <div className="p-3 border-b border-[#EDF1EE] sm:border-b-0 sm:border-r">
                  <p className="text-[9px] font-extrabold uppercase tracking-[.06em] text-[#216B45] mb-1">{t("organicAdvisor.compare.potentialBenefit")}</p>
                  <p className="text-[10px] leading-5 text-[#3C5248]">{t(`organicAdvisor.compare.rows.${id}.potential`)}</p>
                </div>
                <div className="p-3">
                  <p className="text-[9px] font-extrabold uppercase tracking-[.06em] text-[#8A6D2B] mb-1">{t("organicAdvisor.compare.consideration")}</p>
                  <p className="text-[10px] leading-5 text-[#7C6428]">{t(`organicAdvisor.compare.rows.${id}.consideration`)}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="rounded-[22px] border border-[#E0E8E2] bg-[#F7FAF8] p-4">
        <p className="text-[10px] font-extrabold text-[#52665B] mb-2">{t("organicAdvisor.compare.howToUseTitle")}</p>
        <p className="text-[10px] leading-5 text-[#5B6F63]">
          {t("organicAdvisor.compare.howToUseBody")}
        </p>
      </section>
    </div>
  );

  const renderAssessTab = () => {
    if (loading) {
      return (
        <div className="space-y-3">
          {[1, 2, 3].map((n) => (
            <div key={n} className="h-24 animate-pulse rounded-[20px] bg-[#E8F0EB]" />
          ))}
        </div>
      );
    }
    if (error) {
      return (
        <div className="space-y-3">
          <p className="rounded-2xl bg-[#FCE9E5] p-4 text-[11px] font-semibold text-[#9D4C3E]">
            {t("organicAdvisor.error.loadMethods", {
              status: error.status ? ` (${error.status})` : "",
            })}
          </p>
          <ModuleButton secondary onClick={refetch}>{t("organicAdvisor.error.tryAgain")}</ModuleButton>
        </div>
      );
    }
    const crops = data?.crops ?? [];
    const soilTypes = data?.soil_types ?? [];
    const preferences = data?.preferences ?? [];
    if (!crops.length || !soilTypes.length) {
      return (
        <p className="rounded-2xl bg-[#F4F7F3] p-4 text-[11px] font-semibold text-[#5B6F63]">
          {t("organicAdvisor.error.noData")}
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
              {t("organicAdvisor.assess.title")}
            </h2>
          </div>

        <div className="mt-3 space-y-3">
          <SelectInput
            label={t("organicAdvisor.assess.crop")}
            value={form.crop}
            onChange={(v) => set("crop", v)}
            options={crops}
            placeholder={t("organicAdvisor.assess.cropPlaceholder")}
            error={fieldErrors.crop}
          />
          <Field
            label={t("organicAdvisor.assess.farmLocation")}
            value={form.location}
            onChange={(v) => set("location", v)}
            placeholder={t("organicAdvisor.assess.farmLocationPlaceholder")}
          />
          <SelectInput
            label={t("organicAdvisor.assess.soilType")}
            value={form.soil_type}
            onChange={(v) => set("soil_type", v)}
            options={soilTypes}
            placeholder={t("organicAdvisor.assess.soilTypePlaceholder")}
            error={fieldErrors.soil_type}
          />
          <Field
            label={t("organicAdvisor.assess.farmSize")}
            type="number"
            value={form.area_acres}
            onChange={(v) => set("area_acres", v)}
            placeholder={t("organicAdvisor.assess.farmSizePlaceholder")}
          />
          {fieldErrors.area_acres && (
            <FieldError text={fieldErrors.area_acres} />
          )}
          <Field
            label={t("organicAdvisor.assess.currentFertiliser")}
            value={form.current_fertilizer}
            onChange={(v) => set("current_fertilizer", v)}
            placeholder={t("organicAdvisor.assess.currentFertiliserPlaceholder")}
          />
          <Field
            label={t("organicAdvisor.assess.currentPesticide")}
            value={form.current_pesticide}
            onChange={(v) => set("current_pesticide", v)}
            placeholder={t("organicAdvisor.assess.currentPesticidePlaceholder")}
          />
        </div>

        <fieldset className="mt-4">
          <legend className="text-[10px] font-bold text-[#52675B]">
            {t("organicAdvisor.assess.organicMaterialsLegend")}
          </legend>
          <div className="mt-2 space-y-2">
            <Check
              label={t("organicAdvisor.assess.cowDung")}
              checked={form.cow_dung}
              onChange={(v) => set("cow_dung", v)}
            />
            <Check
              label={t("organicAdvisor.assess.compost")}
              checked={form.compost}
              onChange={(v) => set("compost", v)}
            />
            <Check
              label={t("organicAdvisor.assess.cropResidues")}
              checked={form.crop_residues}
              onChange={(v) => set("crop_residues", v)}
            />
          </div>
          <div className="mt-3">
            <Field
              label={t("organicAdvisor.assess.otherMaterials")}
              value={form.other}
              onChange={(v) => set("other", v)}
              placeholder={t("organicAdvisor.assess.otherMaterialsPlaceholder")}
            />
          </div>
        </fieldset>

        <div className="mt-4">
          <label className="block">
            <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">
              {t("organicAdvisor.assess.preference")}
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
          {t("organicAdvisor.assess.save")}
        </label>

        {submitError && (
          <div
            role="alert"
            className="mt-3 rounded-2xl bg-[#FCE9E5] p-3 text-[10px] font-semibold leading-5 text-[#9D4C3E]"
          >
            {submitError.message || t("organicAdvisor.assess.somethingWrong")}
          </div>
        )}
        {savedId && (
          <p className="mt-3 rounded-2xl bg-[#EAF6EF] p-3 text-[10px] font-semibold text-[#216B45]">
            {t("organicAdvisor.assess.saved")}
          </p>
        )}

        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <ModuleButton
            disabled={busy === "compare"}
            onClick={() => submit("/api/farming-methods/compare", "compare")}
          >
            {busy === "compare" ? t("organicAdvisor.assess.comparing") : t("organicAdvisor.assess.compare")}
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
                ? t("organicAdvisor.assess.preparingPlan")
                : t("organicAdvisor.assess.generatePlan")}
            </ModuleButton>
          )}
        </div>
      </section>

      <Legend legend={data?.legend} />

      {comparison && <ComparisonView data={comparison} />}
      {plan && <PlanView plan={plan} />}
    </div>
    );
  }; // end renderAssessTab

  return (
    <div className="space-y-4">
      {/* Tab strip */}
      <div className="flex gap-1 overflow-x-auto rounded-[18px] border border-white/40 bg-white/50 p-1 backdrop-blur-md">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 shrink-0 rounded-[14px] px-3 py-2 text-[11px] font-extrabold transition whitespace-nowrap ${
              activeTab === tab.key
                ? "bg-[#216B45] text-white shadow"
                : "text-[#52665B] hover:bg-white/60"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "learn" && renderLearnTab()}
      {activeTab === "practices" && renderPracticesTab()}
      {activeTab === "compare" && renderCompareTab()}
      {activeTab === "assess" && renderAssessTab()}
    </div>
  );
}

/* ── Practice Card ─────────────────────────────────────────────────────── */

function PracticeCard({ card }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const base = `organicAdvisor.practices.cards.${card.id}`;
  const name = t(`${base}.name`);
  const explanation = t(`${base}.explanation`);
  const advantages = t(`${base}.advantages`, { returnObjects: true });
  const whenUseful = t(`${base}.whenUseful`);
  const precautions = t(`${base}.precautions`);
  return (
    <div className={`rounded-[22px] border border-white/60 bg-white overflow-hidden`}>
      <button
        className="w-full text-left p-4 flex items-center gap-3"
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${card.color}`}>
          <ModuleIcon name={card.icon} size={17} />
        </span>
        <span className="flex-1 min-w-0">
          <p className="text-[12px] font-extrabold text-[#213D2F]">{name}</p>
          <p className="text-[10px] text-[#84938B] leading-4 mt-0.5 line-clamp-1">{explanation}</p>
        </span>
        <span className="text-[10px] text-[#84938B]">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="border-t border-[#EDF1EE] p-4 space-y-3">
          <div>
            <p className="text-[9px] font-extrabold uppercase tracking-[.07em] text-[#7A8B82] mb-1">{t("organicAdvisor.practiceCard.whatItIs")}</p>
            <p className="text-[10px] leading-5 text-[#5B6F63]">{explanation}</p>
          </div>
          <div>
            <p className="text-[9px] font-extrabold uppercase tracking-[.07em] text-[#216B45] mb-1">{t("organicAdvisor.practiceCard.advantages")}</p>
            <ul className="space-y-1">
              {advantages.map((a, i) => (
                <li key={i} className="flex items-start gap-1.5 text-[10px] leading-5 text-[#3C5248]">
                  <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[#3F9C6A]" />
                  {a}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-[9px] font-extrabold uppercase tracking-[.07em] text-[#5A8090] mb-1">{t("organicAdvisor.practiceCard.whenUseful")}</p>
            <p className="text-[10px] leading-5 text-[#5B6F63]">{whenUseful}</p>
          </div>
          <div className="rounded-xl bg-[#FFF8EA] border border-[#F0DFC0] p-3">
            <p className="text-[9px] font-extrabold uppercase tracking-[.07em] text-[#8A6D2B] mb-1">{t("organicAdvisor.practiceCard.precautions")}</p>
            <p className="text-[10px] leading-5 text-[#7C6428]">{precautions}</p>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Sub-views ─────────────────────────────────────────────────────────── */

function ComparisonView({ data }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <section className="rounded-[22px] border border-[#DCE6DF] bg-[#F7FAF8] p-4">
        <h2 className="text-[13px] font-extrabold text-[#213D2F]">
          {t("organicAdvisor.comparison.title", { crop: data.crop })}
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
            {t("organicAdvisor.comparison.warningsTitle")}
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
          {t("organicAdvisor.comparison.resourcesTitle")}
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
                {r.available
                  ? t("organicAdvisor.comparison.available")
                  : t("organicAdvisor.comparison.notReported")}
                {r.usable_for?.length > 0 && (
                  <>
                    {" "}
                    ·{" "}
                    {t("organicAdvisor.comparison.usableFor", {
                      list: r.usable_for.join(", "),
                    })}
                  </>
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
      {/* ── Side-by-side comparison dashboard ───────────────────── */}
      <ComparisonDashboard methods={data.methods} crop={data.crop} />
    </div>
  );
}

function PlanView({ plan }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <section className="rounded-[22px] border border-[#DCE6DF] bg-[#F7FAF8] p-4">
        <h2 className="text-[13px] font-extrabold text-[#213D2F]">
          {t("organicAdvisor.plan.title", { crop: plan.crop })}
        </h2>
        <p className="mt-1 text-[10px] leading-5 text-[#75867C]">
          {t("organicAdvisor.plan.preference", {
            title: plan.preference_title,
            area: plan.area_acres,
          })}
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
          {t("organicAdvisor.plan.costsTitle")}
        </h3>
        <p className="mt-1 text-[10px] leading-5 text-[#7C6428]">
          {plan.costs_and_resources.note}
        </p>
        {plan.costs_and_resources.reported_on_farm_materials?.length > 0 && (
          <p className="mt-2 text-[10px] leading-5 text-[#7C6428]">
            {t("organicAdvisor.plan.reported", {
              list: plan.costs_and_resources.reported_on_farm_materials.join(", "),
            })}
          </p>
        )}
      </section>

      <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <h3 className="text-[12px] font-extrabold text-[#203C2E]">
          {t("organicAdvisor.plan.indicatorsTitle")}
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
  const { t } = useTranslation();
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
        label={t("organicAdvisor.method.recommendedPractices")}
        block={method.recommended_practices}
      />
      <Labeled
        label={t("organicAdvisor.method.fertiliser")}
        item={method.fertilizer_and_nutrition}
      />
      <Labeled
        label={t("organicAdvisor.method.pestManagement")}
        item={method.pest_and_disease_management}
      />
      <CostBlock item={method.estimated_cost_per_acre} />
      <Labeled label={t("organicAdvisor.method.labour")} item={method.labour_requirement} />
      <Labeled label={t("organicAdvisor.method.water")} item={method.water_requirement} />
      <LabeledList label={t("organicAdvisor.method.benefits")} block={method.benefits} />
      <LabeledList label={t("organicAdvisor.method.limitations")} block={method.limitations} />
      <Labeled label={t("organicAdvisor.method.soilHealth")} item={method.soil_health} />
      <Labeled label={t("organicAdvisor.method.yieldImpact")} item={method.yield_impact} />
      <Labeled
        label={t("organicAdvisor.method.environmentalImpact")}
        item={method.environmental_impact}
      />
      <Labeled
        label={t("organicAdvisor.method.transitionDifficulty")}
        item={method.transition_difficulty}
      />

      <div className="mt-3 border-t border-[#EDF1EE] pt-3">
        <p className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
          {t("organicAdvisor.method.sources")}
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

// ── Comparison Dashboard — side-by-side table ────────────────────────────────

function ComparisonDashboard({ methods, crop }) {
  if (!methods?.length) return null;

  const ROWS = [
    {
      key: "estimated_cost_per_acre",
      label: "Estimated cost / acre",
      render: (m) => {
        const c = m.estimated_cost_per_acre;
        if (!c) return <Unavail />;
        return c.value != null ? (
          <span className="font-bold text-[#916112]">
            {c.value} {c.unit}
          </span>
        ) : (
          <Unavail note={c.note} />
        );
      },
    },
    {
      key: "labour_requirement",
      label: "Labour",
      render: (m) => <TextOrUnavail item={m.labour_requirement} />,
    },
    {
      key: "water_requirement",
      label: "Water",
      render: (m) => <TextOrUnavail item={m.water_requirement} />,
    },
    {
      key: "soil_health",
      label: "Soil health",
      render: (m) => <TextOrUnavail item={m.soil_health} />,
    },
    {
      key: "yield_impact",
      label: "Yield impact",
      render: (m) => <TextOrUnavail item={m.yield_impact} />,
    },
    {
      key: "environmental_impact",
      label: "Environment",
      render: (m) => <TextOrUnavail item={m.environmental_impact} />,
    },
    {
      key: "transition_difficulty",
      label: "Transition",
      render: (m) => <TextOrUnavail item={m.transition_difficulty} />,
    },
  ];

  const METHOD_COLORS = [
    "bg-[#E6F3E8] text-[#216B45] border-[#B6D9C2]",
    "bg-[#E5F3F7] text-[#28778A] border-[#B0D5E0]",
    "bg-[#EAF1DE] text-[#657638] border-[#C2D498]",
  ];

  return (
    <div className="space-y-3">
      <h3 className="text-[13px] font-extrabold text-[#1D382A]">
        Side-by-side comparison — {crop}
      </h3>

      {/* Comparison table */}
      <div className="overflow-x-auto rounded-[22px] border border-[#E0E8E2] bg-white">
        <table className="w-full min-w-[420px] text-left">
          <thead>
            <tr className="border-b border-[#EDF1EE]">
              <th className="p-3 text-[9px] font-bold uppercase tracking-[.08em] text-[#7A8B82] w-28">
                Feature
              </th>
              {methods.map((m, i) => (
                <th
                  key={m.id}
                  className={`p-3 text-[10px] font-extrabold rounded-t-sm border-b-2 ${
                    METHOD_COLORS[i % 3]
                  }`}
                >
                  {m.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr
                key={row.key}
                className="border-b border-[#F0F4F1] last:border-0"
              >
                <td className="p-3 text-[9px] font-bold text-[#7A8B82] align-top">
                  {row.label}
                </td>
                {methods.map((m) => (
                  <td
                    key={m.id}
                    className="p-3 text-[10px] text-[#5B6F63] align-top"
                  >
                    {row.render(m)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Unavail({ note }) {
  return (
    <span className="text-[9px] italic text-[#916112]">
      Not estimated
      {note ? ` — ${note}` : ""}
    </span>
  );
}

function TextOrUnavail({ item }) {
  if (!item) return <Unavail />;
  if (item.text) return <span>{item.text}</span>;
  if (item.level) return <span className="font-bold">{item.level}</span>;
  return <Unavail note={item.note} />;
}
