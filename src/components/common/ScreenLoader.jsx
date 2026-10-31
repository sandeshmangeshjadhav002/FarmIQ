import { useTranslation } from "react-i18next";

/**
 * Suspense fallback for lazily-loaded screens.
 *
 * Every page and every module panel is a separate chunk (see App.jsx and
 * ModuleScreen.jsx), so the first visit to each one briefly suspends. This is
 * deliberately tiny and dependency-free so the shell around it stays painted
 * while the chunk arrives.
 *
 * @param {object} props
 * @param {string} [props.label] - Message shown next to the spinner.
 */
export default function ScreenLoader({ label }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-[40vh] items-center justify-center px-6 py-10">
      <div className="flex items-center gap-3 rounded-2xl border border-white/40 bg-white/60 px-4 py-3 shadow-sm backdrop-blur-md">
        <span
          aria-hidden="true"
          className="h-4 w-4 animate-spin rounded-full border-2 border-[#216B45] border-t-transparent"
        />
        <span role="status" className="text-[12px] font-bold text-[#3F5A4B]">
          {label ?? t("common.loading")}
        </span>
      </div>
    </div>
  );
}
