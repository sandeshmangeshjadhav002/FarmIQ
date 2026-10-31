import { useState } from "react";
import { useTranslation } from "react-i18next";
import { DemoBadge, ModuleButton, SelectField } from "./ModuleShared";
import ModuleIcon from "./ModuleIcon";

const CROP_OPTIONS = [
  { value: "Tomato", labelKey: "imageAnalysis.cropOptions.tomato" },
  { value: "Onion", labelKey: "imageAnalysis.cropOptions.onion" },
  { value: "Wheat", labelKey: "imageAnalysis.cropOptions.wheat" },
  { value: "Other", labelKey: "imageAnalysis.cropOptions.other" },
];
const PROBLEM_OPTIONS = [
  { value: "Leaf spots", labelKey: "imageAnalysis.problemOptions.leafSpots" },
  { value: "Curling", labelKey: "imageAnalysis.problemOptions.curling" },
  { value: "Yellowing", labelKey: "imageAnalysis.problemOptions.yellowing" },
  { value: "Not sure", labelKey: "imageAnalysis.problemOptions.notSure" },
];

/**
 * Crop Image Analysis module.
 *
 * Lets the user upload a crop photograph and select the visible symptom.
 * The analysis result is a demonstration — no real AI inference runs here.
 */
export default function ImageAnalysis() {
  const { t } = useTranslation();
  const [file, setFile]             = useState("");
  const [crop, setCrop]             = useState(CROP_OPTIONS[0].value);
  const [problem, setProblem]       = useState(PROBLEM_OPTIONS[0].value);
  const [processing, setProcessing] = useState(false);
  const [result, setResult]         = useState(false);

  const handleFileChange = (e) => {
    setFile(e.target.files?.[0]?.name ?? "");
    setResult(false);
  };

  const analyze = () => {
    if (!file) return;
    setProcessing(true);
    // Simulate a short processing delay (demonstration only — no real inference)
    setTimeout(() => {
      setProcessing(false);
      setResult(true);
    }, 900);
  };

  return (
    <div className="space-y-4">
      <DemoBadge status={t("imageAnalysis.aiDemonstration")} />

      {/* Photo upload */}
      <label className="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-[22px] border-2 border-dashed border-[#B7CABB] bg-white p-6 text-center">
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-[#E9F3EC] text-[#216B45]">
          <ModuleIcon name="camera" />
        </span>
        <b className="mt-3 text-[13px] text-[#294234]">
          {file || t("imageAnalysis.uploadPrompt")}
        </b>
        <span className="mt-1 text-[10px] text-[#829188]">
          {t("imageAnalysis.uploadHint")}
        </span>
        <input
          className="hidden"
          type="file"
          accept="image/*"
          onChange={handleFileChange}
        />
      </label>

      {/* Crop and symptom selectors — both controlled */}
      <div className="grid grid-cols-2 gap-3">
        <SelectField
          label={t("imageAnalysis.cropLabel")}
          value={crop}
          onChange={setCrop}
          options={CROP_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey) }))}
        />
        <SelectField
          label={t("imageAnalysis.problemLabel")}
          value={problem}
          onChange={setProblem}
          options={PROBLEM_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey) }))}
        />
      </div>

      <ModuleButton disabled={!file || processing} onClick={analyze}>
        {processing ? t("imageAnalysis.checking") : t("imageAnalysis.analyze")}
      </ModuleButton>

      {/* Demonstration result */}
      {result && (
        <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
          <DemoBadge status={t("imageAnalysis.possibleCause")} />
          <h2 className="mt-3 text-[16px] font-extrabold text-[#203C2E]">
            {t("imageAnalysis.resultTitle")}
          </h2>
          <p className="mt-2 text-[11px] leading-5 text-[#718379]">
            {t("imageAnalysis.resultBody")}
          </p>
          <div className="mt-3 rounded-xl bg-[#F3F6F2] p-3 text-[10px] leading-5 text-[#52675B]">
            <b>{t("imageAnalysis.nextSteps")}</b> {t("imageAnalysis.nextStepsBody")}
          </div>
        </section>
      )}
    </div>
  );
}
