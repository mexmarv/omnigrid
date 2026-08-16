"""
Phase 2 payload validation: strict messages schema, legacy-prompt
backward compatibility, and provider-controlled bounds (roles, message
count, content size, temperature/top_p/top_k/stop, context budget).
"""

import pytest

from inference.config import ModelConfig
from inference.schema import ValidationError, normalize_generate_payload

MODEL = ModelConfig(
    public_name="test-model", backend="ollama", max_context_tokens=200,
    max_output_tokens=64, local_model="test:model",
)
VISION_MODEL = ModelConfig(
    public_name="test-vlm", backend="ollama", max_context_tokens=200,
    max_output_tokens=64, local_model="test:vlm", vision=True,
)


def test_new_schema_happy_path():
    req = normalize_generate_payload(
        {"messages": [{"role": "user", "content": "hi"}], "max_output_tokens": 16,
         "temperature": 0.5, "top_p": 0.8, "top_k": 20, "stop": ["</s>"]},
        MODEL, allow_images=False,
    )
    assert req.messages[0].role == "user"
    assert req.messages[0].content == "hi"
    assert req.max_output_tokens == 16
    assert req.temperature == 0.5
    assert req.stop == ["</s>"]


def test_legacy_prompt_payload_is_translated():
    req = normalize_generate_payload(
        {"prompt": "hello there", "system": "be nice", "max_tokens": 10, "temperature": 0.2},
        MODEL, allow_images=False,
    )
    assert [m.role for m in req.messages] == ["system", "user"]
    assert req.messages[0].content == "be nice"
    assert req.messages[1].content == "hello there"
    assert req.max_output_tokens == 10


def test_legacy_prompt_without_system():
    req = normalize_generate_payload({"prompt": "hello"}, MODEL, allow_images=False)
    assert [m.role for m in req.messages] == ["user"]


@pytest.mark.parametrize("payload", [
    {},
    {"prompt": ""},
    {"messages": []},
])
def test_missing_or_empty_input_is_rejected(payload):
    with pytest.raises(ValidationError):
        normalize_generate_payload(payload, MODEL, allow_images=False)


def test_unsupported_top_level_field_is_rejected():
    with pytest.raises(ValidationError, match="Unsupported field"):
        normalize_generate_payload(
            {"prompt": "hi", "model_path": "/etc/passwd"}, MODEL, allow_images=False,
        )


def test_mixing_new_and_legacy_fields_is_rejected():
    with pytest.raises(ValidationError):
        normalize_generate_payload(
            {"messages": [{"role": "user", "content": "hi"}], "prompt": "also this"},
            MODEL, allow_images=False,
        )


def test_disallowed_role_is_rejected():
    with pytest.raises(ValidationError, match="role"):
        normalize_generate_payload(
            {"messages": [{"role": "tool", "content": "hi"}]}, MODEL, allow_images=False,
        )


def test_unsupported_message_field_is_rejected():
    with pytest.raises(ValidationError):
        normalize_generate_payload(
            {"messages": [{"role": "user", "content": "hi", "name": "attacker"}]},
            MODEL, allow_images=False,
        )


def test_too_many_messages_is_rejected():
    messages = [{"role": "user", "content": "hi"} for _ in range(100)]
    with pytest.raises(ValidationError, match="messages"):
        normalize_generate_payload({"messages": messages}, MODEL, allow_images=False)


def test_oversized_message_content_is_rejected():
    with pytest.raises(ValidationError, match="chars"):
        normalize_generate_payload(
            {"messages": [{"role": "user", "content": "x" * 40_000}]}, MODEL, allow_images=False,
        )


def test_max_output_tokens_is_capped_to_model_limit_not_requester_value():
    req = normalize_generate_payload(
        {"messages": [{"role": "user", "content": "hi"}], "max_output_tokens": 999_999},
        MODEL, allow_images=False,
    )
    assert req.max_output_tokens == MODEL.max_output_tokens


def test_temperature_top_p_top_k_are_clamped():
    req = normalize_generate_payload(
        {"messages": [{"role": "user", "content": "hi"}],
         "temperature": 99, "top_p": 5, "top_k": 999_999},
        MODEL, allow_images=False,
    )
    assert req.temperature == 2.0
    assert req.top_p == 1.0
    assert req.top_k == 1000


def test_too_many_stop_sequences_is_rejected():
    with pytest.raises(ValidationError, match="stop"):
        normalize_generate_payload(
            {"messages": [{"role": "user", "content": "hi"}], "stop": ["a"] * 20},
            MODEL, allow_images=False,
        )


def test_context_limit_rejects_oversized_request():
    # MODEL allows 200 tokens total; ~3.5 chars/token estimate means this
    # single message alone blows well past the budget once max_output is added.
    huge_prompt = "word " * 2000
    with pytest.raises(ValidationError, match="max_context_tokens"):
        normalize_generate_payload(
            {"messages": [{"role": "user", "content": huge_prompt}], "max_output_tokens": 64},
            MODEL, allow_images=False,
        )


def test_image_rejected_for_non_vision_model():
    with pytest.raises(ValidationError, match="image"):
        normalize_generate_payload(
            {"prompt": "describe", "image_b64": "ZmFrZQ=="}, MODEL, allow_images=False,
        )


def test_image_accepted_for_vision_model():
    req = normalize_generate_payload(
        {"prompt": "describe", "image_b64": "ZmFrZQ==", "image_mime": "image/png"},
        VISION_MODEL, allow_images=True,
    )
    assert req.image_b64 == "ZmFrZQ=="
    assert req.image_mime == "image/png"


def test_bad_image_mime_is_rejected():
    with pytest.raises(ValidationError, match="image_mime"):
        normalize_generate_payload(
            {"prompt": "describe", "image_b64": "ZmFrZQ==", "image_mime": "text/plain"},
            VISION_MODEL, allow_images=True,
        )
