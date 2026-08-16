"""
Persistent provider-side inference backends (Phase 1) and the validated
generation request schema (Phase 2) -- see individual modules for details.
"""

from .config import ConfigError, ModelConfig, legacy_llamacpp_config, load_model_configs, merge_configs
from .errors import BackendError, BackendTimeoutError, BackendUnavailableError
from .llamacpp_backend import LlamaCppBackend
from .manager import InferenceManager
from .ollama_backend import OllamaBackend
from .schema import ValidationError, normalize_generate_payload
from .types import BackendHealth, GenerateRequest, GenerateResponse, InferenceBackend, Message

__all__ = [
    "ConfigError", "ModelConfig", "legacy_llamacpp_config", "load_model_configs", "merge_configs",
    "BackendError", "BackendTimeoutError", "BackendUnavailableError",
    "LlamaCppBackend", "InferenceManager", "OllamaBackend",
    "ValidationError", "normalize_generate_payload",
    "BackendHealth", "GenerateRequest", "GenerateResponse", "InferenceBackend", "Message",
]
