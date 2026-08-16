"""
Shared types for provider-side inference backends (Phase 1) and the
validated generation request schema (Phase 2).

InferenceBackend is deliberately small and non-streaming for now, but
generate() takes a single request object and returns a single response
object precisely so a future generate_stream() (yielding incremental
GenerateResponse chunks) can be added to the Protocol without changing
this signature or any existing caller.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class BackendHealth:
    healthy: bool
    detail: str = ""
    model_loaded: bool = False


@dataclass
class Message:
    role: str
    content: str


@dataclass
class GenerateRequest:
    messages: list[Message]
    max_output_tokens: int
    temperature: float = 0.7
    top_p: float = 1.0
    top_k: int = 40
    stop: list[str] = field(default_factory=list)
    image_b64: str | None = None
    image_mime: str = "image/jpeg"


@dataclass
class GenerateResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    time_to_first_token_s: float | None = None
    generation_time_s: float = 0.0


class InferenceBackend(Protocol):
    async def health(self) -> BackendHealth:
        ...

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        ...

    async def close(self) -> None:
        ...
