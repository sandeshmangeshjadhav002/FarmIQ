"""Hugging Face integration tests: credential bridge, availability, redaction.

Requirements covered here:
  #2/#3  HF_TOKEN / HF_MODEL_ID live in the *backend* environment and are
         forwarded to the standalone RAG project (which builds the official
         ``huggingface_hub.InferenceClient``).
  #4     The configured model can be probed for a live inference provider.
  #12    Credentials never reach the frontend or the logs.

These tests deliberately import only the RAG project's ``src.config`` module
(stdlib-only) so they do not need sentence-transformers / ChromaDB.
"""
from __future__ import annotations

import sys
from dataclasses import replace as dc_replace
from pathlib import Path

import pytest

from app import rag_service
from app.config import Settings, get_settings


# ── helpers ──────────────────────────────────────────────────────────────────
def _rag_config():
    """Import the real RAG project's ``src.config`` module, or skip if shadowed."""
    project_dir = rag_service._resolve_project_dir()
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    import src.config as rag_config  # type: ignore

    module_file = Path(rag_config.__file__).resolve()
    if project_dir.resolve() not in module_file.parents:
        pytest.skip("Another 'src' package is shadowing the FarmIQ-RAG package.")
    return rag_config


def _rag_settings(**overrides):
    """A real RAG-project Settings instance with the given fields overridden."""
    settings = _rag_config().get_settings()
    return dc_replace(settings, **overrides) if overrides else settings


def _backend_settings(**overrides) -> Settings:
    return get_settings().model_copy(update=overrides)


# ── #2/#3  The backend bridges its credentials into the RAG project ──────────
def test_hf_configured_requires_both_a_token_and_a_model():
    assert _backend_settings(hf_token="hf_abc123", hf_model_id="").hf_configured is False
    assert _backend_settings(hf_token="", hf_model_id="meta-llama/Llama-3.1-8B-Instruct").hf_configured is False
    assert _backend_settings(hf_token="hf_abc123", hf_model_id="m").hf_configured is True


def test_an_unconfigured_backend_leaves_the_rag_settings_untouched():
    """An existing Groq / OpenAI-compatible setup must keep working."""
    rag_settings = _rag_settings(
        llm_provider="openai", llm_api_key="gsk_existing", llm_model="openai/gpt-oss-120b"
    )
    result = rag_service._apply_hf_settings(
        rag_settings, _backend_settings(hf_token="", hf_model_id="")
    )
    assert result is rag_settings


def test_backend_credentials_switch_the_rag_project_to_huggingface():
    rag_settings = _rag_settings(
        llm_provider="openai", llm_api_key="gsk_old", llm_model="openai/gpt-oss-120b"
    )
    backend = _backend_settings(
        hf_token="hf_secret_value",
        hf_model_id="meta-llama/Llama-3.1-8B-Instruct",
        hf_provider="",
        hf_timeout_seconds=45.0,
    )

    result = rag_service._apply_hf_settings(rag_settings, backend)

    assert result.llm_provider == "huggingface"
    assert result.is_huggingface_provider is True
    assert result.hf_token == "hf_secret_value"
    assert result.hf_model_id == "meta-llama/Llama-3.1-8B-Instruct"
    # The RAG project's own aliases agree, so its LLMClient Protocol check passes.
    assert result.llm_api_key == "hf_secret_value"
    assert result.llm_model == "meta-llama/Llama-3.1-8B-Instruct"
    assert result.llm_configured is True
    # The configured timeout is applied so an unresponsive provider degrades to
    # the retrieved-passages fallback instead of hanging the request.
    assert result.llm_request_timeout == 45.0
    # dataclasses.replace copies: the original object is untouched.
    assert rag_settings.llm_provider == "openai"
    assert rag_settings.hf_token is None


def test_the_provider_pin_is_only_forwarded_when_set():
    rag_settings = _rag_settings()
    base = dict(hf_token="hf_x", hf_model_id="meta-llama/Llama-3.1-8B-Instruct")

    assert rag_service._apply_hf_settings(
        rag_settings, _backend_settings(hf_provider="", **base)
    ).hf_provider is None
    assert rag_service._apply_hf_settings(
        rag_settings, _backend_settings(hf_provider="deepinfra", **base)
    ).hf_provider == "deepinfra"


def test_whitespace_only_credentials_do_not_count_as_configured():
    assert _backend_settings(hf_token="   ", hf_model_id="   ").hf_configured is False


# ── #12  Secrets never leave the backend ─────────────────────────────────────
def test_redact_secrets_strips_token_shaped_strings():
    out = rag_service._redact_secrets(
        "401 Unauthorized: token hf_abcdef123456 rejected; key sk-proj-abcdefgh also bad"
    )
    assert "hf_abcdef123456" not in out
    assert "sk-proj-abcdefgh" not in out
    assert "***" in out


def test_redact_secrets_strips_the_configured_token_even_without_a_prefix(monkeypatch):
    token = "unprefixed-token-1234567890"
    monkeypatch.setattr(
        rag_service, "get_settings", lambda: _backend_settings(hf_token=token)
    )
    assert token not in rag_service._redact_secrets(f"rejected: {token}")


def test_redact_secrets_leaves_ordinary_text_alone():
    text = "The soil pH is 6.4 and rainfall was 720 mm."
    assert rag_service._redact_secrets(text) == text


# ── #4  Model availability probing ───────────────────────────────────────────
def test_probe_llm_model_without_a_model_id_explains_the_setting(monkeypatch):
    monkeypatch.setattr(rag_service, "get_settings", lambda: _backend_settings(hf_model_id=""))
    result = rag_service.probe_llm_model()
    assert result["available"] is False
    assert "No Hugging Face model id" in result["message"]


