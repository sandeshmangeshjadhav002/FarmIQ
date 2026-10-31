import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { DemoBadge, ModuleButton } from "./ModuleShared";
import ModuleIcon from "./ModuleIcon";

/**
 * Knowledge Center module — searchable article list with a detail view.
 *
 * @param {object}   props
 * @param {Function} props.onAsk - Navigate to the assistant screen.
 */
export default function KnowledgeCenter({ onAsk }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [article, setArticle] = useState(null);

  // Article/tag content lives in the translation files so it is available in
  // both English and Marathi; `returnObjects` keeps the array shape intact.
  const knowledgeTopicTags = t("data.knowledgeTopicTags", { returnObjects: true });

  const filteredArticles = useMemo(
    () =>
      t("data.knowledgeArticles", { returnObjects: true }).filter((item) =>
        item.join(" ").toLowerCase().includes(query.toLowerCase()),
      ),
    [query, t],
  );

  if (article) {
    const [title, category, source] = article;
    return (
      <div className="space-y-4">
        <button
          onClick={() => setArticle(null)}
          className="flex items-center gap-2 text-[11px] font-bold text-[#216B45]"
        >
          <ModuleIcon name="back" size={16} />
          {t("knowledgeCenter.backToArticles")}
        </button>

        <article className="rounded-[22px] border border-[#E0E8E2] bg-white p-5">
          <DemoBadge status={t("knowledgeCenter.verifiedSource")} />
          <h2 className="mt-4 text-[21px] font-extrabold leading-tight text-[#1D3A2B]">
            {title}
          </h2>
          <p className="mt-2 text-[10px] font-semibold text-[#789085]">
            {category} • {source}
          </p>
          <p className="mt-5 text-[12px] leading-6 text-[#4F6559]">
            {t("knowledgeCenter.assistantNote")}
          </p>
          <div className="mt-4 rounded-xl bg-[#F1F6F2] p-4 text-[11px] leading-5 text-[#486050]">
            <b>{t("knowledgeCenter.noteLabel")}</b>{" "}
            {t("knowledgeCenter.noteBody")}
          </div>
        </article>

        <ModuleButton onClick={onAsk}>
          {t("knowledgeCenter.askAboutArticle")}
        </ModuleButton>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Search */}
      <label className="flex h-12 items-center gap-3 rounded-2xl border border-[#DFE7E1] bg-white px-4">
        <ModuleIcon name="search" size={18} />
        <input
          aria-label={t("knowledgeCenter.searchAria")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="min-w-0 flex-1 bg-transparent text-[12px] outline-none"
          placeholder={t("knowledgeCenter.searchPlaceholder")}
        />
      </label>

      {/* Topic filter tags */}
      <div className="flex flex-wrap gap-2">
        {knowledgeTopicTags.map((tag) => (
          <button
            key={tag}
            onClick={() => setQuery(tag)}
            className="rounded-full border border-[#DDE6DF] bg-white px-3 py-2 text-[9px] font-bold text-[#567063]"
          >
            {tag}
          </button>
        ))}
      </div>

      {/* Article list */}
      <div className="overflow-hidden rounded-[22px] border border-[#E0E8E2] bg-white">
        {filteredArticles.length > 0 ? (
          filteredArticles.map(([title, category, source], index) => (
            <button
              key={title}
              onClick={() => setArticle([title, category, source])}
              className={`flex w-full items-center gap-3 p-4 text-left ${
                index ? "border-t border-[#EDF1EE]" : ""
              }`}
            >
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#E9F1EA] text-[#3C6A4D]">
                <ModuleIcon name="book" size={18} />
              </span>
              <span className="min-w-0 flex-1">
                <b className="block text-[12px] text-[#294234]">{title}</b>
                <span className="mt-1 block text-[9px] text-[#829188]">
                  {category} • {source}
                </span>
              </span>
              <ModuleIcon name="arrow" size={15} />
            </button>
          ))
        ) : (
          <p className="p-6 text-center text-[11px] text-[#829188]">
            {t("knowledgeCenter.noArticles")}
          </p>
        )}
      </div>
    </div>
  );
}
