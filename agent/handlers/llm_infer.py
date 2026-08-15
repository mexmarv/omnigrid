"""
llm_infer -- run a provider-hosted GGUF language model for text generation.

Unlike onnx_infer, the model itself is NOT part of the wire payload: LLM
weights are hundreds of MB to tens of GB, so shipping them per-request over
JSON/base64 would be wasteful and slow. Instead each provider pre-downloads
and hosts one specific model, advertised as a task_type of the form
"llm_infer:<model-name>" (see base.py's family:variant lookup and agent.py's
--llm-model-path/--llm-model-name flags). Only the prompt and generation
parameters travel over the wire -- still data, never code.

Payload (a JSON object, base64-encoded at the wire level):
{
  "prompt": "...",
  "system": "optional system prompt",
  "max_tokens": 128,
  "temperature": 0.7
}

Result: {"text": "<generated text>"}

Known limitation (see README): the model is reloaded from disk on every job
because each job runs in a fresh sandboxed subprocess. Fine for a prototype;
a warm, persistent worker would be needed for real throughput.
"""

import os

from llama_cpp import Llama

from safe_io import decode_json_payload, encode_json_result

from .base import handler

MODEL_PATH_ENV = "COMPUTE_COMMONS_LLM_MODEL_PATH"


@handler("llm_infer")
def run(payload_b64: str) -> str:
    model_path = os.environ.get(MODEL_PATH_ENV)
    if not model_path:
        raise RuntimeError(f"No LLM model configured on this provider (${MODEL_PATH_ENV} unset).")

    payload = decode_json_payload(payload_b64)
    prompt = payload["prompt"]
    system = payload.get("system")
    max_tokens = int(payload.get("max_tokens", 128))
    temperature = float(payload.get("temperature", 0.7))

    llm = Llama(model_path=model_path, n_ctx=2048, verbose=False)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    completion = llm.create_chat_completion(
        messages=messages, max_tokens=max_tokens, temperature=temperature,
    )
    text = completion["choices"][0]["message"]["content"]
    return encode_json_result({"text": text})