def test_probe_llm_model_reports_a_missing_rag_project_instead_of_raising(monkeypatch):
    def _raise():
        raise rag_service.RagUnavailableError("FarmIQ-RAG project not found.")

    monkeypatch.setattr(
        rag_service, "get_settings",
        lambda: _backend_settings(hf_model_id="meta-llama/Llama-3.1-8B-Instruct"),
    )
    monkeypatch.setattr(rag_service, "_resolve_project_dir", _raise)
    result = rag_service.probe_llm_model()
    assert result["available"] is False
    assert "not found" in result["message"]


def test_probe_llm_model_delegates_to_the_rag_availability_check(monkeypatch):
    """The CLI script and the running API must agree on how a model is probed."""
    _rag_config()  # puts the RAG project on sys.path
    import src.llm_client as rag_llm_client

    recorded: dict = {}

    def _fake_check(model_id, *, token=None, provider=None, timeout=None):
        recorded.update(
            {"model_id": model_id, "token": token, "provider": provider, "timeout": timeout}
        )
        return {
            "model": model_id,
            "available": True,
            "provider": provider or "auto",
            "providers": ["novita"],
            "message": "",
        }

    monkeypatch.setattr(rag_llm_client, "check_model_availability", _fake_check)
    monkeypatch.setattr(
        rag_service, "get_settings",
        lambda: _backend_settings(
            hf_token="hf_probe_token",
            hf_model_id="meta-llama/Llama-3.1-8B-Instruct",
            hf_provider="",
            hf_timeout_seconds=30.0,
        ),
    )

    result = rag_service.probe_llm_model()

    assert result["available"] is True
    assert recorded["model_id"] == "meta-llama/Llama-3.1-8B-Instruct"
    assert recorded["token"] == "hf_probe_token"
    assert recorded["timeout"] == 30.0


def _raise_unavailable():
    raise rag_service.RagUnavailableError("RAG dependencies are not installed.")


def test_check_model_availability_never_raises_without_a_pipeline(monkeypatch):
    monkeypatch.setattr(rag_service, "get_pipeline", _raise_unavailable)
    result = rag_service.check_model_availability()
    assert result["available"] is False
    assert result["providers"] == []
    assert "not installed" in result["message"]


class _ConfiguredOpenAIClient:
    is_configured = True
    model_name = "openai/gpt-oss-120b"


class _PipelineWith:
    def __init__(self, llm_client, **extra):
        self.llm_client = llm_client
        for key, value in extra.items():
            setattr(self, key, value)


def test_check_model_availability_explains_non_huggingface_providers(monkeypatch):
    monkeypatch.setattr(
        rag_service, "get_pipeline", lambda: _PipelineWith(_ConfiguredOpenAIClient())
    )
    result = rag_service.check_model_availability()
    assert result["available"] is True
    assert result["model"] == "openai/gpt-oss-120b"
    assert "Hugging Face" in result["message"]


def test_check_model_availability_delegates_to_the_huggingface_client(monkeypatch):
    class _HfClient:
        is_configured = True
        model_name = "meta-llama/Llama-3.1-8B-Instruct"

        def check_availability(self):
            return {
                "model": self.model_name,
                "available": True,
                "provider": "novita",
                "providers": [{"provider": "novita", "status": "live"}],
                "message": "Served by 1 live provider.",
            }

    monkeypatch.setattr(rag_service, "get_pipeline", lambda: _PipelineWith(_HfClient()))
    result = rag_service.check_model_availability()
    assert result["available"] is True
    assert result["provider"] == "novita"
    assert result["providers"][0]["status"] == "live"


def test_the_availability_report_never_contains_the_token(monkeypatch):
    secret = "hf_SECRETVALUE1234567890"
    monkeypatch.setattr(
        rag_service, "get_settings", lambda: _backend_settings(hf_token=secret, hf_model_id="m")
    )
    monkeypatch.setattr(rag_service, "get_pipeline", _raise_unavailable)
    assert secret not in str(rag_service.check_model_availability())


# ── Status reporting ─────────────────────────────────────────────────────────
def test_get_status_reports_the_configured_provider_and_model(monkeypatch):
    class _Store:
        def count(self) -> int:
            return 7

    class _Embedder:
        model_name = "sentence-transformers/all-MiniLM-L6-v2"

    class _Retriever:
        vector_store = _Store()
        embedder = _Embedder()

    class _Settings:
        llm_provider = "huggingface"

    class _Client:
        is_configured = True
        model_name = "meta-llama/Llama-3.1-8B-Instruct"

    pipeline = _PipelineWith(_Client(), retriever=_Retriever(), settings=_Settings())
    monkeypatch.setattr(rag_service, "get_pipeline", lambda: pipeline)

    status = rag_service.get_status()
    assert status["available"] is True
    assert status["indexed"] is True
    assert status["index_chunks"] == 7
    assert status["llm_provider"] == "huggingface"
    assert status["llm_model"] == "meta-llama/Llama-3.1-8B-Instruct"
    assert "hf_" not in str(status)


def test_get_status_degrades_gracefully_without_a_settings_attribute(monkeypatch):
    """A pipeline without ``settings`` (e.g. an older build) must not 500."""

    class _Store:
        def count(self) -> int:
            return 1

    class _Embedder:
        model_name = "fake-embed"

    class _Retriever:
        vector_store = _Store()
        embedder = _Embedder()

    monkeypatch.setattr(
        rag_service,
        "get_pipeline",
        lambda: _PipelineWith(_ConfiguredOpenAIClient(), retriever=_Retriever()),
    )
    status = rag_service.get_status()
    assert status["available"] is True
    assert status["llm_provider"] is None
    assert status["llm_model"] == "openai/gpt-oss-120b"
