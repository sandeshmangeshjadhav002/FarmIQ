import { useState } from "react";
import { useTranslation } from "react-i18next";
import Icon from "@/components/common/Icon";
import TextInput from "@/components/common/TextInput";
import ScreenShell from "@/components/layout/ScreenShell";
import useApi from "@/hooks/useApi";

const DOMAIN_STYLE = {
  crop: {
    icon: "crop",
    module: "crop-recommendation",
    tone: "bg-[#E6F3E8] text-[#216B45]",
  },
  fertilizer: {
    icon: "fertilizer",
    module: "fertilizer",
    tone: "bg-[#FFF2DA] text-[#9A6817]",
  },
  irrigation: {
    icon: "droplet",
    module: "irrigation",
    tone: "bg-[#E5F3F7] text-[#28778A]",
  },
  yield: {
    icon: "chart",
    module: "yield",
    tone: "bg-[#EAF1DE] text-[#657638]",
  },
};

function formatDate(iso, t) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return t("history.date.justNow");
  if (diff < 3600)
    return t("history.date.minutesAgo", { count: Math.floor(diff / 60) });
  if (diff < 86400) return t("history.date.today");
  if (diff < 172800) return t("history.date.yesterday");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function predictionSummary(item, t) {
  const pred = item.output?.prediction;
  if (item.domain === "crop")
    return t("history.summary.crop", { value: pred ?? "—" });
  if (item.domain === "fertilizer")
    return t("history.summary.fertilizer", { value: pred ?? "—" });
  if (item.domain === "irrigation")
    return pred === 1
      ? t("history.summary.irrigationNow")
      : t("history.summary.irrigationNone");
  if (item.domain === "yield")
    return t("history.summary.yield", {
      value: pred != null ? Number(pred).toFixed(2) : "—",
    });
  return String(pred ?? "—");
}

function previewText(item, t) {
  const inp = item.input ?? {};
  if (item.domain === "crop")
    return t("history.preview.nutrients", {
      n: inp.N ?? "—",
      p: inp.P ?? "—",
      k: inp.K ?? "—",
      ph: inp.ph ?? "—",
    });
  if (item.domain === "fertilizer")
    return t("history.preview.onSoil", {
      crop: inp.crop_type ?? "—",
      soil: inp.soil_type ?? "—",
    });
  if (item.domain === "irrigation")
    return t("history.preview.moisture", {
      value: inp.soil_moisture ?? "—",
      crop: inp.crop_type ?? t("history.preview.paddy"),
    });
  if (item.domain === "yield")
    return t("history.preview.cropState", {
      crop: inp.crop ?? "—",
      state: inp.state_name ?? "—",
    });
  return "";
}

/**
 * Prediction History screen — shows prediction history from GET /api/predictions.
 *
 * Part of the Insights & Analytics section. Tapping a record reopens the tool
 * that produced it rather than a second copy of the same list.
 *
 * @param {object}   props
 * @param {Function} props.navigate     - Navigate to a screen by key.
 * @param {Function} [props.openModule] - Open the tool behind a prediction.
 */
export default function HistoryScreen({ navigate, openModule }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const { data, loading, error, refetch } = useApi("/api/predictions?limit=50");
  const all = data?.items ?? [];

  const filtered = all.filter((item) => {
    const q = query.toLowerCase();
    return (
      item.domain.includes(q) ||
      predictionSummary(item, t).toLowerCase().includes(q) ||
      previewText(item, t).toLowerCase().includes(q)
    );
  });

  return (
    <ScreenShell active="insights" navigate={navigate}>
      <div className="px-5 pb-7 pt-5">
        <header className="mb-5 flex items-center gap-3">
          <button
            onClick={() => navigate("home")}
            aria-label={t("common.back")}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[#DFE7E1] bg-white text-[#3F5A4B] active:scale-95"
          >
            <Icon name="arrow" size={18} className="rotate-180" />
          </button>
          <h1 className="text-[22px] font-extrabold tracking-[-0.04em] text-[#17392A]">
            {t("history.title")}
          </h1>
        </header>

        <TextInput
          onChange={setQuery}
          placeholder={t("history.searchPlaceholder")}
          value={query}
        />

        <p className="mb-2 mt-4 text-right text-[10px] font-semibold text-[#819087]">
          {loading ? "…" : t("history.results", { count: filtered.length })}
        </p>

        {loading && (
          <div className="space-y-2">
            {[1, 2, 3, 4].map((n) => (
              <div
                key={n}
                className="h-16 animate-pulse rounded-[18px] bg-[#E8F0EB]"
              />
            ))}
          </div>
        )}

        {error && !loading && (
          <div className="rounded-[22px] bg-[#FCE9E5] p-4 text-center">
            <p className="text-[12px] font-bold text-[#9D4C3E]">
              {error.message || t("history.loadError")}
            </p>
            <button
              onClick={refetch}
              className="mt-3 text-[11px] font-bold text-[#216B45] underline"
            >
              {t("history.tryAgain")}
            </button>
          </div>
        )}

        {!loading && !error && (
          <div className="overflow-hidden rounded-[22px] border border-[#E2E9E4] bg-white">
            {filtered.length === 0 && (
              <div className="p-8 text-center text-sm text-[#7A8C82]">
                {all.length === 0
                  ? t("history.empty")
                  : t("history.noResults")}
              </div>
            )}
            {filtered.map((item, index) => {
              const style = DOMAIN_STYLE[item.domain] ?? DOMAIN_STYLE.crop;
              return (
                <button
                  key={item.id}
                  className={`flex w-full items-center gap-3 p-4 text-left transition hover:bg-[#F8FAF7] ${
                    index ? "border-t border-[#EDF1EE]" : ""
                  }`}
                  onClick={() => openModule?.(style.module)}
                >
                  <span
                    className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${style.tone}`}
                  >
                    <Icon name={style.icon} size={19} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-bold text-[#263F32]">
                      {predictionSummary(item, t)}
                    </span>
                    <span className="mt-1 block truncate text-[10px] text-[#819087]">
                      {previewText(item, t)}
                    </span>
                  </span>
                  <span className="self-start whitespace-nowrap text-[9px] font-semibold text-[#95A198]">
                    {formatDate(item.created_at, t)}
                  </span>
                  <Icon name="chevron" size={15} className="text-[#9CA8A0]" />
                </button>
              );
            })}
          </div>
        )}

        <button
          className="mt-4 flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#216B45] text-[12px] font-bold text-white shadow-md"
          onClick={() => navigate("advisor")}
        >
          <Icon name="sparkles" size={16} /> {t("history.newPrediction")}
        </button>
      </div>
    </ScreenShell>
  );
}
