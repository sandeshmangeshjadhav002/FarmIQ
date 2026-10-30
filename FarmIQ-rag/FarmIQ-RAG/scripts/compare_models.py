#!/usr/bin/env python
"""Compare candidate answer-generation models on real FarmIQ questions.

Before settling on the model that writes FarmIQ's AI explanations, run a small,
representative set of real agricultural questions through each candidate and
compare the answers side by side.

Usage
-----
    # Compare two Hugging Face models (needs HF_TOKEN / HF_MODEL_ID in .env)
    python scripts/compare_models.py \\
        --models meta-llama/Llama-3.1-8B-Instruct,Qwen/Qwen2.5-7B-Instruct

    # Compare models on whichever provider is already configured in .env
    python scripts/compare_models.py --models openai/gpt-oss-120b,openai/gpt-oss-20b

    # Just the first three questions, custom output path
    python scripts/compare_models.py --limit 3 --out data/processed/my_report

How it works
------------
The retrieval half of the pipeline is identical for every candidate (same
embedder, same index, same prompt), so any difference in the output comes from
the model. Each candidate is probed for availability first and then asked the
same questions. Answers, latencies and retrieved sources are written to a JSON
file plus a Markdown table for review.

Nothing is fabricated: a candidate that is unavailable, that errors, or that
returns no text is recorded as such rather than replaced by a guess. The
retrieved-passages fallback (used when an LLM is not configured) is labelled
too, so it cannot be mistaken for a model answer.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make ``src`` importable when running the script directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import (  # noqa: E402
    HUGGINGFACE_PROVIDER_NAMES,
    Settings,
    get_settings,
)
from src.llm_client import (  # noqa: E402
    LLMNotConfiguredError,
    LLMRequestError,
    build_llm_client,
    check_model_availability,
)
from src.rag_pipeline import build_rag_pipeline  # noqa: E402

# The two models FarmIQ documents as its default and its multilingual
# alternative (see backend/.env.example).
DEFAULT_MODELS = [
    "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
]

# A small, representative set of real FarmIQ questions: one per major topic the
# assistant is asked about, two carrying real ML predictions (so requirement
# "explain the ML result, never replace it" is exercised), and one Marathi
# question to check language handling.
COMPARISON_QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "irrigation-soybean",
        "topic": "irrigation_management",
        "language": "en",
        "question": "How should I manage irrigation for a soybean crop in black soil?",
    },
    {
        "id": "soil-acidic",
        "topic": "soil_health_and_nutrients",
        "language": "en",
        "question": "My soil test says pH 5.4. How do I correct it before sowing wheat?",
    },
    {
        "id": "tomato-leaf-spots",
        "topic": "crop_symptoms_and_causes",
        "language": "en",
        "question": (
            "My tomato leaves have brown spots with yellow rings and the lower "
            "leaves are drying. What is this and how do I treat it?"
        ),
    },
    {
        "id": "pesticide-safety",
        "topic": "pesticide_selection_and_safety",
        "language": "en",
        "question": "What is the safe waiting period after spraying on brinjal before harvest?",
    },
    {
        "id": "explain-crop-prediction",
        "topic": "crop_practices_india",
        "language": "en",
        "question": "The app recommended soybean for my field. Why does that suit my soil?",
        "ml_results": {
            "source": "farmiq_ml_model",
            "domain": "crop",
            "prediction": "soybean",
            "model_source": "pretrained",
            "inputs": {"N": 42, "P": 18, "K": 25, "ph": 6.5, "rainfall": 720},
        },
    },
    {
        "id": "explain-fertilizer-prediction",
        "topic": "soil_health_and_nutrients",
        "language": "en",
        "question": "The app said to use DAP. How should I apply it?",
        "ml_results": {
            "source": "farmiq_ml_model",
            "domain": "fertilizer",
            "prediction": "DAP",
            "model_source": "pretrained",
            "inputs": {"N": 42, "P": 18, "K": 25, "ph": 6.5},
        },
    },
    {
        "id": "onion-marathi",
        "topic": "crop_practices_india",
        "language": "mr",
        "question": "माझ्या शेतात कांदा लावावा का?",
    },
]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare candidate LLM models on real FarmIQ questions."
    )
    parser.add_argument(
        "--models",
        default="",
        help=f"Comma-separated model ids (default: {', '.join(DEFAULT_MODELS)}).",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Only use the first N questions (default: all).",
    )
    parser.add_argument(
        "--out", default="",
        help="Output path without extension (default: data/processed/model_comparison).",
    )
    return parser.parse_args(argv)


def _candidate_settings(base: Settings, model: str) -> Settings:
    """Settings for one candidate model, leaving everything else unchanged."""
    provider = (base.llm_provider or "openai").strip().lower()
    if provider in HUGGINGFACE_PROVIDER_NAMES:
        # HF_MODEL_ID is the field the Hugging Face client reads.
        return replace(base, hf_model_id=model, llm_model=model)
    return replace(base, llm_model=model)


def _availability(base: Settings, model: str) -> Dict[str, Any]:
    provider = (base.llm_provider or "openai").strip().lower()
    if provider not in HUGGINGFACE_PROVIDER_NAMES:
        return {
            "model": model,
            "available": None,
            "provider": provider,
            "providers": [],
            "message": "Availability probing is only implemented for Hugging Face.",
        }
    return check_model_availability(
        model,
        token=(base.hf_token or base.llm_api_key or "").strip() or None,
        provider=(base.hf_provider or "").strip() or None,
        timeout=float(base.llm_request_timeout),
    )


# ---------------------------------------------------------------------------
# Running one candidate over every question
# ---------------------------------------------------------------------------
def _ask(pipeline, item: Dict[str, Any]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "id": item["id"],
        "topic": item["topic"],
        "language": item.get("language"),
        "question": item["question"],
        "ml_results": item.get("ml_results"),
    }
    started = time.perf_counter()
    try:
        result = pipeline.answer(
            item["question"],
            item.get("ml_results"),
            language=item.get("language"),
        )
    except (LLMNotConfiguredError, LLMRequestError) as exc:
        entry.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:  # noqa: BLE001 - report, never abort the comparison
        entry.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    else:
        entry.update(
            {
                "ok": True,
                "answer": result.answer,
                "llm_used": bool(result.llm_used),
                "retrieval_status": getattr(
                    getattr(result, "retrieval_status", None), "name", None
                ),
                "ml_context_provided": bool(getattr(result, "ml_context_provided", False)),
                "sources": [
                    {
                        "source": str(getattr(s, "source", "")),
                        "page": getattr(s, "page", None),
                        "similarity": round(float(getattr(s, "similarity", 0.0)), 3),
                    }
                    for s in (getattr(result, "sources", None) or [])
                ],
                "warnings": list(getattr(result, "warnings", None) or []),
            }
        )
    entry["latency_s"] = round(time.perf_counter() - started, 2)
    return entry


def run_comparison(
    base: Settings,
    models: List[str],
    questions: List[Dict[str, Any]],
    *,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Ask every question through every candidate and collect the answers."""
    pipeline = build_rag_pipeline(base)

    index_chunks = None
    try:
        index_chunks = pipeline.retriever.vector_store.count()
    except Exception:  # pragma: no cover - defensive
        index_chunks = None

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider_configured": base.llm_provider,
        "embedding_model": base.embedding_model,
        "index_chunks": index_chunks,
        "questions": [
            {"id": q["id"], "topic": q["topic"], "question": q["question"]} for q in questions
        ],
        "models": {},
    }

    for model in models:
        candidate = _candidate_settings(base, model)
        availability = _availability(base, model)
        if verbose:
            state = availability.get("available")
            state_text = {True: "live", False: "unavailable", None: "unknown"}[state]
            print(f"\n[INFO] {model} — {state_text}")

        # Reuse the already-built retriever/embedder; only the LLM changes, so
        # any difference in the output comes from the model itself.
        pipeline.llm_client = build_llm_client(candidate)
        pipeline.settings = candidate

        entries: List[Dict[str, Any]] = []
        for item in questions:
            entry = _ask(pipeline, item)
            if verbose:
                if entry["ok"]:
                    preview = " ".join(str(entry["answer"]).split())[:80]
                    print(f"    - {entry['id']}: {entry['latency_s']}s | {preview}...")
                else:
                    print(f"    - {entry['id']}: FAILED ({entry['error']})")
            entries.append(entry)

        report["models"][model] = {"availability": availability, "results": entries}

    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _cell(entry: Dict[str, Any]) -> str:
    if not entry["ok"]:
        return f"**ERROR** — {entry['error']}"
    text = " ".join(str(entry.get("answer") or "").split())
    if not text:
        text = "_(empty answer)_"
    flag = "" if entry.get("llm_used") else " _(retrieved passages only — LLM not used)_"
    return f"{text}{flag}"


