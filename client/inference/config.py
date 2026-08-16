"""
Provider model configuration: a YAML file (--models-config /
OMNIGRID_MODELS_CONFIG), merged with any legacy single-model CLI flags
(--llm-model-path/--vlm-model-path) translated into the same shape.
Validated once, synchronously, at startup -- a bad config exits before any
backend is started rather than partially starting.

None of these fields are ever settable by a requester's job payload --
only the provider operator controls which backend/endpoint/local model
serves a given public_name. See inference/schema.py for what IS
requester-controlled (generation parameters only, bounded by the matching
ModelConfig's max_context_tokens/max_output_tokens here).
"""

import os
from dataclasses import dataclass, fields

import yaml

VALID_BACKENDS = {"ollama", "llamacpp"}


class ConfigError(Exception):
    pass


@dataclass
class ModelConfig:
    public_name: str
    backend: str
    max_context_tokens: int
    max_output_tokens: int
    max_concurrency: int = 1
    vision: bool = False

    # backend == "ollama"
    endpoint: str = "http://127.0.0.1:11434"
    local_model: str | None = None

    # backend == "llamacpp"
    model_path: str | None = None
    mmproj_path: str | None = None
    n_gpu_layers: int | None = None
    server_binary: str = "llama-server"

    # optional for either backend, e.g. a secured/shared Ollama endpoint
    # or an llama-server started with --api-key
    api_key_env: str | None = None


def _validate(cfg: ModelConfig) -> None:
    if not cfg.public_name or not cfg.public_name.strip():
        raise ConfigError("Every model needs a non-empty public_name.")
    if cfg.backend not in VALID_BACKENDS:
        raise ConfigError(
            f"model '{cfg.public_name}': backend must be one of {sorted(VALID_BACKENDS)}, got '{cfg.backend}'."
        )
    if cfg.max_context_tokens <= 0:
        raise ConfigError(f"model '{cfg.public_name}': max_context_tokens must be positive.")
    if cfg.max_output_tokens <= 0:
        raise ConfigError(f"model '{cfg.public_name}': max_output_tokens must be positive.")
    if cfg.max_output_tokens > cfg.max_context_tokens:
        raise ConfigError(f"model '{cfg.public_name}': max_output_tokens can't exceed max_context_tokens.")
    if cfg.max_concurrency <= 0:
        raise ConfigError(f"model '{cfg.public_name}': max_concurrency must be positive.")
    if cfg.backend == "ollama" and not cfg.local_model:
        raise ConfigError(f"model '{cfg.public_name}': backend 'ollama' requires local_model.")
    if cfg.backend == "llamacpp" and not cfg.model_path:
        raise ConfigError(f"model '{cfg.public_name}': backend 'llamacpp' requires model_path.")


def load_model_configs(path: str | None) -> list[ModelConfig]:
    """Loads and validates models.yaml. Returns [] if path is None."""
    if not path:
        return []
    if not os.path.isfile(path):
        raise ConfigError(f"models config file not found: {path}")
    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    entries = raw.get("models")
    if entries is None:
        raise ConfigError(f"{path}: expected a top-level 'models:' list.")
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: 'models' must be a list.")

    valid_field_names = {f.name for f in fields(ModelConfig)}
    configs = []
    seen_names = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: models[{i}] must be a mapping.")
        unknown = set(entry) - valid_field_names
        if unknown:
            raise ConfigError(f"{path}: models[{i}] has unsupported field(s): {sorted(unknown)}.")
        try:
            cfg = ModelConfig(**entry)
        except TypeError as exc:
            raise ConfigError(f"{path}: models[{i}] is missing a required field ({exc}).") from exc
        _validate(cfg)
        if cfg.public_name in seen_names:
            raise ConfigError(f"{path}: duplicate public_name '{cfg.public_name}'.")
        seen_names.add(cfg.public_name)
        configs.append(cfg)
    return configs


def legacy_llamacpp_config(
    *,
    public_name: str,
    model_path: str,
    n_gpu_layers: int,
    mmproj_path: str | None = None,
    max_context_tokens: int = 4096,
    max_output_tokens: int = 2048,
) -> ModelConfig:
    """Builds a ModelConfig from the pre-existing --llm-model-path/--vlm-model-path
    CLI flags, so those flags keep working unchanged after this refactor."""
    cfg = ModelConfig(
        public_name=public_name,
        backend="llamacpp",
        max_context_tokens=max_context_tokens,
        max_output_tokens=max_output_tokens,
        model_path=model_path,
        mmproj_path=mmproj_path,
        n_gpu_layers=n_gpu_layers,
        vision=mmproj_path is not None,
    )
    _validate(cfg)
    return cfg


def merge_configs(*groups: list[ModelConfig]) -> list[ModelConfig]:
    merged: list[ModelConfig] = []
    seen = set()
    for group in groups:
        for cfg in group:
            if cfg.public_name in seen:
                raise ConfigError(f"duplicate public_name '{cfg.public_name}' across config sources.")
            seen.add(cfg.public_name)
            merged.append(cfg)
    return merged
