import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiPost } from "@/lib/apiClient";
import { DEFAULT_LANGUAGE, normalizeLanguage, readStoredLanguage } from "@/i18n/language";
import ModuleIcon from "./ModuleIcon";

// The four labelled lines the assistant is asked to return, in display order.
// Each canonical key maps to a translation key under
// ``predictionExplanation.labels`` so the section headings are shown in the
// farmer's own language even though the model returns the content.
const LABEL_KEYS = ["explanation", "keyFactors", "nextStep", "limitations"];

// English label text, used as a fallback when the assistant answers with the
// English label instead of the localised one.
const CANONICAL_LABELS = {
  explanation: "Explanation",
  keyFactors: "Key factors",
  nextStep: "Next step",
  limitations: "Limitations",
};

/**
 * PredictionExplanation — a plain-language explanation of a finished ML
 * prediction, produced by the existing RAG assistant.
 *
 * The ML model stays the only source of the prediction: this component never
 * changes, replaces or "improves" the result. It sends the model's own output
 * to ``POST /api/chat`` as ``ml_results`` and asks for a short, farmer-friendly
 * explanation. If the assistant is unavailable (503), the session has expired
 * (401) or the request fails, the original prediction stays on screen and only
 * a muted note is shown here — the prediction is never blocked by the AI.
 *
 * @param {object}   props
 * @param {string}   props.moduleKey - ML module key ("crop-recommendation"…).
 * @param {object}   props.result    - Raw ML response from the backend.
 * @param {object}   props.input     - The exact inputs that produced the result.
 * @param {string}   [props.farmName]- Optional farm the prediction was for.
 * @param {Function} [props.onAsk]   - Open the full assistant for follow-ups.
 */
