"""Tests for the Hugging Face Inference Providers LLM client.

Requirement #13 asks for coverage of: a successful generation, incorrect
credentials, model unavailability, timeouts, and unusable responses.

Every test here runs fully offline: ``huggingface_hub.InferenceClient`` and
``huggingface_hub.HfApi`` are replaced with recording stand-ins, so no token,
network call or paid inference is involved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.config import Settings

HF_MODEL = "meta-llama/Llama-3.1-8B-Instruct"
HF_TOKEN = "hf_test_token_1234567890"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _settings(**overrides: Any) -> Settings:
    """A Settings instance wired for Hugging Face, with overrides applied."""
    base: Dict[str, Any] = {
        "data_raw_dir": Path("/tmp/raw"),
        "data_processed_dir": Path("/tmp/proc"),
        "chroma_path": Path("/tmp/chroma"),
        "collection_name": "test",
        "llm_provider": "huggingface",
        "hf_token": HF_TOKEN,
        "hf_model_id": HF_MODEL,
        "hf_provider": None,
        "llm_api_key": None,
        "llm_model": None,
        "llm_request_timeout": 30.0,
    }
    base.update(overrides)
    return Settings(**base)


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _FakeInferenceClient:
    """Stands in for ``huggingface_hub.InferenceClient``."""

    instances: List["_FakeInferenceClient"] = []
    response_text = "Apply 2 t/ha of agricultural lime before sowing."
    error: Optional[Exception] = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.calls: List[Dict[str, Any]] = []
        _FakeInferenceClient.instances.append(self)

    def chat_completion(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if _FakeInferenceClient.error is not None:
            raise _FakeInferenceClient.error
        if isinstance(_FakeInferenceClient.response_text, str):
            return _Response(_FakeInferenceClient.response_text)
        # A non-string stands in for a raw, differently-shaped provider payload.
        return _FakeInferenceClient.response_text


@pytest.fixture
def fake_inference_client(monkeypatch):
    pytest.importorskip("huggingface_hub")
    _FakeInferenceClient.instances = []
    _FakeInferenceClient.response_text = "Apply 2 t/ha of agricultural lime before sowing."
    _FakeInferenceClient.error = None
    monkeypatch.setattr(
        "huggingface_hub.InferenceClient", _FakeInferenceClient, raising=True
    )
    yield _FakeInferenceClient
    _FakeInferenceClient.error = None


def _client(**overrides):
    from src.llm_client import HuggingFaceClient

    return HuggingFaceClient(_settings(**overrides))


# ---------------------------------------------------------------------------
# Successful generation
# ---------------------------------------------------------------------------
class TestSuccessfulGeneration:
    def test_generate_returns_the_model_completion(self, fake_inference_client) -> None:
        assert _client().generate("How do I fix acidic soil?") == (
            "Apply 2 t/ha of agricultural lime before sowing."
        )

    def test_generate_sends_a_system_and_a_user_message(self, fake_inference_client) -> None:
        _client().generate("How do I fix acidic soil?", system="You are FarmIQ.")

        sent = fake_inference_client.instances[0].calls[0]
        assert sent["messages"] == [
            {"role": "system", "content": "You are FarmIQ."},
            {"role": "user", "content": "How do I fix acidic soil?"},
        ]

    def test_generate_omits_the_system_message_when_none_is_given(
        self, fake_inference_client
    ) -> None:
        _client().generate("hello")
        assert fake_inference_client.instances[0].calls[0]["messages"] == [
            {"role": "user", "content": "hello"}
        ]

    def test_generate_forwards_temperature_and_max_tokens(self, fake_inference_client) -> None:
        _client().generate("hi", temperature=0.1, max_tokens=123)
        sent = fake_inference_client.instances[0].calls[0]
        assert sent["temperature"] == 0.1
        assert sent["max_tokens"] == 123

    def test_generate_falls_back_to_the_configured_sampling_defaults(
        self, fake_inference_client
    ) -> None:
        from src.config import get_settings

        expected = get_settings()
        _client().generate("hi")
        sent = fake_inference_client.instances[0].calls[0]
        assert sent["temperature"] == expected.llm_temperature
        assert sent["max_tokens"] == expected.llm_max_tokens

    def test_the_model_is_named_explicitly_on_every_call(self, fake_inference_client) -> None:
        _client().generate("hi")
        assert fake_inference_client.instances[0].calls[0]["model"] == HF_MODEL

    def test_a_dict_shaped_response_is_also_accepted(self, fake_inference_client) -> None:
        # Some providers return raw JSON rather than an OpenAI-style object.
        fake_inference_client.response_text = {
            "choices": [{"message": {"content": "Dict shaped answer."}}]
        }
        assert _client().generate("hi") == "Dict shaped answer."

    def test_the_client_satisfies_the_llm_client_protocol(self) -> None:
        from src.llm_client import LLMClient

        assert isinstance(_client(), LLMClient)


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------
class TestConstruction:
    def test_the_official_client_is_built_with_model_token_and_timeout(
        self, fake_inference_client
    ) -> None:
        _client().generate("hi")
        kwargs = fake_inference_client.instances[0].kwargs
        assert kwargs["model"] == HF_MODEL
        assert kwargs["token"] == HF_TOKEN
        assert kwargs["timeout"] == 30.0
        # No provider pin means "let the Hub route it".
        assert "provider" not in kwargs

    def test_a_pinned_provider_is_forwarded(self, fake_inference_client) -> None:
        _client(hf_provider="deepinfra").generate("hi")
        assert fake_inference_client.instances[0].kwargs["provider"] == "deepinfra"

    def test_the_client_is_built_once_and_reused(self, fake_inference_client) -> None:
        client = _client()
        client.generate("first")
        client.generate("second")
        assert len(fake_inference_client.instances) == 1
        assert len(fake_inference_client.instances[0].calls) == 2

    def test_the_reported_model_name_is_the_configured_model(self) -> None:
        client = _client()
        assert client.model_name == HF_MODEL
        assert client.provider == ""
        assert client.is_configured is True


# ---------------------------------------------------------------------------
# Incorrect / missing credentials
# ---------------------------------------------------------------------------
class TestCredentials:
    def test_a_missing_token_is_reported_as_not_configured(self) -> None:
        client = _client(hf_token=None, llm_api_key=None)
        assert client.is_configured is False

    def test_a_missing_model_is_reported_as_not_configured(self) -> None:
        client = _client(hf_model_id=None, llm_model=None)
        assert client.is_configured is False

    def test_generating_without_credentials_explains_what_to_set(self) -> None:
        from src.llm_client import LLMNotConfiguredError

        client = _client(hf_token=None, llm_api_key=None)
        with pytest.raises(LLMNotConfiguredError, match="HF_TOKEN, HF_MODEL_ID"):
            client.generate("hello")

    def test_the_llm_aliases_are_accepted(self) -> None:
        client = _client(hf_token=None, hf_model_id=None,
                         llm_api_key=HF_TOKEN, llm_model=HF_MODEL)
        assert client.is_configured is True
        assert client.model_name == HF_MODEL

    def test_a_rejected_token_raises_a_request_error(self, fake_inference_client) -> None:
        from src.llm_client import LLMRequestError

        fake_inference_client.error = RuntimeError("401 Unauthorized")
        with pytest.raises(LLMRequestError, match="Hugging Face request failed"):
            _client().generate("hi")

    def test_a_failed_request_never_echoes_the_token(self, fake_inference_client) -> None:
        from src.llm_client import LLMRequestError

        # Worst case: the provider's SDK includes the credential in its message.
        fake_inference_client.error = RuntimeError(f"Invalid token: {HF_TOKEN}")
        with pytest.raises(LLMRequestError) as excinfo:
            _client().generate("hi")
        assert HF_TOKEN not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Timeouts and unusable responses
# ---------------------------------------------------------------------------
class TestFailures:
    def test_a_timeout_raises_a_request_error(self, fake_inference_client) -> None:
        from src.llm_client import LLMRequestError

        fake_inference_client.error = TimeoutError("request timed out")
        with pytest.raises(LLMRequestError, match="TimeoutError"):
            _client().generate("hi")

    def test_an_empty_completion_raises_a_request_error(self, fake_inference_client) -> None:
        from src.llm_client import LLMRequestError

        fake_inference_client.response_text = ""
        with pytest.raises(LLMRequestError, match="empty completion"):
            _client().generate("hi")

    def test_a_malformed_response_raises_a_request_error(self, fake_inference_client) -> None:
        from src.llm_client import LLMRequestError

        fake_inference_client.response_text = {"unexpected": True}
        with pytest.raises(LLMRequestError, match="empty completion"):
            _client().generate("hi")


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
class TestBuildLLMClient:
    @pytest.mark.parametrize("provider", ["huggingface", "hf", "hf-inference", "HUGGINGFACE"])
    def test_huggingface_providers_select_the_huggingface_client(self, provider) -> None:
        from src.llm_client import HuggingFaceClient, build_llm_client

        assert isinstance(build_llm_client(_settings(llm_provider=provider)), HuggingFaceClient)

    def test_openai_provider_still_selects_the_openai_compatible_client(self) -> None:
        from src.llm_client import OpenAICompatibleClient, build_llm_client

        settings = _settings(llm_provider="openai", llm_api_key="gsk_x", llm_model="m")
        assert isinstance(build_llm_client(settings), OpenAICompatibleClient)

    def test_an_unknown_provider_is_rejected_loudly(self) -> None:
        from src.llm_client import LLMNotConfiguredError, build_llm_client

        with pytest.raises(LLMNotConfiguredError, match="nonsense"):
            build_llm_client(_settings(llm_provider="nonsense"))


# ---------------------------------------------------------------------------
# Model availability (requirement #4)
# ---------------------------------------------------------------------------
class _Mapping:
    def __init__(self, provider: str, status: str) -> None:
        self.provider = provider
        self.status = status


class _ModelInfo:
    def __init__(self, mappings) -> None:
        self.inference_provider_mapping = mappings


class _FakeHfApi:
    result: Any = None
    error: Optional[Exception] = None
    calls: List[Dict[str, Any]] = []

    def model_info(self, repo_id: str, **kwargs: Any) -> Any:
        _FakeHfApi.calls.append({"repo_id": repo_id, **kwargs})
        if _FakeHfApi.error is not None:
            raise _FakeHfApi.error
        return _FakeHfApi.result


@pytest.fixture
def fake_hf_api(monkeypatch):
    pytest.importorskip("huggingface_hub")
    _FakeHfApi.result = None
    _FakeHfApi.error = None
    _FakeHfApi.calls = []
    monkeypatch.setattr("huggingface_hub.HfApi", _FakeHfApi, raising=True)
    yield _FakeHfApi
    _FakeHfApi.error = None


class TestModelAvailability:
    def test_a_live_provider_makes_the_model_available(self, fake_hf_api) -> None:
        from src.llm_client import check_model_availability

        fake_hf_api.result = _ModelInfo([
            _Mapping("novita", "live"),
            _Mapping("deepinfra", "live"),
            _Mapping("featherless-ai", "error"),
        ])
        result = check_model_availability(HF_MODEL, token=HF_TOKEN)

        assert result["available"] is True
        assert result["providers"] == ["novita", "deepinfra"]
        assert result["provider"] == "auto"
        assert result["message"] == ""

    def test_the_hub_is_asked_for_the_provider_mapping(self, fake_hf_api) -> None:
        from src.llm_client import check_model_availability

        fake_hf_api.result = _ModelInfo([_Mapping("novita", "live")])
        check_model_availability(HF_MODEL, token=HF_TOKEN, timeout=12.5)

        call = fake_hf_api.calls[0]
        assert call["repo_id"] == HF_MODEL
        assert call["expand"] == ["inferenceProviderMapping"]
        assert call["token"] == HF_TOKEN
        assert call["timeout"] == 12.5

    def test_no_live_provider_is_reported_as_unavailable(self, fake_hf_api) -> None:
        from src.llm_client import check_model_availability

        fake_hf_api.result = _ModelInfo([
            _Mapping("novita", "error"),
            _Mapping("featherless-ai", "staging"),
        ])
        result = check_model_availability(HF_MODEL)

        assert result["available"] is False
        # The providers are still listed so an operator can see what exists.
        assert result["providers"] == ["novita", "featherless-ai"]
        assert "not currently served" in result["message"]

    def test_a_model_with_no_providers_at_all_is_unavailable(self, fake_hf_api) -> None:
        from src.llm_client import check_model_availability

        fake_hf_api.result = _ModelInfo([])
        result = check_model_availability("sarvamai/sarvam-1")

        assert result["available"] is False
        assert result["providers"] == []

    def test_a_pinned_provider_that_is_live_makes_the_model_available(self, fake_hf_api) -> None:
        from src.llm_client import check_model_availability

        fake_hf_api.result = _ModelInfo([_Mapping("novita", "live")])
        result = check_model_availability(HF_MODEL, provider="Novita")

        assert result["available"] is True
        assert result["provider"] == "Novita"

    def test_a_pinned_provider_that_is_not_live_is_unavailable(self, fake_hf_api) -> None:
        from src.llm_client import check_model_availability

        fake_hf_api.result = _ModelInfo([_Mapping("novita", "live")])
        result = check_model_availability(HF_MODEL, provider="deepinfra")

        assert result["available"] is False

    def test_a_hub_error_is_reported_instead_of_raised(self, fake_hf_api) -> None:
        from src.llm_client import check_model_availability

        fake_hf_api.error = RuntimeError("401 Client Error: Unauthorized")
        result = check_model_availability(HF_MODEL, token="hf_bad_token")

        assert result["available"] is False
        assert "RuntimeError" in result["message"]
        assert result["model"] == HF_MODEL

    def test_an_unset_model_id_is_reported_instead_of_raised(self, fake_hf_api) -> None:
        from src.llm_client import check_model_availability

        result = check_model_availability("")
        assert result["available"] is False
        assert "No Hugging Face model id" in result["message"]
        assert fake_hf_api.calls == []

    def test_the_report_never_contains_the_token(self, fake_hf_api) -> None:
        from src.llm_client import check_model_availability

        fake_hf_api.error = RuntimeError("401 Unauthorized")
        result = check_model_availability(HF_MODEL, token=HF_TOKEN)
        assert HF_TOKEN not in str(result)

    def test_the_client_delegates_its_availability_check(self, fake_hf_api) -> None:
        from src.llm_client import HuggingFaceClient

        fake_hf_api.result = _ModelInfo([_Mapping("novita", "live")])
        result = HuggingFaceClient(_settings()).check_availability()

        assert result["available"] is True
        assert result["model"] == HF_MODEL
