"""
vlm_infer -- forward a prompt (plus an optional image) to a free NVIDIA-hosted
vision-language model, using the *provider's own* NVIDIA API key.

Same pattern as llm_infer: the model itself doesn't travel over the wire.
Here it's not even hosted on the provider's machine -- NVIDIA hosts it, free,
at build.nvidia.com. What the provider hosts is just their own API key,
configured locally via --nvidia-api-key (never sent to chanza.ai, never
visible to whoever's consuming the model). The handler's only job is to
relay the requester's data (prompt + optional image) to NVIDIA's API and
relay the text back -- still data in, data out, never code.

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

import requests

from safe_io import decode_json_payload, encode_json_result

from .base import handler

API_KEY_ENV = "OMNIGRID_NVIDIA_API_KEY"
MODEL_ID_ENV = "OMNIGRID_NVIDIA_MODEL_ID"
API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


@handler("vlm_infer")
def run(payload_b64: str) -> str:
    api_key = os.environ.get(API_KEY_ENV)
    model_id = os.environ.get(MODEL_ID_ENV)
    if not api_key or not model_id:
        raise RuntimeError(f"No NVIDIA API key/model configured on this provider (${API_KEY_ENV}/${MODEL_ID_ENV} unset).")

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

    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return encode_json_result({"text": text})