def render_markdown(report: Dict[str, Any]) -> str:
    models = list(report["models"].keys())
    lines: List[str] = []
    lines.append("# FarmIQ model comparison")
    lines.append("")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append(f"Provider configured: `{report['provider_configured']}`")
    lines.append(f"Embedding model: `{report['embedding_model']}`")
    lines.append(f"Indexed chunks: {report['index_chunks']}")
    lines.append("")

    # Per-model summary.
    lines.append("## Summary")
    lines.append("")
    lines.append("| Model | Available | Answered | Mean latency (s) |")
    lines.append("| --- | --- | --- | --- |")
    for model in models:
        block = report["models"][model]
        results = block["results"]
        ok = [r for r in results if r["ok"]]
        mean = round(sum(r["latency_s"] for r in ok) / len(ok), 2) if ok else None
        lines.append(
            f"| `{model}` | {block['availability'].get('available')} | "
            f"{len(ok)}/{len(results)} | {mean if mean is not None else '—'} |"
        )
    lines.append("")

    # Answer-by-answer comparison.
    lines.append("## Answers")
    for question in report["questions"]:
        qid = question["id"]
        lines.append("")
        lines.append(f"### {qid} — _{question['topic']}_")
        lines.append("")
        lines.append(f"**Q:** {question['question']}")
        lines.append("")
        for model in models:
            lines.append(f"**{model}**")
            lines.append("")
            entry = next(
                (r for r in report["models"][model]["results"] if r["id"] == qid), None
            )
            lines.append(f"> {_cell(entry)}" if entry else "> _(not run)_")
            lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    args = _parse_args(argv)
    base = get_settings()

    models = [m.strip() for m in args.models.split(",") if m.strip()] or DEFAULT_MODELS
    questions = COMPARISON_QUESTIONS[: args.limit] if args.limit else COMPARISON_QUESTIONS

    print(f"[INFO] Provider      : {base.llm_provider}")
    print(f"[INFO] Embedding     : {base.embedding_model}")
    print(f"[INFO] Candidates    : {', '.join(models)}")
    print(f"[INFO] Questions     : {len(questions)}")

    if not base.llm_configured:
        print(
            "[WARN] No LLM credentials are configured, so no model answers can be "
            "generated. Set HF_TOKEN and HF_MODEL_ID (Hugging Face) — or "
            "LLM_API_KEY and LLM_MODEL — in FarmIQ-RAG/.env, then re-run."
        )

    try:
        report = run_comparison(base, models, questions)
    except Exception as exc:  # noqa: BLE001 - CLI must explain, not traceback
        print(f"[ERROR] Comparison failed: {type(exc).__name__}: {exc}")
        return 2

    out_base = Path(args.out) if args.out else _PROJECT_ROOT / "data" / "processed" / "model_comparison"
    if not out_base.is_absolute():
        out_base = _PROJECT_ROOT / out_base
    out_base.parent.mkdir(parents=True, exist_ok=True)

    json_path = out_base.with_suffix(".json")
    md_path = out_base.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"\n[INFO] Wrote {json_path}")
    print(f"[INFO] Wrote {md_path}")

    # A non-zero exit code when no candidate produced a single answer.
    answered = any(
        r["ok"] and r.get("llm_used")
        for block in report["models"].values()
        for r in block["results"]
    )
    return 0 if answered else 1


if __name__ == "__main__":
    sys.exit(main())
