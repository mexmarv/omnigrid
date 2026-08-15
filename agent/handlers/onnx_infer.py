"""
onnx_infer -- run a given ONNX model on a given input tensor.

ONNX is a fixed graph-of-predefined-operators format, not a scripting
language: loading one doesn't grant arbitrary code execution the way
unpickling an untrusted object graph would. We still only use the default
CPU/CUDA execution providers (no custom-op models), and cap wall-clock time
the same as every other handler via the sandbox layer.

Payload (a JSON object, base64-encoded at the wire level):
{
  "model_onnx_b64": "<base64 .onnx model bytes>",
  "input_npy_b64": "<base64 .npy input array>",
  "input_name": "optional input tensor name (auto-detected if omitted)"
}

Result: {"output_npy_b64": "<base64 .npy bytes>"}
"""

import base64

import onnxruntime as ort

from safe_io import decode_json_payload, decode_npy_b64, encode_json_result, encode_npy_b64

from .base import handler


@handler("onnx_infer")
def run(payload_b64: str) -> str:
    payload = decode_json_payload(payload_b64)
    model_bytes = base64.b64decode(payload["model_onnx_b64"])
    input_array = decode_npy_b64(payload["input_npy_b64"])

    session = ort.InferenceSession(model_bytes, providers=["CPUExecutionProvider"])
    input_name = payload.get("input_name") or session.get_inputs()[0].name
    outputs = session.run(None, {input_name: input_array})

    return encode_json_result({"output_npy_b64": encode_npy_b64(outputs[0])})
