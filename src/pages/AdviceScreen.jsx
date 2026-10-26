import Icon from "@/components/common/Icon";
import ScreenShell from "@/components/layout/ScreenShell";
import useApi from "@/hooks/useApi";

const DOMAIN_META = {
  crop:        { category: "Crop recommendation",  icon: "crop",       tone: "bg-[#E6F3E8] text-[#216B45]" },
  fertilizer:  { category: "Fertilizer guidance",  icon: "fertilizer", tone: "bg-[#FFF2DA] text-[#9A6817]" },
  irrigation:  { category: "Irrigation",           icon: "droplet",    tone: "bg-[#E5F3F7] text-[#28778A]" },
  yield:       { category: "Yield estimate",       icon: "chart",      tone: "bg-[#EAF1DE] text-[#657638]" },
};

function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  } catch {
    return "";
  }
}

function predictionTitle(item) {
  const pred = item.output?.prediction;
  if (!pred && pred !== 0) return item.domain;
  if (item.domain === "crop")       return `Recommended: ${pred}`;
  if (item.domain === "fertilizer") return `Use: ${pred}`;
  if (item.domain === "irrigation") return pred === 1 ? "Irrigate now" : "No irrigation needed";
  if (item.domain === "yield")      return `Yield estimate: ${Number(pred).toFixed(2)} t/ha`;
  return String(pred);
}

function predictionBody(item) {
  const inp = item.input ?? {};
  if (item.domain === "crop")
    return `N=${inp.N ?? "—"} P=${inp.P ?? "—"} K=${inp.K ?? "—"} · pH ${inp.ph ?? "—"} · ${inp.humidity ?? "—"}% humidity`;
  if (item.domain === "fertilizer")
    return `${inp.crop_type ?? "—"} on ${inp.soil_type ?? "—"} soil · N=${inp.nitrogen ?? "—"} K=${inp.potassium ?? "—"} P=${inp.phosphorous ?? "—"}`;
  if (item.domain === "irrigation")
    return `Soil moisture ${inp.soil_moisture ?? "—"} · ${inp.crop_type ?? "Paddy"} · day ${inp.crop_days ?? "—"}`;
  if (item.domain === "yield")
    return `${inp.crop ?? "—"} · ${inp.state_name ?? "—"} · ${inp.crop_year ?? "—"} · ${inp.area ?? "—"} ha`;
  return item.source === "baseline" ? "Rule-based baseline" : "ML prediction";
}

/**
 * Farming Advice screen — shows real prediction history from GET /api/predictions.
 */
export default function AdviceScreen({ navigate }) {
  const { data, loading, error, refetch } = useApi("/api/predictions?limit=10");
  const items = data?.items ?? [];

  return (
    <ScreenShell active="advice" navigate={navigate}>
      <div className="px-5 pb-7 pt-5">
        <header className="mb-6">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate("home")}
              aria-label="Back"
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[#DFE7E1] bg-white text-[#3F5A4B] active:scale-95"
            >
              <Icon name="arrow" size={18} className="rotate-180" />
            </button>
            <div className="flex-1">
              <p className="text-[11px] font-bold uppercase tracking-[.12em] text-[#5D7B6B]">FarmIQ insights</p>
              <h1 className="mt-0.5 text-[22px] font-extrabold tracking-[-0.04em] text-[#17392A]">Farming Advice</h1>
            </div>
            <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#E5F1E8] text-[#216B45]">
              <Icon name="sparkles" size={22} />
            </span>
          </div>
          <p className="mt-3 text-[12px] leading-5 text-[#718279]">
            {items.length > 0 ? `${items.length} recent predictions` : "Your AI predictions will appear here."}
          </p>
        </header>

        {loading && (
          <div className="space-y-3">
            {[1, 2, 3].map((n) => (
              <div key={n} className="h-32 animate-pulse rounded-[22px] bg-[#E8F0EB]" />
            ))}
          </div>
        )}

        {error && !loading && (
          <div className="rounded-[22px] bg-[#FCE9E5] p-4 text-center">
            <p className="text-[12px] font-bold text-[#9D4C3E]">{error.message || "Could not load predictions."}</p>
            <button onClick={refetch} className="mt-3 text-[11px] font-bold text-[#216B45] underline">Try again</button>
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="rounded-[22px] border border-dashed border-[#B0C9B8] p-8 text-center">
            <p className="text-[13px] font-bold text-[#3C5C49]">No predictions yet</p>
            <p className="mt-2 text-[11px] text-[#7B8C82]">
              Use the Crop, Fertilizer, Irrigation, or Yield modules to get your first AI prediction.
            </p>
            <button
              onClick={() => navigate("more")}
              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[#216B45] px-4 py-2 text-[12px] font-bold text-white"
            >
              <Icon name="sparkles" size={15} /> Explore modules
            </button>
          </div>
        )}

        <div className="space-y-3">
          {items.map((item) => {
            const meta = DOMAIN_META[item.domain] ?? DOMAIN_META.crop;
            return (
              <article
                key={item.id}
                className="rounded-[22px] border border-[#E3E9E4] bg-white p-4 shadow-[0_5px_18px_rgba(31,57,44,.045)]"
              >
                <div className="flex items-start gap-3">
                  <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-2xl ${meta.tone}`}>
                    <Icon name={meta.icon} size={22} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[10px] font-bold uppercase tracking-[.08em] text-[#7D8E84]">
                        {meta.category}
                      </p>
                      <span className="shrink-0 rounded-full bg-[#F0F5F1] px-2 py-1 text-[9px] font-bold text-[#4A715A]">
                        {item.source === "baseline" ? "Baseline" : "ML model"} · {formatDate(item.created_at)}
                      </span>
                    </div>
                    <h2 className="mt-2 text-[16px] font-extrabold text-[#203D2E]">
                      {predictionTitle(item)}
                    </h2>
                    <p className="mt-1.5 text-[11px] leading-[1.55] text-[#718178]">
                      {predictionBody(item)}
                    </p>
                  </div>
                </div>
                <button
                  className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-[#F0F6F1] text-[11px] font-bold text-[#216B45]"
                  onClick={() => navigate("chat")}
                >
                  <Icon name="sparkles" size={15} />
                  Ask FarmIQ
                  <Icon name="arrow" size={14} />
                </button>
              </article>
            );
          })}
        </div>
      </div>
    </ScreenShell>
  );
}
