"""
OllamaBackend tests: health/generate against a mocked local endpoint (no
real Ollama server), connection reuse across jobs, and clean timeout /
connection-failure handling. No network access is used.
"""

import time

import pytest
import requests

from inference.errors import BackendTimeoutError, BackendUnavailableError
from inference.ollama_backend import OllamaBackend
from inference.types import GenerateRequest, Message


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.get_calls = []
        self.post_calls = []
        self.get_response = FakeResponse(200, {"models": [{"name": "qwen3:8b"}]})
        self.post_response = FakeResponse(200, {
            "message": {"content": "hello"}, "prompt_eval_count": 12, "eval_count": 4,
        })
        self.get_side_effect = None
        self.post_side_effect = None

    def get(self, url, timeout=None):
        self.get_calls.append(url)
        if self.get_side_effect:
            raise self.get_side_effect
        return self.get_response

    def post(self, url, json=None, timeout=None):
        self.post_calls.append((url, json))
        if self.post_side_effect:
            raise self.post_side_effect
        return self.post_response

    def close(self):
        pass


def _request(text="hi"):
    return GenerateRequest(messages=[Message(role="user", content=text)], max_output_tokens=32)


@pytest.fixture
def fake_session(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr("inference.ollama_backend.requests.Session", lambda: session)
    return session


async def test_health_reports_healthy_when_model_present(fake_session):
    backend = OllamaBackend("qwen3:8b", endpoint="http://127.0.0.1:11434")
    health = await backend.health()
    assert health.healthy is True
    assert health.model_loaded is True


async def test_health_reports_unhealthy_when_model_missing(fake_session):
    fake_session.get_response = FakeResponse(200, {"models": [{"name": "other-model"}]})
    backend = OllamaBackend("qwen3:8b")
    health = await backend.health()
    assert health.healthy is False
    assert "qwen3:8b" in health.detail


async def test_health_reports_unhealthy_on_connection_error(fake_session):
    fake_session.get_side_effect = requests.ConnectionError("refused")
    backend = OllamaBackend("qwen3:8b")
    health = await backend.health()
    assert health.healthy is False
    assert "Could not connect" in health.detail


async def test_generate_returns_text_and_token_counts(fake_session):
    backend = OllamaBackend("qwen3:8b")
    response = await backend.generate(_request())
    assert response.text == "hello"
    assert response.input_tokens == 12
    assert response.output_tokens == 4
    assert fake_session.post_calls[0][0].endswith("/api/chat")


async def test_generate_uses_keep_alive_to_stay_warm(fake_session):
    backend = OllamaBackend("qwen3:8b", keep_alive="30m")
    await backend.generate(_request())
    _, payload = fake_session.post_calls[0]
    assert payload["keep_alive"] == "30m"
    assert payload["stream"] is False


async def test_generate_disables_thinking_so_reasoning_models_dont_starve_content(fake_session):
    """qwen3 and other reasoning models otherwise burn max_output_tokens on
    a separate `message.thinking` field and leave `message.content` (what
    we read) empty."""
    backend = OllamaBackend("qwen3:8b")
    await backend.generate(_request())
    _, payload = fake_session.post_calls[0]
    assert payload["think"] is False


async def test_generate_raises_on_connection_error(fake_session):
    fake_session.post_side_effect = requests.ConnectionError("refused")
    backend = OllamaBackend("qwen3:8b")
    with pytest.raises(BackendUnavailableError):
        await backend.generate(_request())


async def test_generate_raises_timeout_error(fake_session):
    def slow_post(url, json=None, timeout=None):
        time.sleep(0.2)
        return fake_session.post_response

    fake_session.post = slow_post
    backend = OllamaBackend("qwen3:8b", total_timeout_s=0.02)
    with pytest.raises(BackendTimeoutError):
        await backend.generate(_request())


async def test_session_is_reused_across_multiple_generate_calls(fake_session):
    """The whole point of a persistent backend: one connection-pooled
    Session serves every job, it isn't rebuilt per request."""
    backend = OllamaBackend("qwen3:8b")
    assert backend._session is fake_session  # constructed once, from __init__

    for _ in range(5):
        await backend.generate(_request())

    assert backend._session is fake_session  # still the exact same Session object
    assert len(fake_session.post_calls) == 5


async def test_api_key_env_sets_auth_header(monkeypatch, fake_session):
    monkeypatch.setenv("FAKE_OLLAMA_KEY", "super-secret-token")
    OllamaBackend("qwen3:8b", api_key_env="FAKE_OLLAMA_KEY")
    assert fake_session.headers["Authorization"] == "Bearer super-secret-token"
