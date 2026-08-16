"""
API keys must never appear in a backend's error messages/health detail --
those often get logged or surfaced back through job failure text.
"""

import requests

from inference.llamacpp_backend import LlamaCppBackend
from inference.ollama_backend import OllamaBackend
from inference.types import GenerateRequest, Message

SECRET = "sk-super-secret-value-should-never-leak"


class ErroringSession:
    def __init__(self):
        self.headers = {}

    def get(self, *a, **k):
        raise requests.ConnectionError("refused")

    def post(self, *a, **k):
        raise requests.ConnectionError("refused")

    def close(self):
        pass


def _request():
    return GenerateRequest(messages=[Message(role="user", content="hi")], max_output_tokens=8)


async def test_ollama_health_error_never_leaks_api_key(monkeypatch):
    monkeypatch.setenv("SECRET_ENV", SECRET)
    monkeypatch.setattr("inference.ollama_backend.requests.Session", lambda: ErroringSession())
    backend = OllamaBackend("qwen3:8b", api_key_env="SECRET_ENV")
    health = await backend.health()
    assert SECRET not in health.detail


async def test_ollama_generate_error_never_leaks_api_key(monkeypatch):
    monkeypatch.setenv("SECRET_ENV", SECRET)
    monkeypatch.setattr("inference.ollama_backend.requests.Session", lambda: ErroringSession())
    backend = OllamaBackend("qwen3:8b", api_key_env="SECRET_ENV")
    try:
        await backend.generate(_request())
        assert False, "expected an exception"
    except Exception as exc:
        assert SECRET not in str(exc)


async def test_llamacpp_missing_binary_error_never_leaks_api_key(monkeypatch):
    monkeypatch.setenv("SECRET_ENV", SECRET)
    monkeypatch.setattr("inference.llamacpp_backend.shutil.which", lambda name: None)
    backend = LlamaCppBackend("/models/model.gguf", api_key_env="SECRET_ENV")
    health = await backend.health()
    assert SECRET not in health.detail
    try:
        await backend.generate(_request())
        assert False, "expected an exception"
    except Exception as exc:
        assert SECRET not in str(exc)
