"""LLM client abstraction for FarmIQ-RAG.

The RAG pipeline depends only on the :class:`LLMClient` protocol, so the
underlying provider can be swapped (Hugging Face Inference Providers, OpenAI,
Together, Groq, a local vLLM, ...) without touching the pipeline. Two concrete
clients ship out of the box:

* :class:`HuggingFaceClient` — the official ``huggingface_hub.InferenceClient``,
  reaching a model through any supported Hugging Face Inference Provider.
* :class:`OpenAICompatibleClient` — any OpenAI-compatible Chat Completions API.

Security rules
--------------
* Credentials are read from :class:`~src.config.Settings` (i.e. environment
  variables / ``.env``) and are **never** logged or echoed back.
* If the provider is not configured, a clear :class:`LLMNotConfiguredError`
  is raised so the CLI can print a helpful message instead of crashing.
* The client never writes fake/hard-coded responses into production code; a
  :class:`FakeLLMClient` exists only for tests and is deliberately not used by
  the pipeline by default.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from src.config import HUGGINGFACE_PROVIDER_NAMES, Settings

logger = logging.getLogger(__name__)


class LLMNotConfiguredError(RuntimeError):
    """Raised when answer generation is requested but no provider is configured."""


class LLMRequestError(RuntimeError):
    """Raised when the provider returns an error or an unusable response."""


def _redact(text: Any, *secrets: Optional[str]) -> str:
    """Return *text* with any of *secrets* replaced by ``***``.

    Provider SDKs occasionally echo the credential they rejected inside their
    own error message. Credentials must never reach a log line or a caller, so
    the configured token is scrubbed from every error we surface.
    """
    redacted = str(text)
    for secret in secrets:
        value = (secret or "").strip()
        if value:
            redacted = redacted.replace(value, "***")
    return redacted


@runtime_checkable
class LLMClient(Protocol):
    """Minimal interface the RAG pipeline depends on."""

    @property
    def is_configured(self) -> bool: ...

    @property
    def model_name(self) -> str: ...

    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str: ...


class OpenAICompatibleClient:
    """LLM client for any OpenAI-compatible Chat Completions endpoint.

    Works with OpenAI, Together AI, Groq, OpenRouter, local vLLM/llama.cpp
    servers, etc. — anything that accepts ``base_url`` + ``api_key`` and speaks
    the Chat Completions schema.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None  # lazily initialised on first generate() call

    # ------------------------------------------------------------------ props
    @property
    def is_configured(self) -> bool:
        # Never log the key itself; only report readiness.
        return self._settings.llm_configured

    @property
    def model_name(self) -> str:
        return self._settings.llm_model or ""

    # ------------------------------------------------------------------ impl
    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self.is_configured:
            raise LLMNotConfiguredError(
                "Answer generation requires an LLM provider. Set the following "
                "environment variables (see .env.example):\n"
                "  LLM_API_KEY, LLM_MODEL  (and optionally LLM_BASE_URL)."
            )
        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:  # pragma: no cover - env dependent
            raise LLMRequestError(
                "The 'openai' package is required for the default LLM client. "
                "Install it via: pip install openai"
            ) from exc

        kwargs: Dict[str, Any] = {
            "api_key": self._settings.llm_api_key,
            "timeout": self._settings.llm_request_timeout,
        }
        if self._settings.llm_base_url:
            kwargs["base_url"] = self._settings.llm_base_url

        # Avoid passing None base_url so provider defaults apply.
        self._client = OpenAI(**kwargs)
        return self._client

    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        client = self._ensure_client()
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        temp = float(temperature if temperature is not None else self._settings.llm_temperature)
        max_tok = int(max_tokens if max_tokens is not None else self._settings.llm_max_tokens)

        logger.debug(
            "Calling LLM (model=%s, temperature=%.2f, max_tokens=%s, system=%s).",
            self.model_name,
            temp,
            max_tok,
            bool(system),
        )
        try:
            response = client.chat.completions.create(
                model=self._settings.llm_model,
                messages=messages,
                temperature=temp,
                max_tokens=max_tok,
            )
        except Exception as exc:
            # Only the exception type and a redacted message are surfaced — the
            # API key never reaches a log line or a caller.
            raise LLMRequestError(
                f"LLM request failed: {type(exc).__name__}: "
                f"{_redact(exc, self._settings.llm_api_key)}"
            ) from exc

        text = _extract_content(response)
        if not text:
            raise LLMRequestError("LLM returned an empty completion.")
        return text


