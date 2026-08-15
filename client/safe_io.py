"""
The only functions allowed to turn wire bytes into in-memory objects.

Deliberately narrow: JSON for structure, numpy .npy for array data (loaded
with allow_pickle=False, which makes it just a typed data blob -- unlike
Python's `pickle`, it cannot deserialize into arbitrary object construction
or code execution). Nothing here ever calls `eval`, `exec`, or `pickle.load`.
"""

import base64
import io
import json

import numpy as np


def decode_npy_b64(b64_str: str) -> np.ndarray:
    raw = base64.b64decode(b64_str)
    return np.load(io.BytesIO(raw), allow_pickle=False)


def encode_npy_b64(arr: np.ndarray) -> str:
    buf = io.BytesIO()
    np.save(buf, arr, allow_pickle=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def decode_json_payload(payload_b64: str) -> dict:
    raw = base64.b64decode(payload_b64)
    return json.loads(raw.decode("utf-8"))


def encode_json_result(obj: dict) -> str:
    raw = json.dumps(obj).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")
