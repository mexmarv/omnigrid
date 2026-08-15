"""
Runs one handler call in its own OS process with a hard wall-clock timeout
and a best-effort memory cap, so a runaway or malformed job can't hang or
crash the agent -- it just gets killed and reported as failed.

This is process-level isolation (crash/hang containment), not a security
sandbox against malicious code -- that protection comes from never running
requester-supplied code at all (see handlers/base.py).
"""

import multiprocessing as mp
import platform
import time

IS_POSIX = platform.system() != "Windows"

if IS_POSIX:
    import resource


def _child(task_type: str, payload_b64: str, ram_limit_mb: int, queue: mp.Queue):
    if IS_POSIX:
        limit_bytes = ram_limit_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        except (ValueError, OSError):
            pass  # some platforms cap how far RLIMIT_AS can be lowered; best-effort

    import handlers  # imported here (not at module load) so the rlimit above covers it too

    fn = handlers.get_handler(task_type)
    if fn is None:
        queue.put(("error", f"No handler installed for task_type '{task_type}'."))
        return
    try:
        result_b64 = fn(payload_b64)
        queue.put(("ok", result_b64))
    except Exception as exc:  # deliberately broad: a bad job must not crash the agent
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


def run(task_type: str, payload_b64: str, ram_limit_mb: int, timeout_s: int):
    """Returns (status, result_b64_or_None, error_or_None, compute_seconds)."""
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=_child, args=(task_type, payload_b64, ram_limit_mb, queue))

    start = time.time()
    proc.start()
    proc.join(timeout_s)
    compute_seconds = time.time() - start

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
        return "failed", None, f"Job exceeded {timeout_s}s timeout and was killed.", compute_seconds

    if not queue.empty():
        status, payload = queue.get()
        if status == "ok":
            return "done", payload, None, compute_seconds
        return "failed", None, payload, compute_seconds

    return "failed", None, f"Worker process exited unexpectedly (code {proc.exitcode}).", compute_seconds