export default function PredictionExplanation({
  moduleKey,
  result,
  input,
  farmName,
  onAsk,
}) {
  const { t, i18n } = useTranslation();
  // The selected interface language ("en" | "mr"). The explanation is requested
  // in this language, but the prediction values themselves are never touched.
  const language =
    normalizeLanguage(i18n.resolvedLanguage || i18n.language) ||
    readStoredLanguage() ||
    DEFAULT_LANGUAGE;
  const [state, setState] = useState("idle"); // idle | loading | done | error
  const [answer, setAnswer] = useState("");
  const [errorNote, setErrorNote] = useState("");
  const [attempt, setAttempt] = useState(0);

  // One stable identity per prediction. Without it the effect would re-fire on
  // every parent re-render and burn an LLM call each time.
  const resultKey = useMemo(
    () => JSON.stringify({ moduleKey, result }),
    [moduleKey, result],
  );

  useEffect(() => {
    if (!result || !resultKey) return;
    let cancelled = false;
    setState("loading");
    setAnswer("");
    setErrorNote("");

    const prediction =
      result.label ?? result.prediction ?? result.details?.top?.[0]?.crop;

    // Ask for the reply in the selected language. The four labels are taken
    // from the translation file so the assistant structures its answer the same
    // way in both languages; ``parseAnswer`` accepts either the localised or
    // the English label.
    const labelText = LABEL_KEYS.map((key) =>
      t(`predictionExplanation.labels.${key}`),
    );
    const languageName =
      language === "mr" ? "Marathi (Devanagari script, मराठी)" : "English";

    const message =
      `Explain this farm prediction for a farmer. Write the reply in ${languageName}. ` +
      "Use the numbers, units and prediction exactly as given — never change or invent a value. " +
      "Reply with exactly four short labelled lines and nothing else:\n" +
      `${labelText[0]}: <one sentence on what the result means>\n` +
      `${labelText[1]}: <the inputs that most influenced it>\n` +
      `${labelText[2]}: <one practical action>\n` +
      `${labelText[3]}: <what this prediction cannot tell the farmer>`;

    apiPost("/api/chat", {
      message,
      language,
      ml_results: {
        source: "farmiq_ml_model",
        domain: moduleKey,
        prediction,
        model_source: result.source ?? "model",
        inputs: input ?? {},
        farm: farmName ?? null,
      },
      top_k: 4,
    })
      .then((res) => {
        if (cancelled) return;
        setAnswer(res?.answer ?? "");
        setState("done");
      })
      .catch((err) => {
        if (cancelled) return;
        setState("error");
        setErrorNote(
          err?.status === 503
            ? t("predictionExplanation.errors.unavailable")
            : err?.status === 401
            ? t("predictionExplanation.errors.sessionExpired")
            : t("predictionExplanation.errors.unreachable"),
        );
      });

    return () => {
      cancelled = true;
    };
    // `attempt` lets the farmer retry without re-running the prediction;
    // `language` re-requests the explanation when the farmer switches language.
  }, [resultKey, attempt, language]); // eslint-disable-line react-hooks/exhaustive-deps

  // Map every label we may receive back (localised + English fallback) to its
  // canonical key, so the section headings can be rendered from the dictionary.
  const labelMap = useMemo(() => {
    const map = new Map();
    LABEL_KEYS.forEach((key) => {
      map.set(t(`predictionExplanation.labels.${key}`), key);
      map.set(CANONICAL_LABELS[key], key);
    });
    return map;
  }, [t, language]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!result) return null;

  const sections = state === "done" ? parseAnswer(answer, labelMap) : [];

  return (
    <section className="rounded-[22px] border border-[#D8E4DC] bg-white p-4">
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-[#E5F1E8] text-[#216B45]">
          <ModuleIcon name="sparkles" size={15} />
        </span>
        <h3 className="flex-1 text-[12px] font-extrabold text-[#213D2F]">
          {t("predictionExplanation.title")}
        </h3>
        <span className="rounded-full bg-[#F0F5F1] px-2 py-0.5 text-[8px] font-extrabold uppercase tracking-[.06em] text-[#5C7A67]">
          {t("predictionExplanation.badge")}
        </span>
      </div>

      {state === "loading" && (
        <div className="mt-3 space-y-2">
          {[1, 2, 3].map((n) => (
            <div
              key={n}
              className="h-3.5 animate-pulse rounded-full bg-[#EEF3EF]"
              style={{ width: `${90 - n * 12}%` }}
            />
          ))}
        </div>
      )}

      {state === "error" && (
        <div className="mt-3">
          <p className="text-[10px] leading-5 text-[#8A6D2B]">{errorNote}</p>
          <p className="mt-1 text-[9px] text-[#9AA79F]">
            {t("predictionExplanation.unchanged")}
          </p>
          <button
            onClick={() => setAttempt((n) => n + 1)}
            className="mt-2 text-[10px] font-bold text-[#216B45] underline"
          >
            {t("predictionExplanation.tryAgain")}
          </button>
        </div>
      )}

      {state === "done" && sections.length === 0 && (
        <p className="mt-3 text-[11px] leading-5 text-[#4F6A5C]">{answer}</p>
      )}

      {state === "done" && sections.length > 0 && (
        <dl className="mt-3 space-y-2.5">
          {sections.map((s, i) => (
            <div key={`${s.key}-${i}`}>
              <dt className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8C82]">
                {titleCase(t(`predictionExplanation.labels.${s.key}`))}
              </dt>
              <dd className="mt-0.5 text-[11px] leading-5 text-[#42594C]">
                {s.text}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {state === "done" && (
        <div className="mt-3 flex items-center justify-between border-t border-[#EDF1EE] pt-2.5">
          <p className="text-[9px] text-[#9AA79F]">
            {t("predictionExplanation.footerNote")}
          </p>
          {onAsk && (
            <button
              onClick={onAsk}
              className="text-[10px] font-bold text-[#216B45]"
            >
              {t("predictionExplanation.askMore")}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Match a reply line against the labels the assistant was asked to use.
 *
 * Handles both the localised label (Marathi) and the English fallback, and both
 * the ASCII colon and the full-width colon an LLM may emit. Returns the
 * canonical key plus the text after the colon, or ``null`` when the line is not
 * a label.
 */
function matchLabel(line, labelMap) {
  const lower = line.toLowerCase();
  for (const [label, key] of labelMap) {
    const base = String(label).toLowerCase();
    if (lower.startsWith(`${base}:`)) {
      return { key, rest: line.slice(base.length + 1).trim() };
    }
    if (lower.startsWith(`${base}：`)) {
      return { key, rest: line.slice(base.length + 1).trim() };
    }
  }
  return null;
}

/**
 * Split the assistant's reply into labelled sections.
 *
 * The assistant is asked for four labelled lines, but an LLM may return prose,
 * bold markers or bullets instead. Unrecognised lines are appended to the
 * current section, and a reply with no recognisable label is treated as one
 * "Explanation" block — the text is always shown as written, never rewritten.
 */
function parseAnswer(answer, labelMap) {
  const text = String(answer ?? "").trim();
  if (!text) return [];

  const sections = [];
  let current = null;

  for (const raw of text.split(/\r?\n/)) {
    const line = raw
      .trim()
      .replace(/\*\*/g, "")
      .replace(/^[-*•]\s*/, "")
      .trim();
    if (!line) continue;

    const matched = matchLabel(line, labelMap);
    if (matched) {
      current = { key: matched.key, text: matched.rest };
      sections.push(current);
    } else if (current) {
      current.text += current.text ? ` ${line}` : line;
    } else {
      current = { key: "explanation", text: line };
      sections.push(current);
    }
  }

  // A single block needs no reordering; multiple blocks are shown in the
  // sequence the assistant was asked to use.
  if (sections.length <= 1) return sections;
  return sections.sort(
    (a, b) => LABEL_KEYS.indexOf(a.key) - LABEL_KEYS.indexOf(b.key),
  );
}

/**
 * English section headings are title-cased for display ("Key factors" →
 * "Key Factors"). Case conversion is a no-op for Marathi, so this is safe to
 * apply to either language.
 */
function titleCase(value) {
  return String(value)
    .split(" ")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}
