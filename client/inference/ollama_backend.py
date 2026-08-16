"""
OllamaBackend -- persistent client for a provider-controlled local Ollama
server (default http://127.0.0.1:11434).

The endpoint and model name are fixed at construction time from the
provider's OWN configuration (models.yaml / CLI / env), never from a
requester's job payload -- a requester can only ever influence
GenerateRequest fields (messages, max_output_tokens, temperature, ...),
never which endpoint or local model actually serves them. That match is
made once, by the provider operator, in ModelConfig.

One instance is created per configured model and kept alive for the life
of the agent process: the requests.Session below reuses its HTTP
connection pool across every job, and Ollama itself is asked to keep the
model resident in memory via `keep_alive` -- eliminating the per-job
reload this project's llama.cpp path used to suffer from.

Non-streaming today by design, not by accident: generate() takes one
GenerateRequest and returns one GenerateResponse so a future
generate_stream() (yielding incremental chunks from Ollama's `stream:
true` mode) can be added alongside it without touching this signature or
any existing caller.

`think: false` is always sent: reasoning models (e.g. qwen3) otherwise
return their chain-of-thought in a separate `message.thinking` field and
leave `message.content` -- what this backend reads -- empty until
max_output_tokens covers the reasoning too, which silently starves small
generation budgets. Ollama ignores `think` for models that don't support
it, so this is safe as a universal default.
"""

import asyncio
import os
import time

import requests

from .errors import BackendError, BackendTimeoutError, BackendUnavailableError
from .types import BackendHealth, GenerateRequest, GenerateResponse

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"


class OllamaBackend:
    def __init__(
        self,
        model: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        connect_timeout_s: float = 5.0,
        generate_timeout_s: float = 120.0,
        total_timeout_s: float = 125.0,
        keep_alive: str = "30m",
        api_key_env: str | None = None,
    ):
        self._model = model
        self._endpoint = endpoint.rstrip("/")
        self._connect_timeout_s = connect_timeout_s
        self._generate_timeout_s = generate_timeout_s
        self._total_timeout_s = total_timeout_s
        self._keep_alive = keep_alive
        self._session = requests.Session()
        if api_key_env:
            api_key = os.environ.get(api_key_env)
            if api_key:
                self._session.headers["Authorization"] = f"Bearer {api_key}"

    async def health(self) -> BackendHealth:
        def _check() -> bool:
            resp = self._session.get(f"{self._endpoint}/api/tags", timeout=self._connect_timeout_s)
            resp.raise_for_status()
            entries = resp.json().get("models", [])
            names = {e.get("name") for e in entries} | {e.get("model") for e in entries}
            return self._model in names

        try:
            model_present = await asyncio.wait_for(
                asyncio.to_thread(_check), timeout=self._connect_timeout_s + 1.0
            )
        except asyncio.TimeoutError:
            return BackendHealth(healthy=False, detail=f"Timed out reaching Ollama at {self._endpoint}.")
        except requests.ConnectionError:
            return BackendHealth(
                healthy=False, detail=f"Could not connect to Ollama at {self._endpoint}. Is it running?"
            )
        except requests.RequestException as exc:
            return BackendHealth(healthy=False, detail=f"Ollama health check failed ({type(exc).__name__}).")

        if not model_present:
            return BackendHealth(
                healthy=False,
                detail=f"Ollama at {self._endpoint} is reachable but model '{self._model}' isn't pulled.",
            )
        return BackendHealth(healthy=True, model_loaded=True, detail="ok")

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        options = {
            "temperature": request.temperature,
            "top_p": request.top_p,
            "top_k": request.top_k,
            "num_predict": request.max_output_tokens,
        }
        if request.stop:
            options["stop"] = request.stop
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "think": False,
            "keep_alive": self._keep_alive,
            "options": options,
        }

        def _post():
            return self._session.post(
                f"{self._endpoint}/api/chat",
                json=payload,
                timeout=(self._connect_timeout_s, self._generate_timeout_s),
            )

        start = time.monotonic()
        try:
            resp = await asyncio.wait_for(asyncio.to_thread(_post), timeout=self._total_timeout_s)
        except asyncio.TimeoutError as exc:
            raise BackendTimeoutError(f"Ollama generation exceeded the {self._total_timeout_s}s total timeout.") from exc
        except requests.ConnectionError as exc:
            raise BackendUnavailableError(f"Could not reach Ollama at {self._endpoint}.") from exc
        except requests.Timeout as exc:
            raise BackendTimeoutError("Ollama request timed out.") from exc
        elapsed = time.monotonic() - start

        if resp.status_code != 200:
            raise BackendError(f"Ollama returned HTTP {resp.status_code}.")

        data = resp.json()
        text = data.get("message", {}).get("content", "")
        return GenerateResponse(
            text=text,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            generation_time_s=elapsed,
        )

    async def close(self) -> None:
        self._session.close()
