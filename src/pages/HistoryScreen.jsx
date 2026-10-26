import { useState } from "react";
import Icon from "@/components/common/Icon";
import TextInput from "@/components/common/TextInput";
import ScreenShell from "@/components/layout/ScreenShell";
import useApi from "@/hooks/useApi";

const DOMAIN_STYLE = {
  crop:       { icon: "crop",       tone: "bg-[#E6F3E8] text-[#216B45]" },
  fertilizer: { icon: "fertilizer", tone: "bg-[#FFF2DA] text-[#9A6817]" },
  irrigation: { icon: "droplet",    tone: "bg-[#E5F3F7] text-[#28778A]" },
  yield:      { icon: "chart",      tone: "bg-[#EAF1DE] text-[#657638]" },
};

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60)         return "Just now";
  if (diff < 3600)       return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400)      return "Today";
  if (diff < 172800)     return "Yesterday";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function predictionSummary(item) {
  const pred = item.output?.prediction;
  if (item.domain === "crop")       return `Recommended: ${pred ?? "—"}`;
  if (item.domain === "fertilizer") return `Use: ${pred ?? "—"}`;
  if (item.domain === "irrigation") return pred === 1 ? "Irrigate now" : "No irrigation needed";
  if (item.domain === "yield")      return `Yield: ${pred != null ? Number(pred).toFixed(2) : "—"} t/ha`;
  return String(pred ?? "—");
}

function previewText(item) {
  const inp = item.input ?? {};
  if (item.domain === "crop")       return `N=${inp.N ?? "—"} P=${inp.P ?? "—"} K=${inp.K ?? "—"} · pH ${inp.ph ?? "—"}`;
  if (item.domain === "fertilizer") return `${inp.crop_type ?? "—"} on ${inp.soil_type ?? "—"} soil`;
  if (item.domain === "irrigation") return `Moisture ${inp.soil_moisture ?? "—"} · ${inp.crop_type ?? "Paddy"}`;
  if (item.domain === "yield")      return `${inp.crop ?? "—"} · ${inp.state_name ?? "—"}`;
  return "";
}

/**
 * Conversation History screen — shows prediction history from GET /api/predictions.
 */
export default function HistoryScreen({ navigate }) {
  const [query, setQuery] = useState("");
  const { data, loading, error, refetch } = useApi("/api/predictions?limit=50");
  const all = data?.items ?? [];

  const filtered = all.filter((item) => {
    const q = query.toLowerCase();
    return (
      item.domain.includes(q) ||
      predictionSummary(item).toLowerCase().includes(q) ||
      previewText(item).toLowerCase().includes(q)
    );
  });

  return (
    <ScreenShell active="history" navigate={navigate}>
      <div className="px-5 pb-7 pt-5">
        <header className="mb-5">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate("home")}
              aria-label="Back"
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[#DFE7E1] bg-white text-[#3F5A4B] active:scale-95"
            >
              <Icon name="arrow" size={18} className="rotate-180" />
            </button>
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[.12em] text-[#5D7B6B]">Your activity</p>
              <h1 className="text-[22px] font-extrabold tracking-[-0.04em] text-[#17392A]">Prediction History</h1>
            </div>
          </div>
          <p className="mt-2 text-[12px] text-[#718279]">All your past AI predictions in one place.</p>
        </header>

        <TextInput onChange={setQuery} placeholder="Search predictions..." value={query} />

        <div className="mb-3 mt-7 flex items-center justify-between">
          <h2 className="text-[14px] font-extrabold text-[#213D2F]">Past predictions</h2>
          <span className="text-[10px] font-semibold text-[#819087]">
            {loading ? "…" : `${filtered.length} results`}
          </span>
        </div>

        {loading && (
          <div className="space-y-2">
            {[1, 2, 3, 4].map((n) => (
              <div key={n} className="h-16 animate-pulse rounded-[18px] bg-[#E8F0EB]" />
            ))}
          </div>
        )}

        {error && !loading && (
          <div className="rounded-[22px] bg-[#FCE9E5] p-4 text-center">
            <p className="text-[12px] font-bold text-[#9D4C3E]">{error.message || "Could not load history."}</p>
            <button onClick={refetch} className="mt-3 text-[11px] font-bold text-[#216B45] underline">Try again</button>
          </div>
        )}

        {!loading && !error && (
          <div className="overflow-hidden rounded-[22px] border border-[#E2E9E4] bg-white">
            {filtered.length === 0 && (
              <div className="p-8 text-center text-sm text-[#7A8C82]">
                {all.length === 0 ? "No predictions yet. Try the Crop or Irrigation module." : "No results found."}
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
                  onClick={() => navigate("advice")}
                >
                  <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${style.tone}`}>
                    <Icon name={style.icon} size={19} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-bold text-[#263F32]">
                      {predictionSummary(item)}
                    </span>
                    <span className="mt-1 block truncate text-[10px] text-[#819087]">
                      {previewText(item)}
                    </span>
                  </span>
                  <span className="self-start whitespace-nowrap text-[9px] font-semibold text-[#95A198]">
                    {formatDate(item.created_at)}
                  </span>
                  <Icon name="chevron" size={15} className="text-[#9CA8A0]" />
                </button>
              );
            })}
          </div>
        )}

        <button
          className="mt-4 flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#216B45] text-[12px] font-bold text-white shadow-md"
          onClick={() => navigate("more")}
        >
          <Icon name="sparkles" size={16} /> Get new prediction
        </button>
      </div>
    </ScreenShell>
  );
}
