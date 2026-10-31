/**
 * Alerts & Notifications
 *
 * Lists the alerts FarmIQ has derived from *your* account data — device
 * contact gaps, implausible sensor values, saved drought assessments and
 * baseline-only ML predictions.
 *
 * Design rules enforced here:
 * - Nothing is hardcoded: an account with no data sees an empty state, never
 *   sample rows.
 * - Alerts raised from simulated readings carry a DEMO badge.
 * - Priority, timestamp and read/unread state are always visible.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiPatch, apiPost } from "@/lib/apiClient";
import useApi from "@/hooks/useApi";
import ScreenLoader from "@/components/common/ScreenLoader";
import ModuleIcon from "./ModuleIcon";
import { DemoBadge, ModuleButton } from "./ModuleShared";

const PRIORITY = {
  critical: {
    labelKey: "alerts.priority.critical",
    card: "bg-[#FCE9E5] border-[#E8B4AE]",
    title: "text-[#8E3527]",
    badge: "bg-[#E8493B] text-white",
    dot: "bg-[#E8493B]",
  },
  high: {
    labelKey: "alerts.priority.high",
    card: "bg-[#FFF5DE] border-[#F0D090]",
    title: "text-[#8A6D2B]",
    badge: "bg-[#D99A2B] text-white",
    dot: "bg-[#D99A2B]",
  },
  medium: {
    labelKey: "alerts.priority.medium",
    card: "bg-[#E8EEF8] border-[#C0CDE8]",
    title: "text-[#3F5A90]",
    badge: "bg-[#4F6590] text-white",
    dot: "bg-[#4F6590]",
  },
  low: {
    labelKey: "alerts.priority.low",
    card: "bg-white border-[#E2E9E4]",
    title: "text-[#3F5A4B]",
    badge: "bg-[#7A9585] text-white",
    dot: "bg-[#7A9585]",
  },
};

const KIND_LABEL = {
  weather: "alerts.kind.weather",
  irrigation: "alerts.kind.irrigation",
  sensor: "alerts.kind.sensor",
  prediction: "alerts.kind.prediction",
  reminder: "alerts.kind.reminder",
};

const FILTERS = [
  { key: "all", labelKey: "alerts.filterAll" },
  { key: "unread", labelKey: "alerts.filterUnread" },
];

/** Short relative time (e.g. "12 min ago"). Returns "" for a missing date. */
function relativeTime(value, t) {
  if (!value) return "";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return t("alerts.justNow");
  if (minutes < 60) return t("alerts.minAgo", { count: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t("alerts.hAgo", { count: hours });
  const days = Math.round(hours / 24);
  return t("alerts.dAgo", { count: days });
}

export default function AlertsPanel() {
  const { t } = useTranslation();
  const [version, setVersion] = useState(0);
  const [filter, setFilter] = useState("all");
  const [items, setItems] = useState([]);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);

  const { data, loading, error } = useApi("/api/alerts", [version]);

  useEffect(() => {
    if (data?.items) setItems(data.items);
  }, [data]);

  // A 401 means the stored session expired; everything else is a transport or
  // server problem and is shown verbatim.
  const needsAuth = error?.status === 401;

  const runAction = async (fn) => {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      setVersion((v) => v + 1);
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  };

  const handleRefresh = () =>
    runAction(() => apiPost("/api/alerts/refresh", {}));

  const handleToggleRead = (alert) =>
    runAction(() =>
      apiPatch(`/api/alerts/${alert.id}`, { is_read: !alert.is_read }),
    );

  const handleReadAll = () =>
    runAction(() => apiPost("/api/alerts/read-all", {}));

  if (loading && items.length === 0) {
    return <ScreenLoader label={t("alerts.loading")} />;
  }

  const unreadCount = items.filter((a) => !a.is_read).length;
  const visible = filter === "unread" ? items.filter((a) => !a.is_read) : items;

  return (
    <div className="space-y-4">
      {/* ── Summary + actions ─────────────────────────────────────────── */}
      <section className="rounded-[22px] border border-white/40 bg-white/50 p-4 backdrop-blur-md shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[.08em] text-[#7A8B82]">
              {t("alerts.unread")}
            </p>
            <p className="mt-1 text-[26px] font-extrabold tracking-[-.03em] text-[#1D3A2B]">
              {unreadCount}
            </p>
            <p className="text-[9px] text-[#84938B]">
              {t("alerts.total", { count: items.length })}
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <ModuleButton onClick={handleRefresh} disabled={busy}>
              <ModuleIcon name="refresh" size={15} />
              {busy ? t("alerts.checking") : t("alerts.checkNow")}
            </ModuleButton>
            <ModuleButton
              secondary
              onClick={handleReadAll}
              disabled={busy || unreadCount === 0}
            >
              {t("alerts.markAllRead")}
            </ModuleButton>
          </div>
        </div>

        <p className="mt-3 text-[9px] leading-relaxed text-[#84938B]">
          {t("alerts.basedOnData")}
        </p>

        <div className="mt-3 flex gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`h-8 rounded-full px-3 text-[10px] font-extrabold transition ${
                filter === f.key
                  ? "bg-[#216B45] text-white"
                  : "border border-[#D9E4DC] bg-white text-[#216B45]"
              }`}
            >
              {t(f.labelKey)}
            </button>
          ))}
        </div>
      </section>

      {/* ── Errors ────────────────────────────────────────────────────── */}
      {needsAuth && <Notice tone="amber">{t("alerts.signIn")}</Notice>}
      {error && !needsAuth && (
        <Notice tone="red">{error.message || t("alerts.loadError")}</Notice>
      )}
      {actionError && <Notice tone="red">{actionError.message}</Notice>}

      {/* ── List ──────────────────────────────────────────────────────── */}
      {visible.length === 0 ? (
        <EmptyState filter={filter} hasAny={items.length > 0} />
      ) : (
        <ul className="space-y-3">
          {visible.map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              busy={busy}
              onToggleRead={() => handleToggleRead(alert)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function AlertCard({ alert, busy, onToggleRead }) {
  const { t } = useTranslation();
  const tone = PRIORITY[alert.priority] || PRIORITY.low;
  return (
    <li
      className={`rounded-[20px] border p-4 ${tone.card} ${
        alert.is_read ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-start gap-2">
        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${tone.dot}`} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span
              className={`rounded-full px-2 py-[3px] text-[8px] font-extrabold uppercase tracking-[.06em] ${tone.badge}`}
            >
              {t(tone.labelKey)}
            </span>
            <span className="rounded-full bg-white/70 px-2 py-[3px] text-[8px] font-extrabold uppercase tracking-[.06em] text-[#52665B]">
              {KIND_LABEL[alert.kind] ? t(KIND_LABEL[alert.kind]) : alert.kind}
            </span>
            {alert.is_demo && <DemoBadge status={t("alerts.simulatedData")} />}
          </div>

          <h3
            className={`mt-2 text-[13px] font-extrabold leading-snug ${tone.title}`}
          >
            {alert.title}
          </h3>
          {alert.body && (
            <p className="mt-1 text-[11px] leading-relaxed text-[#4A5F53]">
              {alert.body}
            </p>
          )}
          {alert.reason && (
            <p className="mt-2 rounded-xl bg-white/60 px-2.5 py-2 text-[9px] leading-relaxed text-[#6D7F74]">
              <span className="font-extrabold">{t("alerts.why")}</span> {alert.reason}
            </p>
          )}

          <div className="mt-3 flex items-center justify-between gap-2">
            <span className="text-[9px] font-semibold text-[#84938B]">
              {relativeTime(alert.created_at, t) ||
                (alert.is_read ? t("alerts.read") : t("alerts.unread"))}
            </span>
            <button
              onClick={onToggleRead}
              disabled={busy}
              className="rounded-full border border-[#D9E4DC] bg-white px-3 py-1 text-[9px] font-extrabold text-[#216B45] transition active:scale-[.98] disabled:opacity-50"
            >
              {alert.is_read ? t("alerts.markUnread") : t("alerts.markRead")}
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}

function EmptyState({ filter, hasAny }) {
  const { t } = useTranslation();
  const unreadFilter = filter === "unread";
  return (
    <div className="rounded-[22px] border border-[#E2E9E4] bg-white p-6 text-center">
      <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[#EAF6EF] text-[#216B45]">
        <ModuleIcon name="bell" size={20} />
      </span>
      <h3 className="mt-3 text-[13px] font-extrabold text-[#1D3A2B]">
        {unreadFilter && hasAny
          ? t("alerts.noUnreadAlerts")
          : t("alerts.noAlerts")}
      </h3>
      <p className="mx-auto mt-1 max-w-[260px] text-[10px] leading-relaxed text-[#7B8C82]">
        {unreadFilter && hasAny
          ? t("alerts.noUnreadBody")
          : t("alerts.noAlertsBody")}
      </p>
    </div>
  );
}

function Notice({ tone, children }) {
  const tones = {
    red: "border-[#E8B4AE] bg-[#FCE9E5] text-[#8E3527]",
    amber: "border-[#F0D090] bg-[#FFF5DE] text-[#8A6D2B]",
  };
  return (
    <div
      className={`rounded-2xl border p-3 text-[10px] font-semibold ${tones[tone]}`}
    >
      {children}
    </div>
  );
}
