import { useEffect, useMemo, useState } from "react";
import { apiPost } from "@/lib/apiClient";
import ModuleIcon from "./ModuleIcon";

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

    const message =
      "Explain this farm prediction in simple language for a farmer. " +
      "Reply with exactly four short labelled lines and nothing else:\n" +
      "Explanation: <one sentence on what the result means>\n" +
      "Key factors: <the inputs that most influenced it>\n" +
      "Next step: <one practical action>\n" +
      "Limitations: <what this prediction cannot tell the farmer>";

    apiPost("/api/chat", {
      message,
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
            ? "The AI assistant is not available right now, so this prediction has no explanation yet."
            : err?.status === 401
            ? "Sign in again to see the explanation for this prediction."
            : "Could not reach the AI assistant for an explanation.",
        );
      });

    return () => {
      cancelled = true;
    };
    // `attempt` lets the farmer retry without re-running the prediction.
  }, [resultKey, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!result) return null;

  const sections = state === "done" ? parseAnswer(answer) : [];

  return (
    <section className="rounded-[22px] border border-[#D8E4DC] bg-white p-4">
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-[#E5F1E8] text-[#216B45]">
          <ModuleIcon name="sparkles" size={15} />
        </span>
        <h3 className="flex-1 text-[12px] font-extrabold text-[#213D2F]">
          What this means
        </h3>
        <span className="rounded-full bg-[#F0F5F1] px-2 py-0.5 text-[8px] font-extrabold uppercase tracking-[.06em] text-[#5C7A67]">
          AI explanation
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
            The prediction above is unchanged — it comes from the model, not
            from the assistant.
          </p>
          <button
            onClick={() => setAttempt((n) => n + 1)}
            className="mt-2 text-[10px] font-bold text-[#216B45] underline"
          >
            Try the explanation again
          </button>
        </div>
      )}

      {state === "done" && sections.length === 0 && (
        <p className="mt-3 text-[11px] leading-5 text-[#4F6A5C]">{answer}</p>
      )}

      {state === "done" && sections.length > 0 && (
        <dl className="mt-3 space-y-2.5">
          {sections.map((s, i) => (
            <div key={`${s.label}-${i}`}>
              <dt className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8C82]">
                {s.label}
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
            Explanation only — the prediction is the model's own output.
          </p>
          {onAsk && (
            <button
              onClick={onAsk}
              className="text-[10px] font-bold text-[#216B45]"
            >
              Ask more →
            </button>
          )}
        </div>
      )}
    </section>
  );
}

// The labels we ask the assistant to use, in the order they should be shown.
const CANONICAL = ["Explanation", "Key factors", "Next step", "Limitations"];

/**
 * Split the assistant's reply into labelled sections.
 *
 * The assistant is asked for four labelled lines, but an LLM may return prose,
 * bold markers or bullets instead. Unrecognised lines are appended to the
 * current section, and a reply with no recognisable label is treated as one
 * "Explanation" block — the text is always shown as written, never rewritten.
 */
function parseAnswer(answer) {
  const text = String(answer ?? "").trim();
  if (!text) return [];

  const sections = [];
  let current = null;

  for (const raw of text.split(/\r?\n/)) {
    const line = raw
      .trim()
      .replace(/^[-*•]\s*/, "")
      .replace(/\*\*/g, "")
      .trim();
    if (!line) continue;

    const match = line.match(/^([A-Za-z][A-Za-z ]{2,24}):\s*(.*)$/);
    const isLabel =
      match &&
      CANONICAL.some(
        (label) => label.toLowerCase() === match[1].trim().toLowerCase(),
      );

    if (isLabel) {
      current = { label: titleCase(match[1].trim()), text: match[2].trim() };
      sections.push(current);
    } else if (current) {
      current.text += current.text ? ` ${line}` : line;
    } else {
      current = { label: "Explanation", text: line };
      sections.push(current);
    }
  }

  // A single block needs no reordering; multiple blocks are shown in the
  // sequence the assistant was asked to use.
  if (sections.length <= 1) return sections;
  return sections.sort((a, b) => orderOf(a.label) - orderOf(b.label));
}

function orderOf(label) {
  const i = CANONICAL.findIndex((c) => c.toLowerCase() === label.toLowerCase());
  return i === -1 ? CANONICAL.length : i;
}

function titleCase(value) {
  return value
    .split(" ")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}
