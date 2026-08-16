"""
vlm_infer -- run a provider-hosted GGUF vision-language model locally, via
llama-cpp-python.

Same pattern as llm_infer: the model itself doesn't travel over the wire.
Each provider pre-downloads and hosts one specific GGUF model + its vision
projector (mmproj) file, advertised as task_type "vlm_infer:<name>" (see
agent.py's --vlm-model-path/--vlm-mmproj-path/--vlm-model-name flags).

Payload (a JSON object, base64-encoded at the wire level):
{
  "prompt": "...",
  "image_b64": "optional base64-encoded image bytes",
  "image_mime": "image/jpeg",   # optional, defaults to image/jpeg
  "max_tokens": 512
}

Result: {"text": "<model's response>"}
"""

import os

from llama_cpp import Llama
from llama_cpp.llama_chat_format import MTMDChatHandler

from safe_io import decode_json_payload, encode_json_result

from .base import handler

MODEL_PATH_ENV = "OMNIGRID_VLM_MODEL_PATH"
MMPROJ_PATH_ENV = "OMNIGRID_VLM_MMPROJ_PATH"


@handler("vlm_infer")
def run(payload_b64: str) -> str:
    model_path = os.environ.get(MODEL_PATH_ENV)
    mmproj_path = os.environ.get(MMPROJ_PATH_ENV)
    if not model_path or not mmproj_path:
        raise RuntimeError(
            f"No local VLM configured on this provider (${MODEL_PATH_ENV}/${MMPROJ_PATH_ENV} unset)."
        )

    payload = decode_json_payload(payload_b64)
    prompt = payload["prompt"]
    image_b64 = payload.get("image_b64")
    image_mime = payload.get("image_mime", "image/jpeg")
    max_tokens = int(payload.get("max_tokens", 512))

    if image_b64:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_b64}"}},
        ]
    else:
        content = prompt

    chat_handler = MTMDChatHandler(clip_model_path=mmproj_path, verbose=False)
    llm = Llama(model_path=model_path, chat_handler=chat_handler, n_ctx=2048, n_gpu_layers=-1, verbose=False)
    completion = llm.create_chat_completion(
        messages=[{"role": "user", "content": content}], max_tokens=max_tokens,
    )
    text = completion["choices"][0]["message"]["content"]
    return encode_json_result({"text": text})
