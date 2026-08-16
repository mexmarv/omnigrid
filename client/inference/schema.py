"""
Phase 2 request validation: turns an untrusted job payload dict (decoded
from a job's payload_b64) into a bounded, provider-controlled
GenerateRequest. This is the boundary that keeps requesters to "data and
bounded generation parameters" -- never a path to provider-controlled
values like model paths, endpoints, or backend configuration.

Current (documented) schema:
{
  "messages": [{"role": "system"|"user"|"assistant", "content": "..."}],
  "max_output_tokens": 512,
  "temperature": 0.7,
  "top_p": 0.8,
  "top_k": 20,
  "stop": []
}

Deprecated legacy schema (still accepted, translated internally -- do not
build new callers against this):
{"prompt": "...", "system": "optional", "max_tokens": 128, "temperature": 0.7}

Every numeric bound here is provider-controlled, taken from the matching
ModelConfig (client/inference/config.py): a job can ask for less than the
limit, never more.
"""

from .config import ModelConfig
from .types import GenerateRequest, Message

ALLOWED_ROLES = {"system", "user", "assistant"}
MAX_MESSAGES = 64
MAX_CONTENT_CHARS = 32_000
MAX_TOTAL_CHARS = 200_000
MAX_STOP_SEQUENCES = 8
MAX_STOP_LEN = 64
MAX_IMAGE_B64_CHARS = 12_000_000  # ~9MB decoded -- generous for one image

# Deliberately conservative chars-per-token estimate used only to reject
# grossly oversized requests before spending any compute -- not a
# tokenizer replacement, and never trusted as an exact count.
CHARS_PER_TOKEN_ESTIMATE = 3.5

NEW_SCHEMA_FIELDS = {"messages", "max_output_tokens", "temperature", "top_p", "top_k", "stop"}
LEGACY_SCHEMA_FIELDS = {"prompt", "system", "max_tokens", "temperature"}
ALLOWED_FIELDS = NEW_SCHEMA_FIELDS | LEGACY_SCHEMA_FIELDS | {"image_b64", "image_mime"}


class ValidationError(Exception):
    pass


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def estimate_input_tokens(messages: list[Message]) -> int:
    total_chars = sum(len(m.content) for m in messages)
    return max(1, int(total_chars / CHARS_PER_TOKEN_ESTIMATE))


def _validate_messages(raw_messages) -> list[Message]:
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ValidationError("'messages' must be a non-empty array.")
    if len(raw_messages) > MAX_MESSAGES:
        raise ValidationError(f"'messages' has {len(raw_messages)} entries; the limit is {MAX_MESSAGES}.")

    messages = []
    for i, entry in enumerate(raw_messages):
        if not isinstance(entry, dict):
            raise ValidationError(f"messages[{i}] must be an object.")
        role = entry.get("role")
        if role not in ALLOWED_ROLES:
            raise ValidationError(f"messages[{i}].role must be one of {sorted(ALLOWED_ROLES)}, got {role!r}.")
        content = entry.get("content")
        if not isinstance(content, str) or not content:
            raise ValidationError(f"messages[{i}].content must be a non-empty string.")
        if len(content) > MAX_CONTENT_CHARS:
            raise ValidationError(
                f"messages[{i}].content is {len(content)} chars; the limit is {MAX_CONTENT_CHARS}."
            )
        extra = set(entry) - {"role", "content"}
        if extra:
            raise ValidationError(f"messages[{i}] has unsupported field(s): {sorted(extra)}.")
        messages.append(Message(role=role, content=content))

    total_chars = sum(len(m.content) for m in messages)
    if total_chars > MAX_TOTAL_CHARS:
        raise ValidationError(f"messages total {total_chars} chars; the limit is {MAX_TOTAL_CHARS}.")
    return messages


def _validate_stop(stop) -> list[str]:
    if stop is None:
        return []
    if not isinstance(stop, list) or len(stop) > MAX_STOP_SEQUENCES:
        raise ValidationError(f"'stop' must be an array of at most {MAX_STOP_SEQUENCES} strings.")
    for s in stop:
        if not isinstance(s, str) or not s or len(s) > MAX_STOP_LEN:
            raise ValidationError(f"each 'stop' entry must be a 1-{MAX_STOP_LEN} character string.")
    return stop


def normalize_generate_payload(payload: dict, model_cfg: ModelConfig, *, allow_images: bool) -> GenerateRequest:
    """Validates an untrusted job payload against model_cfg's provider-set
    limits and returns a bounded GenerateRequest. Raises ValidationError on
    anything out of bounds or unrecognized -- callers should fail the job
    with that message, never silently coerce it into something acceptable.
    """
    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object.")

    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        raise ValidationError(f"Unsupported field(s): {sorted(unknown)}.")

    if "messages" in payload:
        if "prompt" in payload or "system" in payload:
            raise ValidationError("Use either 'messages', or the deprecated 'prompt'/'system' pair -- not both.")
        messages = _validate_messages(payload["messages"])
    else:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValidationError("payload must include 'messages', or (deprecated) a non-empty 'prompt'.")
        if len(prompt) > MAX_CONTENT_CHARS:
            raise ValidationError(f"'prompt' is {len(prompt)} chars; the limit is {MAX_CONTENT_CHARS}.")
        messages = []
        system = payload.get("system")
        if system is not None:
            if not isinstance(system, str) or len(system) > MAX_CONTENT_CHARS:
                raise ValidationError(f"'system' must be a string of at most {MAX_CONTENT_CHARS} chars.")
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))

    max_output = payload.get("max_output_tokens", payload.get("max_tokens", model_cfg.max_output_tokens))
    if not isinstance(max_output, int) or isinstance(max_output, bool) or max_output <= 0:
        raise ValidationError("'max_output_tokens' (or legacy 'max_tokens') must be a positive integer.")
    max_output = min(max_output, model_cfg.max_output_tokens)

    temperature = _clamp(float(payload.get("temperature", 0.7)), 0.0, 2.0)
    top_p = _clamp(float(payload.get("top_p", 1.0)), 0.0, 1.0)
    top_k = int(_clamp(float(payload.get("top_k", 40)), 0, 1000))
    stop = _validate_stop(payload.get("stop"))

    image_b64 = payload.get("image_b64")
    image_mime = payload.get("image_mime", "image/jpeg")
    if image_b64 is not None:
        if not allow_images:
            raise ValidationError("This model does not accept image input.")
        if not isinstance(image_b64, str) or not image_b64:
            raise ValidationError("'image_b64' must be a non-empty base64 string.")
        if len(image_b64) > MAX_IMAGE_B64_CHARS:
            raise ValidationError("'image_b64' is too large.")
        if not isinstance(image_mime, str) or not image_mime.startswith("image/"):
            raise ValidationError("'image_mime' must look like 'image/...'.")

    estimated_input = estimate_input_tokens(messages)
    budget = model_cfg.max_context_tokens - max_output
    if estimated_input > budget:
        raise ValidationError(
            f"Estimated input (~{estimated_input} tokens) plus max_output_tokens ({max_output}) "
            f"exceeds this model's max_context_tokens ({model_cfg.max_context_tokens})."
        )

    return GenerateRequest(
        messages=messages, max_output_tokens=max_output, temperature=temperature,
        top_p=top_p, top_k=top_k, stop=stop, image_b64=image_b64, image_mime=image_mime,
    )
