"""
Importing this package registers every installed sandboxed handler (see
base.py) -- fixed, short-lived operations that still run in sandbox.py's
subprocess.

llm_infer/vlm_infer are NOT registered here: they're long-running,
persistent-backend jobs (client/inference/), routed by agent.py straight
to an already-warm InferenceManager instead of a per-job subprocess. See
client/inference/manager.py and agent.py's run_generation_job().
"""

from . import tensor_op, onnx_infer  # noqa: F401
from .base import get_handler, installed_task_types

__all__ = ["get_handler", "installed_task_types"]
