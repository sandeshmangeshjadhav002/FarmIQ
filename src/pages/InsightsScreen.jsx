import Icon from "@/components/common/Icon";
import ScreenShell from "@/components/layout/ScreenShell";
import { canAccessAdminTools, moduleByKey } from "@/data/modules";
import useApi from "@/hooks/useApi";

/** Section tools that have real analytics behind them. */
const TOOLS = ["yield", "market", "reports"];

/**
 * Insights & Analytics — Yield, market, reports, prediction history and (for
 * the authorised role) real model-evaluation results.
 *
 * Every number here comes from an actual database record or the stored
 * evaluation report. When there is nothing to show, an honest empty state is
 * rendered instead of a zero-valued card.
 */
export default function InsightsScreen({ navigate, openModule, user }) {
  const { data: predictions, loading } = useApi("/api/predictions?limit=3");
  const total = predictions?.total ?? 0;

  // Only fetch model health for the role that may act on it.
  const isAdmin = canAccessAdminTools(user);
  const { data: evaluation } = useApi(
    isAdmin ? "/api/mlops/evaluation/summary" : null,
  );

  return (
    <ScreenShell active="insights" navigate={navigate}>
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
            <h1 className="flex-1 text-[22px] font-extrabold tracking-[-0.04em] text-[#17392A]">
              Measure your farm
            </h1>
            <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#E5F1E8] text-[#216B45]">
              <Icon name="chart" size={22} />
            </span>
          </div>
        </header>

        {/* Prediction count — only shown when real records exist. */}
        {total > 0 && (
          <div className="mb-5 flex items-center gap-4 rounded-[20px] border border-white/40 bg-white/50 p-4 backdrop-blur-md shadow-sm">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-[#E9EAF7] text-[#575E95]">
              <Icon name="report" size={22} />
            </span>
            <div>
              <b className="block text-[24px] font-extrabold leading-none text-[#17392A]">
                {total}
              </b>
              <span className="mt-1 block text-[10px] font-semibold text-[#7B8C82]">
                prediction{total === 1 ? "" : "s"} saved on your account
              </span>
            </div>
          </div>
        )}

        <h2 className="mb-3 text-[15px] font-extrabold text-[#1D382A]">
          Analysis tools
        </h2>
        <div className="grid grid-cols-2 gap-3">
          {TOOLS.map((key) => {
            const info = moduleByKey(key);
            return (
              <button
                key={key}
                onClick={() => openModule(key)}
                className="min-h-[124px] rounded-[20px] border border-white/30 bg-white/40 p-4 text-left shadow-[0_5px_18px_rgba(31,57,44,.05)] backdrop-blur-md transition hover:-translate-y-0.5"
              >
                <span
                  className={`mb-4 grid h-10 w-10 place-items-center rounded-xl ${
                    info?.color ?? "bg-[#E6F2E9] text-[#216B45]"
                  }`}
                >
                  <Icon name={info?.icon ?? "chart"} size={20} />
                </span>
                <span className="block text-[13px] font-bold text-[#1D382A]">
                  {info?.title ?? key}
                </span>
                <span className="mt-1 block text-[10px] leading-4 text-[#7C8E84]">
                  {info?.short}
                </span>
              </button>
            );
          })}
        </div>

        {/* Prediction history */}
        <button
          onClick={() => navigate("history")}
          className="mt-3 flex w-full items-center gap-3 rounded-[20px] border border-white/40 bg-white/50 p-4 text-left backdrop-blur-md shadow-sm"
        >
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-[#E9EAF7] text-[#575E95]">
            <Icon name="history" size={20} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-extrabold text-[#21412F]">
              Prediction history
            </span>
            <span className="mt-1 block text-[10px] text-[#718279]">
              Every past prediction, searchable
            </span>
          </span>
          <Icon name="chevron" size={16} className="text-[#216B45]" />
        </button>

        {/* First-run guidance only — past predictions live on their own screen. */}
        {!loading && total === 0 && (
          <div className="mt-7 rounded-[20px] border border-dashed border-[#B0C9B8] p-6 text-center">
            <p className="text-[12px] font-bold text-[#3C5C49]">
              No predictions yet
            </p>
            <p className="mt-1.5 text-[10px] leading-5 text-[#7B8C82]">
              Run a crop, fertilizer, irrigation or yield prediction to start
              building your farm's history.
            </p>
            <button
              onClick={() => navigate("advisor")}
              className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-[#216B45] px-4 py-2 text-[11px] font-bold text-white"
            >
              <Icon name="sparkles" size={14} />
              Open AI Farm Advisor
            </button>
          </div>
        )}

        {/* Model evaluation — authorised roles only. */}
        {isAdmin && (
          <div className="mt-7">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[15px] font-extrabold text-[#1D382A]">
                Model evaluation
              </h2>
              <button
                onClick={() => openModule("mlops")}
                className="text-[11px] font-bold text-[#216B45]"
              >
                Full report
              </button>
            </div>
            <div className="rounded-[20px] border border-[#E0E8E2] bg-white p-4">
              <p className="text-[10px] leading-5 text-[#718279]">
                Real held-out metrics from{" "}
                <code className="text-[9px]">
                  ml/reports/evaluation_report.json
                </code>
                {evaluation?.evaluation_date
                  ? ` · evaluated ${evaluation.evaluation_date}`
                  : ""}
              </p>
              <div className="mt-3 space-y-2">
                {(evaluation?.domains ?? []).map((d) => (
                  <div
                    key={d.domain}
                    className="flex items-center justify-between border-t border-[#EDF1EE] pt-2 first:border-0 first:pt-0"
                  >
                    <span className="text-[11px] font-bold capitalize text-[#294234]">
                      {d.domain}
                    </span>
                    <span className="text-right text-[10px] text-[#7B8C82]">
                      {!d.available
                        ? "Not available"
                        : d.accuracy != null
                        ? `accuracy ${(d.accuracy * 100).toFixed(1)}%`
                        : d.r2_log != null
                        ? `R² (log) ${Number(d.r2_log).toFixed(3)}`
                        : "—"}
                    </span>
                  </div>
                ))}
                {!evaluation && (
                  <p className="text-[10px] text-[#9AA79F]">
                    Loading stored metrics…
                  </p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </ScreenShell>
  );
}