class HuggingFaceClient:
    """LLM client backed by Hugging Face Inference Providers.

    Uses the official :class:`huggingface_hub.InferenceClient`, so the model is
    served by whichever Inference Provider the Hub routes it to (hf-inference,
    together, deepinfra, novita, groq, ...). ``HF_PROVIDER`` optionally pins a
    single provider; when it is empty the router picks the first available one.

    ``HF_TOKEN`` / ``HF_MODEL_ID`` are the documented names; ``LLM_API_KEY`` /
    ``LLM_MODEL`` are accepted as aliases so a caller such as the FarmIQ backend
    can configure the provider once, under either naming. The token is never
    logged and never appears in an exception message.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None  # lazily initialised on first generate() call

    # ------------------------------------------------------------------ props
    @property
    def token(self) -> str:
        return (self._settings.hf_token or self._settings.llm_api_key or "").strip()

    @property
    def model_name(self) -> str:
        return (self._settings.hf_model_id or self._settings.llm_model or "").strip()

    @property
    def provider(self) -> str:
        return (self._settings.hf_provider or "").strip()

    @property
    def is_configured(self) -> bool:
        # Never log the token itself; only report readiness.
        return bool(self.token and self.model_name)

    # ------------------------------------------------------------------ impl
    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self.is_configured:
            raise LLMNotConfiguredError(
                "Answer generation requires a Hugging Face model. Set the "
                "following environment variables (see .env.example):\n"
                "  HF_TOKEN, HF_MODEL_ID  (and optionally HF_PROVIDER)."
            )
        try:
            from huggingface_hub import InferenceClient  # type: ignore
        except Exception as exc:  # pragma: no cover - env dependent
            raise LLMRequestError(
                "The 'huggingface_hub' package is required for the Hugging Face "
                "LLM client. Install it via: pip install huggingface_hub"
            ) from exc

        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "token": self.token,
            "timeout": float(self._settings.llm_request_timeout),
        }
        if self.provider:
            kwargs["provider"] = self.provider
        self._client = InferenceClient(**kwargs)
        return self._client

    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        client = self._ensure_client()
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        temp = float(temperature if temperature is not None else self._settings.llm_temperature)
        max_tok = int(max_tokens if max_tokens is not None else self._settings.llm_max_tokens)

        logger.debug(
            "Calling Hugging Face Inference Provider (model=%s, provider=%s, "
            "temperature=%.2f, max_tokens=%s, system=%s).",
            self.model_name,
            self.provider or "auto",
            temp,
            max_tok,
            bool(system),
        )
        try:
            response = client.chat_completion(
                model=self.model_name,
                messages=messages,
                temperature=temp,
                max_tokens=max_tok,
            )
        except Exception as exc:
            # Only the exception type and a redacted message are surfaced — the
            # token never reaches a log line or a caller.
            raise LLMRequestError(
                f"Hugging Face request failed: {type(exc).__name__}: "
                f"{_redact(exc, self.token)}"
            ) from exc

        text = _extract_content(response)
        if not text:
            raise LLMRequestError("Hugging Face returned an empty completion.")
        return text

    def check_availability(self) -> Dict[str, Any]:
        """Whether ``HF_MODEL_ID`` is served by a supported Inference Provider.

        Never raises, so a status endpoint stays responsive: an unreachable Hub
        or an invalid token is reported as ``available=False`` with a message.
        """
        return check_model_availability(
            self.model_name,
            token=self.token,
            provider=self.provider,
            timeout=float(self._settings.llm_request_timeout),
        )


def check_model_availability(
    model_id: str,
    *,
    token: Optional[str] = None,
    provider: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Report which Inference Providers serve *model_id*.

    Returns a JSON-ready dict::

        {
          "model": "meta-llama/Llama-3.1-8B-Instruct",
          "available": True,
          "provider": "auto",            # the pinned provider, or "auto"
          "providers": ["novita", "deepinfra"],
          "message": "",
        }

    ``available`` is true when at least one provider reports ``status == "live"``
    (and, when *provider* is pinned, that the pinned provider does). This never
    raises — verification must not be able to take an endpoint down.
    """
    result: Dict[str, Any] = {
        "model": (model_id or "").strip(),
        "available": False,
        "provider": (provider or "").strip() or "auto",
        "providers": [],
        "message": "",
    }
    if not result["model"]:
        result["message"] = "No Hugging Face model id is configured."
        return result

    try:
        from huggingface_hub import HfApi  # type: ignore
    except Exception as exc:  # pragma: no cover - env dependent
        result["message"] = (
            f"The 'huggingface_hub' package is required to check model "
            f"availability ({type(exc).__name__})."
        )
        return result

    try:
        info = HfApi().model_info(
            result["model"],
            expand=["inferenceProviderMapping"],
            token=token or None,
            timeout=timeout,
        )
    except Exception as exc:
        result["message"] = (
            f"Could not read model '{result['model']}' from the Hugging Face Hub "
            f"({type(exc).__name__}: {exc})."
        )
        return result

    mappings = getattr(info, "inference_provider_mapping", None) or []
    live: List[str] = []
    all_providers: List[str] = []
    for mapping in mappings:
        name = str(getattr(mapping, "provider", "") or "")
        if not name:
            continue
        all_providers.append(name)
        if str(getattr(mapping, "status", "") or "").lower() == "live":
            live.append(name)

    result["providers"] = live or all_providers
    pinned = (provider or "").strip().lower()
    if pinned:
        result["available"] = pinned in [p.lower() for p in live]
    else:
        result["available"] = bool(live)

    if not result["available"]:
        result["message"] = (
            f"Model '{result['model']}' is not currently served by a live "
            "inference provider."
        )
    return result


