import { lazy, Suspense } from "react";
import Icon from "@/components/common/Icon";
import Logo from "@/components/common/Logo";
import { PrimaryButton } from "@/components/common/Button";
import ScreenShell from "@/components/layout/ScreenShell";
import { quickActions } from "@/data/modules";
import useApi from "@/hooks/useApi";

const FarmActionPlan = lazy(() =>
  import("@/components/modules/FarmActionPlan"),
);

/**
 * Home screen.
 *
 * Prioritised for a farmer opening the app:
 *   1. Today's most important action   (the unified Farm Action Plan)
 *   2. Current farm conditions
 *   3. Relevant alerts
 *   4. AI Advisor shortcuts
 *   5. Recent prediction results
 *
 * Every number shown comes from a real record. A brand-new account sees a
 * farm-setup workflow instead of zero-valued cards.
 *
 * @param {object}   props
 * @param {Function} props.navigate         - Navigate to a screen by key.
 * @param {string}   props.language         - Currently selected language label.
 * @param {Function} props.openLanguages    - Open the language sheet.
 * @param {Function} props.openModule       - Open a module by its key.
 * @param {object}   [props.user]           - Logged-in user data.
 * @param {Function} props.onOpenProfile    - Open the profile panel.
 */
export default function HomeScreen({
  navigate,
  language,
  openLanguages,
  openModule,
  user,
  onOpenProfile,
}) {
  /** Generate up-to-2-char initials from a full name string. */
  const initials = (name = "?") =>
    name
      .trim()
      .split(/\s+/)
      .map((w) => w[0]?.toUpperCase() ?? "")
      .slice(0, 2)
      .join("");

  const { data: dash, loading: dashLoading } = useApi("/api/dashboard/summary");
  const { data: alerts } = useApi("/api/alerts?unread_only=true&limit=3");
  const { data: predictions } = useApi("/api/predictions?limit=2");

  const hasFarm = (dash?.farms ?? 0) > 0;
  const unread = alerts?.unread ?? 0;
  const recentPredictions = predictions?.items ?? [];

  // Only include statistics that are backed by real records.
  const stats = [];
  if ((dash?.farms ?? 0) > 0) stats.push(["Farms", dash.farms]);
  if ((dash?.devices_online ?? 0) > 0)
    stats.push(["Sensors online", dash.devices_online]);
  if ((dash?.predictions ?? 0) > 0)
    stats.push(["Predictions", dash.predictions]);

  return (
    <ScreenShell active="home" navigate={navigate}>
      <div className="px-5 pb-6 pt-5">
        <header className="flex items-center justify-between gap-2">
          <Logo />
          <div className="flex items-center gap-2">
            <button
              className="flex h-10 items-center gap-2 rounded-full border border-white/30 bg-white/40 px-3 text-[11px] font-bold text-[#345443] backdrop-blur-md shadow-sm"
              onClick={openLanguages}
            >
              <Icon name="language" size={17} />
              {language}
            </button>
            <button
              aria-label="Open profile"
              onClick={onOpenProfile}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#216B45] text-[13px] font-extrabold text-white shadow-[0_2px_8px_rgba(33,107,69,.3)] transition hover:bg-[#1a5738] active:scale-95 select-none"
            >
              {user ? (
                initials(user.full_name)
              ) : (
                <Icon name="person" size={18} />
              )}
            </button>
          </div>
        </header>

        <section className="pb-4 pt-7">
          <h1 className="max-w-[320px] text-[26px] font-extrabold leading-[1.14] tracking-[-0.04em] text-[#17392A]">
            What needs your attention today?
          </h1>
        </section>

        <PrimaryButton onClick={() => navigate("chat")}>
          <Icon name="mic" size={21} />
          Ask FarmIQ
        </PrimaryButton>

        {/* ── 1. Today's plan, or the setup workflow for a new account ── */}
        <div className="mt-7">
          {dashLoading ? (
            <div className="space-y-3">
              <div className="h-5 w-48 animate-pulse rounded-full bg-[#E8F0EB]" />
              {[1, 2].map((n) => (
                <div
                  key={n}
                  className="h-24 animate-pulse rounded-[20px] bg-[#E8F0EB]"
                />
              ))}
            </div>
          ) : hasFarm ? (
            <Suspense
              fallback={
                <div className="space-y-2">
                  {[1, 2].map((n) => (
                    <div
                      key={n}
                      className="h-24 animate-pulse rounded-[20px] bg-[#E8F0EB]"
                    />
                  ))}
                </div>
              }
            >
              <FarmActionPlan openModule={openModule} />
            </Suspense>
          ) : (
            <SetupWorkflow openModule={openModule} />
          )}
        </div>

        {/* ── 2. Current farm conditions (real records only) ── */}
        {hasFarm && stats.length > 0 && (
          <>
            <h2 className="mb-3 mt-7 text-[15px] font-extrabold text-[#1D382A]">
              Your farm today
            </h2>
            <div className="flex rounded-[20px] border border-white/40 bg-white/50 p-4 backdrop-blur-md shadow-sm">
              {stats.map(([label, value], i) => (
                <div
                  key={label}
                  className={`flex-1 text-center ${
                    i ? "border-l border-white/30" : ""
                  }`}
                >
                  <b className="block text-[20px] font-extrabold text-[#17392A]">
                    {value}
                  </b>
                  <span className="text-[10px] text-[#7B8C82]">{label}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {/* ── 3. Relevant alerts ── */}
        {unread > 0 && (
          <button
            onClick={() => openModule("alerts")}
            className="mt-4 flex w-full items-center gap-3 rounded-[20px] border border-[#F0C9C0] bg-[#FDF1EE] p-4 text-left"
          >
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-[#FCE9E5] text-[#A55243]">
              <Icon name="bell" size={20} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-extrabold text-[#8E4536]">
                {unread} unread alert{unread > 1 ? "s" : ""}
              </span>
              <span className="mt-1 block truncate text-[10px] text-[#A5746A]">
                {alerts?.items?.[0]?.title ??
                  "Weather, sensor and market updates"}
              </span>
            </span>
            <Icon name="chevron" size={16} className="text-[#A55243]" />
          </button>
        )}

        {/* ── 4. AI Advisor shortcuts ── */}
        <div className="mb-3 mt-7 flex items-center justify-between">
          <h2 className="text-[15px] font-extrabold text-[#1D382A]">
            AI Advisor shortcuts
          </h2>
          <button
            onClick={() => navigate("advisor")}
            className="text-[11px] font-bold text-[#216B45]"
          >
            See all
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {quickActions.map((action) => (
            <button
              key={action.title}
              className="group min-h-[120px] rounded-[20px] border border-white/30 bg-white/40 p-4 text-left shadow-[0_5px_18px_rgba(31,57,44,.05)] backdrop-blur-md transition hover:-translate-y-0.5 hover:shadow-md active:scale-[.98]"
              onClick={() => openModule(action.target)}
            >
              <span
                className={`mb-4 grid h-10 w-10 place-items-center rounded-xl ${action.color}`}
              >
                <Icon name={action.icon} size={20} />
              </span>
              <span className="block text-[14px] font-bold text-[#1D382A]">
                {action.title}
              </span>
              <span className="mt-1 block text-[11px] leading-4 text-[#7C8E84]">
                {action.subtitle}
              </span>
            </button>
          ))}
        </div>

        {/* ── 5. Recent prediction results (real records only) ── */}
        {recentPredictions.length > 0 && (
          <>
            <div className="mb-3 mt-7 flex items-center justify-between">
              <h2 className="text-[15px] font-extrabold text-[#1D382A]">
                Recent predictions
              </h2>
              <button
                onClick={() => navigate("history")}
                className="text-[11px] font-bold text-[#216B45]"
              >
                View all
              </button>
            </div>
            <div className="overflow-hidden rounded-[20px] border border-[#E2E9E4] bg-white">
              {recentPredictions.map((item, index) => (
                <button
                  key={item.id}
                  onClick={() => navigate("history")}
                  className={`flex w-full items-center gap-3 p-4 text-left transition hover:bg-[#F8FAF7] ${
                    index ? "border-t border-[#EDF1EE]" : ""
                  }`}
                >
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#E9EAF7] text-[#575E95]">
                    <Icon name="sparkles" size={19} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-bold text-[#263F32]">
                      {predictionSummary(item)}
                    </span>
                  </span>
                  <Icon name="chevron" size={15} className="text-[#9CA8A0]" />
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </ScreenShell>
  );
}

/** Human-readable one-liner for a stored prediction. */
function predictionSummary(item) {
  const pred = item.output?.prediction;
  if (item.domain === "crop") return `Recommended crop: ${pred ?? "—"}`;
  if (item.domain === "fertilizer") return `Fertilizer: ${pred ?? "—"}`;
  if (item.domain === "irrigation")
    return pred === 1 ? "Irrigation: water now" : "Irrigation: not needed";
  if (item.domain === "yield")
    return `Yield estimate: ${
      pred != null ? Number(pred).toFixed(2) : "—"
    } t/ha`;
  return String(pred ?? item.domain ?? "Prediction");
}

/**
 * First-run workflow shown instead of zero-valued cards.
 *
 * The steps mirror what the app actually needs to give useful advice: a farm,
 * then a sensor or a prediction. Only the first step is actionable here because
 * the others live inside those screens.
 */
function SetupWorkflow({ openModule }) {
  const steps = [
    { label: "Add your farm", done: false },
    { label: "Connect a sensor or add soil readings", done: false },
    { label: "Get your first AI recommendation", done: false },
  ];

  return (
    <div className="rounded-[22px] border border-[#D8E4DC] bg-white/60 p-5 backdrop-blur-md shadow-sm">
      <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#E5F1E8] text-[#216B45]">
        <Icon name="farm" size={21} />
      </span>
      <h2 className="mt-3 text-[16px] font-extrabold text-[#1D382A]">
        Set up your farm
      </h2>
      <p className="mt-1.5 text-[11px] leading-5 text-[#6F8378]">
        FarmIQ needs a farm before it can give advice. This takes a minute.
      </p>
      <ol className="mt-4 space-y-2.5">
        {steps.map((step, i) => (
          <li key={step.label} className="flex items-start gap-3">
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#E8F3EA] text-[10px] font-extrabold text-[#216B45]">
              {i + 1}
            </span>
            <span className="text-[11px] leading-6 text-[#3F5A4B]">
              {step.label}
            </span>
          </li>
        ))}
      </ol>
      <button
        onClick={() => openModule("farm-management")}
        className="mt-4 flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#216B45] text-[12px] font-extrabold text-white shadow-[0_6px_16px_rgba(33,107,69,.18)]"
      >
        <Icon name="plus" size={17} />
        Add your first farm
      </button>
    </div>
  );
}
