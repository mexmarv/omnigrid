"""Importing this package registers every installed handler (see base.py)."""

from . import tensor_op, onnx_infer  # noqa: F401
from .base import get_handler, installed_task_types

try:
    from . import llm_infer  # noqa: F401
except ImportError:
    pass  # llama-cpp-python not installed on this provider -- llm_infer stays unavailable

__all__ = ["get_handler", "installed_task_types"]