def _extract_content(response: Any) -> str:
    """Best-effort extraction of the assistant message text from a response."""
    try:
        return response.choices[0].message.content or ""
    except Exception:  # pragma: no cover - defensive
        pass
    # Fallback for dict-like responses (e.g. raw JSON).
    try:
        return response["choices"][0]["message"]["content"] or ""  # type: ignore[index]
    except Exception:
        return ""


class FakeLLMClient:
    """Deterministic in-memory LLM client used **only** by tests.

    It echoes the prompt and source count so tests can assert wiring without
    any network calls. It is intentionally not registered as a default anywhere
    in production code.
    """

    def __init__(self, response: Optional[str] = None, *, configured: bool = True) -> None:
        self._response = response or "FAKE_ANSWER"
        self._configured = configured
        self._model = "fake-llm"
        self.calls: List[Dict[str, Any]] = []

    @property
    def is_configured(self) -> bool:
        return self._configured

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self._response


def build_llm_client(settings: Settings) -> LLMClient:
    """Construct the configured LLM client from :class:`Settings`.

    The provider is selected via ``LLM_PROVIDER`` (default ``openai``):

    * ``huggingface`` / ``hf`` / ``hf-inference`` → :class:`HuggingFaceClient`
      (Hugging Face Inference Providers).
    * ``openai`` / ``openai-compatible`` / ``together`` / ``groq`` /
      ``openrouter`` → :class:`OpenAICompatibleClient`.

    Unknown providers raise a clear error rather than silently failing.
    """
    provider = (settings.llm_provider or "openai").strip().lower()
    if provider in HUGGINGFACE_PROVIDER_NAMES:
        return HuggingFaceClient(settings)
    if provider in {"openai", "openai-compatible", "together", "groq", "openrouter"}:
        return OpenAICompatibleClient(settings)
    raise LLMNotConfiguredError(f"Unknown LLM_PROVIDER: {provider!r}")
