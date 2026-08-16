"""
agent.run_generation_job(): the Phase 2 execution path that routes
llm_infer/vlm_infer jobs straight to a persistent InferenceManager instead
of sandbox.py's per-job subprocess. Covers persistent reuse across jobs,
legacy prompt backward compatibility, payload validation rejection, and
backend failure/timeout handling -- none of it should ever raise out of
agent.py (a bad job must fail cleanly, not crash the provider daemon).
"""

import asyncio
import base64
import json

import pytest

import agent
from inference.config import ModelConfig
from inference.errors import BackendError
from inference.manager import InferenceManager
from inference.types import BackendHealth, GenerateResponse


class FakeBackend:
    def __init__(self, healthy=True, text="generated text", delay=0.0, raise_error=None):
        self.healthy = healthy
        self.text = text
        self.delay = delay
        self.raise_error = raise_error
        self.generate_calls = 0

    async def health(self):
        return BackendHealth(healthy=self.healthy, detail="ok" if self.healthy else "down")

    async def generate(self, request):
        self.generate_calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_error:
            raise self.raise_error
        return GenerateResponse(text=self.text, input_tokens=5, output_tokens=3)

    async def close(self):
        pass


def _payload_b64(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _job(task_type, payload, timeout_s=30, job_id=1):
    return {"id": job_id, "task_type": task_type, "payload_b64": _payload_b64(payload), "timeout_s": timeout_s}


async def _manager_with(backend, public_name="qwen3-8b-m4", vision=False, **cfg_kwargs):
    cfg = ModelConfig(
        public_name=public_name, backend="ollama", max_context_tokens=4096, max_output_tokens=512,
        local_model=f"{public_name}:latest", vision=vision, **cfg_kwargs,
    )
    manager = InferenceManager([cfg])
    manager._build_backend = lambda c: backend
    await manager.start()
    return manager


async def test_new_schema_job_succeeds():
    backend = FakeBackend(text="hello world")
    manager = await _manager_with(backend)
    job = _job("llm_infer:qwen3-8b-m4", {"messages": [{"role": "user", "content": "hi"}], "max_output_tokens": 32})

    status, result_b64, error, compute_seconds = await agent.run_generation_job(job, manager)

    assert status == "done"
    assert error is None
    result = json.loads(base64.b64decode(result_b64))
    assert result["text"] == "hello world"
    assert result["input_tokens"] == 5


async def test_legacy_prompt_payload_still_works():
    backend = FakeBackend(text="legacy ok")
    manager = await _manager_with(backend)
    job = _job("llm_infer:qwen3-8b-m4", {"prompt": "hello", "max_tokens": 32, "temperature": 0.5})

    status, result_b64, error, _ = await agent.run_generation_job(job, manager)

    assert status == "done"
    result = json.loads(base64.b64decode(result_b64))
    assert result["text"] == "legacy ok"


async def test_backend_is_not_rebuilt_across_multiple_jobs():
    backend = FakeBackend()
    manager = await _manager_with(backend)
    for i in range(3):
        job = _job("llm_infer:qwen3-8b-m4", {"prompt": f"hello {i}"}, job_id=i)
        status, _, _, _ = await agent.run_generation_job(job, manager)
        assert status == "done"
    assert backend.generate_calls == 3  # same backend instance served all three jobs


async def test_invalid_payload_fails_the_job_without_raising():
    backend = FakeBackend()
    manager = await _manager_with(backend)
    job = _job("llm_infer:qwen3-8b-m4", {"messages": [{"role": "tool", "content": "hi"}]})

    status, result_b64, error, _ = await agent.run_generation_job(job, manager)

    assert status == "failed"
    assert result_b64 is None
    assert "role" in error
    assert backend.generate_calls == 0  # rejected before ever reaching the backend


async def test_unsupported_field_is_rejected():
    backend = FakeBackend()
    manager = await _manager_with(backend)
    job = _job("llm_infer:qwen3-8b-m4", {"prompt": "hi", "model_path": "/etc/shadow"})

    status, _, error, _ = await agent.run_generation_job(job, manager)
    assert status == "failed"
    assert "Unsupported field" in error


async def test_unknown_model_fails_cleanly():
    backend = FakeBackend()
    manager = await _manager_with(backend)
    job = _job("llm_infer:not-a-real-model", {"prompt": "hi"})

    status, result_b64, error, _ = await agent.run_generation_job(job, manager)
    assert status == "failed"
    assert result_b64 is None
    assert "not-a-real-model" in error


async def test_unhealthy_model_fails_cleanly():
    backend = FakeBackend(healthy=False)
    manager = await _manager_with(backend)
    job = _job("llm_infer:qwen3-8b-m4", {"prompt": "hi"})

    status, _, error, _ = await agent.run_generation_job(job, manager)
    assert status == "failed"
    assert "No healthy backend" in error


async def test_backend_error_fails_the_job_without_raising():
    backend = FakeBackend(raise_error=BackendError("upstream exploded"))
    manager = await _manager_with(backend)
    job = _job("llm_infer:qwen3-8b-m4", {"prompt": "hi"})

    status, _, error, _ = await agent.run_generation_job(job, manager)
    assert status == "failed"
    assert "upstream exploded" in error


async def test_generation_timeout_fails_cleanly():
    backend = FakeBackend(delay=0.3)
    manager = await _manager_with(backend)
    job = _job("llm_infer:qwen3-8b-m4", {"prompt": "hi"}, timeout_s=1)
    # force run_generation_job's own timeout ceiling down for a fast test
    original_cap = agent.MAX_GENERATION_TIMEOUT_S
    job["timeout_s"] = 0
    job_with_short_timeout = dict(job, timeout_s=None)
    try:
        agent.MAX_GENERATION_TIMEOUT_S = 0.05
        status, _, error, _ = await agent.run_generation_job(job_with_short_timeout, manager)
    finally:
        agent.MAX_GENERATION_TIMEOUT_S = original_cap
    assert status == "failed"
    assert "exceeded" in error


async def test_vision_job_allows_image_and_llm_job_rejects_it():
    vlm_backend = FakeBackend(text="a cat")
    manager = await _manager_with(vlm_backend, public_name="smolvlm", vision=True)
    ok_job = _job("vlm_infer:smolvlm", {"prompt": "describe", "image_b64": "ZmFrZQ=="})
    status, result_b64, error, _ = await agent.run_generation_job(ok_job, manager)
    assert status == "done"

    llm_backend = FakeBackend()
    llm_manager = await _manager_with(llm_backend, public_name="qwen3-8b-m4")
    bad_job = _job("llm_infer:qwen3-8b-m4", {"prompt": "describe", "image_b64": "ZmFrZQ=="})
    status, _, error, _ = await agent.run_generation_job(bad_job, llm_manager)
    assert status == "failed"
    assert "image" in error
