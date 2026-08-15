"""
What a script, notebook, or AI coding agent imports to offload one unit of
work to the network instead of running it locally.

    import client_sdk as cc
    result = cc.run_tensor_op("matmul", a, b, account_name="marvin", email="you@example.com")

Already have an API key (e.g. from register.php on the web)? Pass it
directly and skip the name/email dance entirely:

    result = cc.run_tensor_op("matmul", a, b, api_key="...")
"""

import base64
import io
import json
import time

import numpy as np
import requests

import credentials


def _resolve_api_key(coordinator, account_name, email, api_key) -> str:
    if api_key:
        return api_key
    if not account_name:
        raise ValueError("Pass either api_key=..., or account_name=... (and email=... if it's new).")
    return credentials.get_api_key(coordinator, account_name, email)


def _submit(coordinator, account_name, email, api_key, task_type, payload: dict,
            cpu_limit, ram_limit_mb, timeout_s):
    resolved_key = _resolve_api_key(coordinator, account_name, email, api_key)
    payload_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    resp = requests.post(
        f"{coordinator}/api/jobs_submit.php",
        headers={"Authorization": f"Bearer {resolved_key}"},
        json={
            "task_type": task_type, "payload_format": "json", "payload_b64": payload_b64,
            "cpu_limit": cpu_limit, "ram_limit_mb": ram_limit_mb, "timeout_s": timeout_s,
        },
    )
    resp.raise_for_status()
    return resp.json()["job_id"]


def _wait_for_result(coordinator, job_id, poll_interval=1.0, max_wait_s=300) -> dict:
    start = time.time()
    while time.time() - start < max_wait_s:
        resp = requests.get(f"{coordinator}/api/jobs_get.php", params={"id": job_id})
        resp.raise_for_status()
        job = resp.json()
        if job["status"] == "done":
            return json.loads(base64.b64decode(job["result_b64"]))
        if job["status"] == "failed":
            raise RuntimeError(f"Job {job_id} failed: {job['error']}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Job {job_id} did not complete within {max_wait_s}s.")


def _encode_array(arr) -> str:
    buf = io.BytesIO()
    np.save(buf, np.asarray(arr), allow_pickle=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _decode_array(b64_str: str) -> np.ndarray:
    return np.load(io.BytesIO(base64.b64decode(b64_str)), allow_pickle=False)


def run_tensor_op(op: str, a, b=None, *, account_name: str | None = None, email: str | None = None,
                   api_key: str | None = None, coordinator="http://127.0.0.1:8000",
                   cpu_limit=1.0, ram_limit_mb=512, timeout_s=30, max_wait_s=300) -> np.ndarray:
    """Offload one of matmul/add/multiply/relu/sum/mean. a/b are array-likes.

    Either pass api_key=... directly (e.g. from register.php), or
    account_name=... (+ email=... the first time that name registers here).
    """
    payload = {"op": op, "a_npy_b64": _encode_array(a)}
    if b is not None:
        payload["b_npy_b64"] = _encode_array(b)
    job_id = _submit(coordinator, account_name, email, api_key, "tensor_op", payload,
                      cpu_limit, ram_limit_mb, timeout_s)
    result = _wait_for_result(coordinator, job_id, max_wait_s=max_wait_s)
    return _decode_array(result["result_npy_b64"])


def run_llm_infer(prompt: str, *, model_name: str, account_name: str | None = None,
                   email: str | None = None, api_key: str | None = None,
                   coordinator="http://127.0.0.1:8000", system: str | None = None,
                   max_tokens=128, temperature=0.7, cpu_limit=1.0, ram_limit_mb=1024,
                   timeout_s=120, max_wait_s=300) -> str:
    """Offload text generation to a provider hosting `model_name` (e.g. "tinyllama-1.1b").

    Only the prompt and generation params travel over the wire -- the model itself
    is a provider-side asset, never sent as part of the job. Either pass api_key=...
    directly, or account_name=... (+ email=... the first time it registers here).
    """
    payload = {"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature}
    if system:
        payload["system"] = system
    job_id = _submit(coordinator, account_name, email, api_key, f"llm_infer:{model_name}", payload,
                      cpu_limit, ram_limit_mb, timeout_s)
    result = _wait_for_result(coordinator, job_id, max_wait_s=max_wait_s)
    return result["text"]


def run_onnx_infer(model_bytes: bytes, input_array, *, account_name: str | None = None,
                    email: str | None = None, api_key: str | None = None,
                    coordinator="http://127.0.0.1:8000", input_name=None,
                    cpu_limit=1.0, ram_limit_mb=1024, timeout_s=60, max_wait_s=300) -> np.ndarray:
    """Offload inference of an ONNX model on one input tensor. Either pass api_key=...
    directly, or account_name=... (+ email=... the first time it registers here)."""
    payload = {
        "model_onnx_b64": base64.b64encode(model_bytes).decode("ascii"),
        "input_npy_b64": _encode_array(input_array),
    }
    if input_name:
        payload["input_name"] = input_name
    job_id = _submit(coordinator, account_name, email, api_key, "onnx_infer", payload,
                      cpu_limit, ram_limit_mb, timeout_s)
    result = _wait_for_result(coordinator, job_id, max_wait_s=max_wait_s)
    return _decode_array(result["output_npy_b64"])
