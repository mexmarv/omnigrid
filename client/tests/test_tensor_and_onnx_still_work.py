"""
Regression check (test requirement #15): tensor_op and onnx_infer are
untouched by the Phase 1/2 refactor -- they still run through
handlers/base.py's registry and sandbox.py's subprocess exactly as
before. llm_infer/vlm_infer were removed from that registry (they're
routed to the persistent InferenceManager instead, see
test_agent_generation.py), so this also guards against that change
accidentally breaking the handlers package import or the other two.
"""

import base64
import json

import numpy as np
import onnx
from onnx import TensorProto, helper

import handlers
import sandbox
from safe_io import decode_json_payload, decode_npy_b64, encode_npy_b64


def test_llm_and_vlm_are_no_longer_sandboxed_handlers():
    assert handlers.get_handler("llm_infer") is None
    assert handlers.get_handler("vlm_infer") is None
    assert set(handlers.installed_task_types()) == {"tensor_op", "onnx_infer"}


def test_tensor_op_matmul_via_handler_registry():
    fn = handlers.get_handler("tensor_op")
    a = np.array([[1.0, 2.0], [3.0, 4.0]])
    b = np.array([[5.0, 6.0], [7.0, 8.0]])
    payload = {"op": "matmul", "a_npy_b64": encode_npy_b64(a), "b_npy_b64": encode_npy_b64(b)}
    payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()

    result_b64 = fn(payload_b64)
    result = decode_json_payload(result_b64)
    output = decode_npy_b64(result["result_npy_b64"])
    np.testing.assert_allclose(output, a @ b)


def test_tensor_op_end_to_end_through_sandbox_subprocess():
    a = np.array([1.0, 2.0, 3.0])
    payload = {"op": "sum", "a_npy_b64": encode_npy_b64(a)}
    payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()

    status, result_b64, error, compute_seconds = sandbox.run("tensor_op", payload_b64, ram_limit_mb=512, timeout_s=10)

    assert status == "done", error
    result = decode_json_payload(result_b64)
    output = decode_npy_b64(result["result_npy_b64"])
    assert float(output) == 6.0


def _make_identity_onnx_model_bytes() -> bytes:
    x = helper.make_tensor_value_info("X", TensorProto.DOUBLE, [3])
    y = helper.make_tensor_value_info("Y", TensorProto.DOUBLE, [3])
    node = helper.make_node("Identity", ["X"], ["Y"])
    graph = helper.make_graph([node], "identity-graph", [x], [y])
    model = helper.make_model(graph, producer_name="omnigrid-tests")
    model.opset_import[0].version = 13
    onnx.checker.check_model(model)
    return model.SerializeToString()


def test_onnx_infer_via_handler_registry():
    fn = handlers.get_handler("onnx_infer")
    model_bytes = _make_identity_onnx_model_bytes()
    input_array = np.array([1.0, 2.0, 3.0])
    payload = {
        "model_onnx_b64": base64.b64encode(model_bytes).decode(),
        "input_npy_b64": encode_npy_b64(input_array),
    }
    payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()

    result_b64 = fn(payload_b64)
    result = decode_json_payload(result_b64)
    output = decode_npy_b64(result["output_npy_b64"])
    np.testing.assert_allclose(output, input_array)
