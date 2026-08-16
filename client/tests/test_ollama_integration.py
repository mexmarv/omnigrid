"""
Optional integration test against a REAL, already-running local Ollama
server -- skipped unless both OMNIGRID_TEST_OLLAMA_URL and
OMNIGRID_TEST_OLLAMA_MODEL are set. Every other test in this suite mocks
the network/subprocess layer; this one is the deliberate exception, for
whoever wants to verify the real thing before deploying:

    OMNIGRID_TEST_OLLAMA_URL=http://127.0.0.1:11434 \\
    OMNIGRID_TEST_OLLAMA_MODEL=qwen3:8b \\
    pytest tests/test_ollama_integration.py
"""

import os

import pytest

from inference.ollama_backend import OllamaBackend
from inference.types import GenerateRequest, Message

OLLAMA_URL = os.environ.get("OMNIGRID_TEST_OLLAMA_URL")
OLLAMA_MODEL = os.environ.get("OMNIGRID_TEST_OLLAMA_MODEL")

pytestmark = pytest.mark.skipif(
    not (OLLAMA_URL and OLLAMA_MODEL),
    reason="set OMNIGRID_TEST_OLLAMA_URL and OMNIGRID_TEST_OLLAMA_MODEL to run against a real Ollama server",
)


async def test_real_ollama_health_and_generate_and_reuse():
    backend = OllamaBackend(OLLAMA_MODEL, endpoint=OLLAMA_URL)
    try:
        health = await backend.health()
        assert health.healthy, health.detail

        for _ in range(2):  # same backend instance, proving warm reuse works for real too
            response = await backend.generate(GenerateRequest(
                messages=[Message(role="user", content="Reply with just the word: hello")],
                max_output_tokens=16,
            ))
            assert response.text.strip()
    finally:
        await backend.close()
