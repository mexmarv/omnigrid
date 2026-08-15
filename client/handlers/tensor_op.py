"""
tensor_op -- a small, fixed set of safe numeric operations on arrays.

Payload (a JSON object, base64-encoded at the wire level):
{
  "op": "matmul" | "add" | "multiply" | "relu" | "sum" | "mean",
  "a_npy_b64": "<base64 .npy bytes>",
  "b_npy_b64": "<base64 .npy bytes>"   # only required for matmul/add/multiply
}

Result: {"result_npy_b64": "<base64 .npy bytes>"}
"""

import numpy as np

from safe_io import decode_json_payload, decode_npy_b64, encode_json_result, encode_npy_b64

from .base import handler

_OPS = {
    "matmul": lambda a, b: a @ b,
    "add": lambda a, b: a + b,
    "multiply": lambda a, b: a * b,
    "relu": lambda a, _b: np.maximum(a, 0),
    "sum": lambda a, _b: np.array(a.sum()),
    "mean": lambda a, _b: np.array(a.mean()),
}


@handler("tensor_op")
def run(payload_b64: str) -> str:
    payload = decode_json_payload(payload_b64)
    op = payload.get("op")
    if op not in _OPS:
        raise ValueError(f"Unsupported op '{op}'. Allowed: {sorted(_OPS)}")

    a = decode_npy_b64(payload["a_npy_b64"])
    b = decode_npy_b64(payload["b_npy_b64"]) if "b_npy_b64" in payload else None

    result = _OPS[op](a, b)
    return encode_json_result({"result_npy_b64": encode_npy_b64(np.asarray(result))})
