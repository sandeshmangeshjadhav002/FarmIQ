"""LLM client abstraction for FarmIQ-RAG.

The RAG pipeline depends only on the :class:`LLMClient` protocol, so the
underlying provider can be swapped (OpenAI, Together, Groq, a local vLLM, ...)
without touching the pipeline. A concrete :class:`OpenAICompatibleClient`
ships out of the box and works with any OpenAI-compatible Chat Completions API.

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

from src.config import Settings

logger = logging.getLogger(__name__)


class LLMNotConfiguredError(RuntimeError):
    """Raised when answer generation is requested but no provider is configured."""


class LLMRequestError(RuntimeError):
    """Raised when the provider returns an error or an unusable response."""


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
            # Never include the API key in the exception message.
            raise LLMRequestError(
                f"LLM request failed: {type(exc).__name__}: {exc}"
            ) from exc

        text = _extract_content(response)
        if not text:
            raise LLMRequestError("LLM returned an empty completion.")
        return text


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

    The provider is selected via ``LLM_PROVIDER`` (default ``openai``). Unknown
    providers raise a clear error rather than silently failing.
    """
    provider = (settings.llm_provider or "openai").lower()
    if provider in {"openai", "openai-compatible", "together", "groq", "openrouter"}:
        return OpenAICompatibleClient(settings)
    raise LLMNotConfiguredError(f"Unknown LLM_PROVIDER: {provider!r}")
