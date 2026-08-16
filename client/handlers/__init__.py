"""Importing this package registers every installed handler (see base.py)."""

from . import tensor_op, onnx_infer  # noqa: F401
from .base import get_handler, installed_task_types

try:
    from . import llm_infer  # noqa: F401
except ImportError:
    pass  # llama-cpp-python not installed on this provider -- llm_infer stays unavailable

from . import nvidia_vlm  # noqa: F401 -- only needs `requests`, always available

__all__ = ["get_handler", "installed_task_types"]
