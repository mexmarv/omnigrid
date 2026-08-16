"""
InferenceManager -- owns one persistent InferenceBackend instance per
configured model, for the lifetime of the provider process.

Building each backend once here and reusing it across every job (instead
of instantiating one per job inside agent.py's loop) is exactly what
eliminates the reload-per-request behavior the old sandboxed llm_infer/
vlm_infer handlers had.
"""

import asyncio
import logging

from .config import ModelConfig
from .llamacpp_backend import LlamaCppBackend
from .ollama_backend import OllamaBackend
from .types import BackendHealth, GenerateRequest, GenerateResponse, InferenceBackend

logger = logging.getLogger("omnigrid.inference")


class InferenceManager:
    def __init__(self, configs: list[ModelConfig]):
        self._configs: dict[str, ModelConfig] = {c.public_name: c for c in configs}
        self._backends: dict[str, InferenceBackend] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._last_health: dict[str, BackendHealth] = {}

    def _build_backend(self, cfg: ModelConfig) -> InferenceBackend:
        if cfg.backend == "ollama":
            return OllamaBackend(cfg.local_model, endpoint=cfg.endpoint, api_key_env=cfg.api_key_env)
        if cfg.backend == "llamacpp":
            return LlamaCppBackend(
                cfg.model_path,
                mmproj_path=cfg.mmproj_path,
                n_gpu_layers=cfg.n_gpu_layers if cfg.n_gpu_layers is not None else -1,
                n_ctx=cfg.max_context_tokens,
                server_binary=cfg.server_binary,
                api_key_env=cfg.api_key_env,
            )
        raise ValueError(f"Unknown backend '{cfg.backend}'.")  # config.py already rejects this earlier

    async def start(self) -> dict[str, BackendHealth]:
        """Builds every configured backend and runs its startup health check.

        An unhealthy model is kept registered (so it can recover on a later
        heartbeat) but excluded from available_models() -- and therefore from
        what the provider announces as capacity -- until it reports healthy.
        """
        for name, cfg in self._configs.items():
            backend = self._build_backend(cfg)
            self._backends[name] = backend
            self._semaphores[name] = asyncio.Semaphore(cfg.max_concurrency)
            health = await backend.health()
            self._last_health[name] = health
            if health.healthy:
                logger.info("model '%s' (%s) is healthy and ready.", name, cfg.backend)
            else:
                logger.warning(
                    "model '%s' (%s) failed its startup health check: %s", name, cfg.backend, health.detail
                )
        return dict(self._last_health)

    def model_config(self, public_name: str) -> ModelConfig | None:
        return self._configs.get(public_name)

    def is_configured(self, public_name: str) -> bool:
        return public_name in self._configs

    def available_models(self) -> list[str]:
        return [name for name, health in self._last_health.items() if health.healthy]

    async def generate(self, public_name: str, request: GenerateRequest) -> GenerateResponse:
        if public_name not in self._backends:
            raise KeyError(f"No backend configured for model '{public_name}'.")
        async with self._semaphores[public_name]:
            return await self._backends[public_name].generate(request)

    async def close(self) -> None:
        for backend in self._backends.values():
            try:
                await backend.close()
            except Exception:
                logger.exception("error closing an inference backend during shutdown")
