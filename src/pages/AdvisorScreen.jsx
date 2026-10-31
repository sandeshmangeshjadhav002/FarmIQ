import { useTranslation } from "react-i18next";
import Icon from "@/components/common/Icon";
import ScreenShell from "@/components/layout/ScreenShell";
import { moduleByKey } from "@/data/modules";
import useApi from "@/hooks/useApi";

/**
 * AI Farm Advisor — one screen for every advisory task.
 *
 * Rather than making farmers find seven separate modules, this hub lists each
 * task as a shortcut. Every shortcut opens the existing tool unchanged, so the
 * ML models, forms, charts and upload flows are all reused as-is; only the way
 * they are reached changes. Anything whose inputs vary per field is asked for
 * inside that tool, not here.
 *
 * The "how" badge tells the farmer what will happen: a trained model runs, or
 * a deterministic guide is shown, or an image is uploaded for analysis.
 */
const TASKS = [
  { key: "crop-recommendation", task: "crop", how: "ml", tone: "ml" },
  { key: "soil", task: "soil", how: "guide", tone: "guide" },
  { key: "fertilizer", task: "fertilizer", how: "ml", tone: "ml" },
  { key: "irrigation", task: "irrigation", how: "ml", tone: "ml" },
  { key: "drought-management", task: "drought", how: "guide", tone: "guide" },
  { key: "organic-farming", task: "organic", how: "compare", tone: "guide" },
  { key: "image-analysis", task: "image", how: "image", tone: "image" },
];

const HOW_BADGE = {
  ml: "bg-[#E6F3E8] text-[#216B45]",
  guide: "bg-[#E5F3F7] text-[#28778A]",
  image: "bg-[#FCEBDD] text-[#A7602A]",
};

/**
 * @param {object}   props
 * @param {Function} props.navigate  - Navigate to a screen by key.
 * @param {Function} props.openModule - Open a module by key.
 * @param {object}   [props.user]    - Signed-in user.
 */
export default function AdvisorScreen({ navigate, openModule, user }) {
  const { t } = useTranslation();
  const { data: farms } = useApi("/api/farms?limit=1");
  const farm = farms?.items?.[0] ?? null;

  return (
    <ScreenShell active="advisor" navigate={navigate}>
      <div className="px-5 pb-7 pt-5">
        <header className="mb-5">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate("home")}
              aria-label={t("common.back")}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[#DFE7E1] bg-white text-[#3F5A4B] active:scale-95"
            >
              <Icon name="arrow" size={18} className="rotate-180" />
            </button>
            <div className="flex-1">
              <p className="text-[11px] font-bold uppercase tracking-[.12em] text-[#5D7B6B]">
                {t("advisor.kicker")}
              </p>
              <h1 className="mt-0.5 text-[22px] font-extrabold tracking-[-0.04em] text-[#17392A]">
                {t("advisor.headline")}
              </h1>
            </div>
            <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#E5F1E8] text-[#216B45]">
              <Icon name="sparkles" size={22} />
            </span>
          </div>
        </header>

        {/* Farm context — the advice below is framed around this farm. */}
        {farm && (
          <div className="mb-5 flex items-center gap-3 rounded-[20px] border border-white/40 bg-white/50 p-4 backdrop-blur-md shadow-sm">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#E5F1E8] text-[#216B45]">
              <Icon name="farm" size={19} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[9px] font-bold uppercase tracking-[.1em] text-[#7D8E84]">
                {t("advisor.advisingOn")}
              </p>
              <p className="truncate text-[13px] font-extrabold text-[#21412F]">
                {farm.name}
              </p>
              <p className="truncate text-[10px] text-[#819087]">
                {[farm.location, farm.current_crop]
                  .filter(Boolean)
                  .join(" · ") || t("advisor.locationCropNotSet")}
              </p>
            </div>
            <button
              onClick={() => openModule("farm-management")}
              className="shrink-0 rounded-xl bg-[#F0F6F1] px-3 py-2 text-[10px] font-bold text-[#216B45]"
            >
              {t("common.change")}
            </button>
          </div>
        )}

        {!farm && (
          <div className="mb-5 rounded-[20px] border border-dashed border-[#B0C9B8] p-4">
            <p className="text-[11px] font-bold text-[#3C5C49]">
              {t("advisor.noFarm")}
            </p>
            <p className="mt-1 text-[10px] leading-5 text-[#7B8C82]">
              {t("advisor.noFarmBody")}
            </p>
            <button
              onClick={() => openModule("farm-management")}
              className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-[#216B45] px-4 py-2 text-[11px] font-bold text-white"
            >
              <Icon name="plus" size={14} />
              {t("advisor.addFarm")}
            </button>
          </div>
        )}

        <h2 className="mb-3 text-[15px] font-extrabold text-[#1D382A]">
          {t("advisor.chooseTask")}
        </h2>

        <div className="space-y-3">
          {TASKS.map((task) => {
            const info = moduleByKey(task.key);
            return (
              <button
                key={task.key}
                onClick={() => openModule(task.key)}
                className="flex w-full items-center gap-3 rounded-[20px] border border-white/30 bg-white/40 p-4 text-left shadow-[0_4px_14px_rgba(31,57,44,.04)] backdrop-blur-md transition hover:-translate-y-0.5"
              >
                <span
                  className={`grid h-11 w-11 shrink-0 place-items-center rounded-2xl ${
                    info?.color ?? "bg-[#E6F2E9] text-[#216B45]"
                  }`}
                >
                  <Icon name={info?.icon ?? "sparkles"} size={21} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="text-[13px] font-extrabold text-[#233F31]">
                      {t(`advisor.tasks.${task.task}.title`)}
                    </span>
                  </span>
                  <span className="mt-1 block text-[10px] leading-4 text-[#75877D]">
                    {t(`advisor.tasks.${task.task}.body`)}
                  </span>
                  <span
                    className={`mt-2 inline-block rounded-full px-2 py-0.5 text-[8px] font-extrabold uppercase tracking-[.06em] ${
                      HOW_BADGE[task.tone]
                    }`}
                  >
                    {t(`advisor.how.${task.how}`)}
                  </span>
                </span>
                <Icon name="chevron" size={16} className="text-[#9CA8A0]" />
              </button>
            );
          })}
        </div>

        {/* Free-form assistant — one option among the tasks, not the only one. */}
        <button
          onClick={() => navigate("chat")}
          className="mt-5 flex w-full items-center gap-3 rounded-[20px] bg-[#216B45] p-4 text-left text-white shadow-[0_10px_24px_rgba(33,107,69,.2)]"
        >
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-white/15">
            <Icon name="bot" size={21} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[14px] font-extrabold">
              {t("advisor.freeformTitle")}
            </span>
            <span className="mt-0.5 block text-[10px] text-white/70">
              {t("advisor.freeformBody")}
            </span>
          </span>
          <Icon name="chevron" size={17} />
        </button>

        <button
          onClick={() => openModule("knowledge")}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl border border-[#DDE6DF] bg-white/60 py-3 text-[11px] font-bold text-[#216B45]"
        >
          <Icon name="book" size={15} />
          {t("advisor.browseKnowledge")}
        </button>
      </div>
    </ScreenShell>
  );
}
