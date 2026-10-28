import { useState } from "react";

import useApi from "@/hooks/useApi";
import ModuleIcon from "./ModuleIcon";
import { ModuleButton } from "./ModuleShared";

/**
 * MLOps Dashboard — real model evaluation.
 *
 * Shows the report produced by `python -m ml.evaluate` (GET /api/mlops/evaluation):
 * accuracy, precision, recall, F1 and a confusion matrix for the classification
 * models, and RMSE/MAE/R² for the regression model — all measured on the
 * repository's own held-out test split. Metrics are never fabricated: when a
 * model or dataset is missing the domain is shown as "not evaluated" with the
 * reason. The dataset caveats are always displayed alongside the numbers.
 */
export default function MlopsDashboard() {
  const { data, loading, error, refetch } = useApi("/api/mlops/evaluation");
  const [reloading, setReloading] = useState(false);

  const runReload = async () => {
    if (reloading) return; // re-entrancy guard (the button is also disabled)
    setReloading(true);
    // Re-reads the stored report; a full recompute is run offline via
    // `python -m ml.evaluate` so the dashboard never blocks on training.
    await refetch();
    setReloading(false);
  };

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3, 4].map((n) => (
          <div
            key={n}
            className="h-28 animate-pulse rounded-[20px] bg-[#E8F0EB]"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3">
        <p className="rounded-2xl bg-[#FCE9E5] p-4 text-[11px] font-semibold leading-5 text-[#9D4C3E]">
          Could not load the evaluation report
          {error.status ? ` (${error.status})` : ""}.
          {error.status === 503 ? " " + (error.message || "") : ""}
        </p>
        <ModuleButton secondary onClick={refetch}>
          Try again
        </ModuleButton>
      </div>
    );
  }

  const domains = data?.domains ?? {};

  return (
    <div className="space-y-4">
      <section className="rounded-[22px] border border-[#DCE6DF] bg-[#F7FAF8] p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-[#E9EAF7] text-[#575E95]">
              <ModuleIcon name="model" size={16} />
            </span>
            <h2 className="text-[13px] font-extrabold text-[#213D2F]">
              {data?.report_title}
            </h2>
          </div>
          <button
            onClick={runReload}
            disabled={reloading}
            className="rounded-full border border-[#D9E4DC] bg-white px-3 py-1.5 text-[10px] font-extrabold text-[#216B45] disabled:opacity-50"
          >
            {reloading ? "Reloading…" : "Reload"}
          </button>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-[#52675B]">
          <Meta label="Evaluation date" value={data?.evaluation_date} />
          <Meta
            label="Generated at"
            value={
              data?.generated_at
                ? new Date(data.generated_at).toLocaleString()
                : "—"
            }
          />
          <Meta label="scikit-learn" value={data?.environment?.scikit_learn} />
          <Meta label="Python" value={data?.environment?.python} />
        </div>
        <p className="mt-3 text-[10px] leading-5 text-[#75867C]">
          {data?.methodology?.summary}
        </p>
      </section>

      {Object.entries(domains).map(([domain, block]) => (
        <DomainCard key={domain} domain={domain} block={block} />
      ))}

      {data?.caveats?.length > 0 && (
        <section className="rounded-[22px] border border-[#F2DCB0] bg-[#FFFBF0] p-4">
          <h2 className="text-[12px] font-extrabold text-[#8A6D2B]">
            Dataset caveats
          </h2>
          <ul className="mt-2 space-y-1.5">
            {data.caveats.map((c, i) => (
              <li key={i} className="text-[9px] leading-4 text-[#8A6D2B]">
                • {c}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function DomainCard({ domain, block }) {
  const [showMatrix, setShowMatrix] = useState(false);

  if (!block?.available) {
    return (
      <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <h2 className="text-[13px] font-extrabold capitalize text-[#203C2E]">
          {domain}
        </h2>
        <p className="mt-2 text-[10px] leading-5 text-[#8A6D2B]">
          Not evaluated: {block?.reason ?? "no model or test split available."}
        </p>
      </section>
    );
  }

  const m = block.metrics ?? {};
  const isClassification = block.task === "multiclass_classification";

  return (
    <section className="space-y-3 rounded-[22px] border border-[#E0E8E2] bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-[13px] font-extrabold capitalize text-[#203C2E]">
          {domain}
        </h2>
        <span className="rounded-full bg-[#E9EAF7] px-2.5 py-1 text-[9px] font-extrabold text-[#575E95]">
          {block.model_type}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-[10px] text-[#52675B]">
        <Meta label="Train samples" value={block.n_train} />
        <Meta label="Test samples" value={block.n_test} />
        {isClassification ? (
          <Meta label="Crop classes" value={block.n_classes} />
        ) : (
          <Meta label="Task" value="regression" />
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {isClassification ? (
          <>
            <Stat label="Accuracy" value={m.accuracy} />
            <Stat label="F1 (macro)" value={m.f1_macro} />
            <Stat label="F1 (weighted)" value={m.f1_weighted} />
            <Stat label="Precision (macro)" value={m.precision_macro} />
            <Stat label="Recall (macro)" value={m.recall_macro} />
            {m.top_3_accuracy != null && (
              <Stat label="Top-3 accuracy" value={m.top_3_accuracy} />
            )}
          </>
        ) : (
          <>
            <Stat label="R² (log)" value={m.r2_log} />
            <Stat label="RMSE (log)" value={m.rmse_log} />
            <Stat label="MAE (log)" value={m.mae_log} />
            <Stat label="R² (t/ha)" value={m.r2_tonnes_per_ha} />
            <Stat label="RMSE (t/ha)" value={m.rmse_tonnes_per_ha} />
            <Stat label="MAE (t/ha)" value={m.mae_tonnes_per_ha} />
          </>
        )}
      </div>

      <p className="text-[9px] leading-4 text-[#9AA79F]">
        Split: {block.split?.kind} — {block.split?.detail}
      </p>

      {isClassification && m.confusion_matrix && (
        <div>
          <button
            onClick={() => setShowMatrix((v) => !v)}
            className="text-[10px] font-extrabold text-[#216B45] underline"
          >
            {showMatrix ? "Hide" : "Show"} confusion matrix ({block.n_classes}×
            {block.n_classes})
          </button>
          {showMatrix && <ConfusionMatrix metrics={m} />}
        </div>
      )}

      {m.top_k_note && (
        <p className="text-[9px] leading-4 text-[#8A6D2B]">{m.top_k_note}</p>
      )}
    </section>
  );
}

function ConfusionMatrix({ metrics }) {
  const labels = metrics.confusion_matrix_labels ?? [];
  const matrix = metrics.confusion_matrix ?? [];
  return (
    <div className="mt-2 overflow-x-auto rounded-xl border border-[#EDF1EE]">
      <table className="min-w-full border-collapse text-[8px]">
        <thead>
          <tr>
            <th className="sticky left-0 bg-[#F7FAF8] p-1" />
            {labels.map((l) => (
              <th key={l} className="p-1 font-extrabold text-[#52675B]">
                {l.slice(0, 4)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={i}>
              <th className="sticky left-0 bg-[#F7FAF8] p-1 text-left font-extrabold text-[#52675B]">
                {labels[i]}
              </th>
              {row.map((value, j) => (
                <td
                  key={j}
                  className={`p-1 text-center ${
                    i === j && value > 0
                      ? "bg-[#EAF6EF] font-extrabold text-[#1D4A33]"
                      : "text-[#75867C]"
                  }`}
                >
                  {value}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="p-2 text-[8px] text-[#9AA79F]">
        Rows = actual · Columns = predicted
      </p>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-2xl border border-[#E2E9E4] bg-[#FBFDFB] p-3">
      <p className="text-[9px] font-bold uppercase tracking-[.06em] text-[#7A8B82]">
        {label}
      </p>
      <p className="mt-1 text-[16px] font-extrabold text-[#1D3A2B]">
        {typeof value === "number" ? value.toFixed(4) : value ?? "—"}
      </p>
    </div>
  );
}

function Meta({ label, value }) {
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-[.06em] text-[#8A998F]">
        {label}
      </p>
      <p className="mt-0.5 text-[11px] font-extrabold text-[#213D2F]">
        {value ?? "—"}
      </p>
    </div>
  );
}
