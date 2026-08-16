"""
InferenceManager: one persistent backend instance per configured model,
startup health checks, unhealthy models excluded from availability, a
per-model concurrency cap, and clean shutdown. Uses fake backends -- no
real Ollama/llama.cpp involved.
"""

import asyncio

from inference.config import ModelConfig
from inference.manager import InferenceManager
from inference.types import BackendHealth, GenerateRequest, GenerateResponse, Message


class FakeBackend:
    def __init__(self, name, healthy=True):
        self.name = name
        self.healthy = healthy
        self.generate_calls = 0
        self.closed = False
        self.concurrent = 0
        self.max_concurrent_seen = 0

    async def health(self):
        return BackendHealth(healthy=self.healthy, detail="ok" if self.healthy else "simulated failure")

    async def generate(self, request):
        self.concurrent += 1
        self.max_concurrent_seen = max(self.max_concurrent_seen, self.concurrent)
        await asyncio.sleep(0.05)
        self.generate_calls += 1
        self.concurrent -= 1
        return GenerateResponse(text=f"{self.name}-response")

    async def close(self):
        self.closed = True


def _cfg(name, max_concurrency=1):
    return ModelConfig(
        public_name=name, backend="ollama", max_context_tokens=4096,
        max_output_tokens=512, max_concurrency=max_concurrency, local_model=f"{name}:latest",
    )


def _request():
    return GenerateRequest(messages=[Message(role="user", content="hi")], max_output_tokens=16)


async def test_start_excludes_unhealthy_models_from_availability():
    healthy_backend = FakeBackend("good")
    unhealthy_backend = FakeBackend("bad", healthy=False)
    manager = InferenceManager([_cfg("good"), _cfg("bad")])
    manager._build_backend = lambda cfg: {"good": healthy_backend, "bad": unhealthy_backend}[cfg.public_name]

    health = await manager.start()
    assert health["good"].healthy is True
    assert health["bad"].healthy is False
    assert manager.available_models() == ["good"]


async def test_generate_reuses_the_same_backend_instance_across_jobs():
    backend = FakeBackend("good")
    build_calls = []

    def build(cfg):
        build_calls.append(cfg.public_name)
        return backend

    manager = InferenceManager([_cfg("good")])
    manager._build_backend = build
    await manager.start()

    for _ in range(4):
        response = await manager.generate("good", _request())
        assert response.text == "good-response"

    assert build_calls == ["good"]  # backend built exactly once, reused for every job
    assert backend.generate_calls == 4


async def test_concurrency_limit_is_enforced():
    backend = FakeBackend("limited")
    manager = InferenceManager([_cfg("limited", max_concurrency=2)])
    manager._build_backend = lambda cfg: backend
    await manager.start()

    await asyncio.gather(*[manager.generate("limited", _request()) for _ in range(6)])
    assert backend.max_concurrent_seen <= 2
    assert backend.generate_calls == 6


async def test_generate_unknown_model_raises_keyerror():
    manager = InferenceManager([])
    await manager.start()
    try:
        await manager.generate("nope", _request())
        assert False, "expected KeyError"
    except KeyError:
        pass


async def test_close_closes_every_backend():
    backends = {"a": FakeBackend("a"), "b": FakeBackend("b")}
    manager = InferenceManager([_cfg("a"), _cfg("b")])
    manager._build_backend = lambda cfg: backends[cfg.public_name]
    await manager.start()

    await manager.close()
    assert all(b.closed for b in backends.values())
