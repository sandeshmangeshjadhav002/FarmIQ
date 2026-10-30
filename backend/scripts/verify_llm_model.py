"""Verify that the configured Hugging Face model is served by a live provider.

Requirement: before enabling answer generation, confirm that ``HF_MODEL_ID``
really is available through a supported Hugging Face Inference Provider.

Run from the ``backend/`` directory:

    .venv\\Scripts\\python scripts\\verify_llm_model.py

    # or verify a specific model / provider without editing .env:
    .venv\\Scripts\\python scripts\\verify_llm_model.py --model Qwen/Qwen2.5-7B-Instruct
    .venv\\Scripts\\python scripts\\verify_llm_model.py --provider deepinfra

The script never prints the token. Exit codes: ``0`` the model is live, ``1``
it is not (or the Hub could not be read), ``2`` no model id is configured.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))  # noqa: E402 - allow `python scripts/...`

from app.config import get_settings  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check whether a Hugging Face model is served by a live inference provider."
    )
    parser.add_argument("--model", default="", help="Model id (defaults to HF_MODEL_ID).")
    parser.add_argument(
        "--provider", default=None, help="Require this provider (defaults to HF_PROVIDER)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()

    model_id = (args.model or settings.hf_model_id).strip()
    provider = (args.provider if args.provider is not None else settings.hf_provider).strip()

    if not model_id:
        print(
            "No model id given. Set HF_MODEL_ID in backend/.env, or pass --model.\n"
            "Example: HF_MODEL_ID=meta-llama/Llama-3.1-8B-Instruct"
        )
        return 2

    # Reuse the bridge so this script and the running API stay in agreement.
    from app import rag_service

    result = rag_service.probe_llm_model(model_id, provider=provider)

    print(f"Model:    {result['model']}")
    print(f"Provider: {result['provider']}")
    if result["providers"]:
        print(f"Served by: {', '.join(str(p) for p in result['providers'])}")

    if result["available"]:
        print("\nOK — the model is available through a live inference provider.")
        return 0

    print(f"\nNot available. {result['message']}")
    print(
        "\nTry one of these models, which are widely served by Inference Providers:\n"
        "  meta-llama/Llama-3.1-8B-Instruct\n"
        "  Qwen/Qwen2.5-7B-Instruct        (better multilingual coverage)"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
