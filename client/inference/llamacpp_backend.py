"""
LlamaCppBackend -- supervises one persistent `llama-server` process per
configured GGUF model, instead of instantiating and reloading
`Llama(model_path=...)` on every job (the old client/handlers/llm_infer.py
/ vlm_infer.py behavior this replaces).

llama-server is llama.cpp's own long-lived HTTP worker: it loads the model
once at startup and serves an OpenAI-compatible /v1/chat/completions
endpoint from then on, so GPU offload (Metal on Apple Silicon, CUDA on
Nvidia, or -1/0 either way for CPU-only) is configured once via
--n-gpu-layers at process start, exactly like the old n_gpu_layers
argument to Llama() -- just paid for once instead of per request.

A provider-configured GGUF vision model (mmproj set) is served the same
way: llama-server accepts image content parts in the standard
OpenAI-style message format, so LlamaCppBackend and OllamaBackend expose
the identical GenerateRequest/GenerateResponse shape regardless of which
one actually answers a job.
"""

import asyncio
import os
import shutil
import socket
import subprocess
import time

import requests

from .errors import BackendError, BackendTimeoutError, BackendUnavailableError
from .types import BackendHealth, GenerateRequest, GenerateResponse

DEFAULT_SERVER_BINARY = "llama-server"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaCppBackend:
    def __init__(
        self,
        model_path: str,
        *,
        mmproj_path: str | None = None,
        host: str = "127.0.0.1",
        port: int | None = None,
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,
        server_binary: str = DEFAULT_SERVER_BINARY,
        connect_timeout_s: float = 5.0,
        generate_timeout_s: float = 180.0,
        total_timeout_s: float = 185.0,
        startup_timeout_s: float = 120.0,
        api_key_env: str | None = None,
        extra_args: list[str] | None = None,
    ):
        self._model_path = model_path
        self._mmproj_path = mmproj_path
        self._host = host
        self._port = port  # a free port is picked lazily on first start if None
        self._n_ctx = n_ctx
        self._n_gpu_layers = n_gpu_layers
        self._server_binary = server_binary
        self._connect_timeout_s = connect_timeout_s
        self._generate_timeout_s = generate_timeout_s
        self._total_timeout_s = total_timeout_s
        self._startup_timeout_s = startup_timeout_s
        self._extra_args = extra_args or []
        self._api_key = os.environ.get(api_key_env) if api_key_env else None

        self._session = requests.Session()
        if self._api_key:
            self._session.headers["Authorization"] = f"Bearer {self._api_key}"

        self._proc: subprocess.Popen | None = None
        self._start_lock = asyncio.Lock()

    @property
    def _base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def _binary_available(self) -> bool:
        return shutil.which(self._server_binary) is not None or os.path.isfile(self._server_binary)

    async def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return  # already running and healthy-at-last-check

        async with self._start_lock:
            if self._proc is not None and self._proc.poll() is None:
                return  # someone else won the race while we waited for the lock

            if not self._binary_available():
                raise BackendUnavailableError(
                    f"'{self._server_binary}' was not found on PATH. Install llama.cpp's "
                    "llama-server (e.g. `brew install llama.cpp`, or build from source) or "
                    "set the backend's server_binary to its full path."
                )

            if self._port is None:
                self._port = await asyncio.to_thread(_pick_free_port)

            args = [
                self._server_binary,
                "--model", self._model_path,
                "--host", self._host,
                "--port", str(self._port),
                "--ctx-size", str(self._n_ctx),
                "--n-gpu-layers", str(self._n_gpu_layers),
            ]
            if self._mmproj_path:
                args += ["--mmproj", self._mmproj_path]
            if self._api_key:
                args += ["--api-key", self._api_key]
            args += self._extra_args

            try:
                self._proc = await asyncio.to_thread(
                    subprocess.Popen, args,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
            except OSError as exc:
                raise BackendUnavailableError(f"Failed to launch {self._server_binary}: {exc}") from exc

            await self._wait_until_healthy_or_dead()

    async def _wait_until_healthy_or_dead(self) -> None:
        deadline = time.monotonic() + self._startup_timeout_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise BackendUnavailableError(
                    f"{self._server_binary} exited during startup (code {self._proc.returncode}). "
                    f"{self._read_tail()}"
                )
            try:
                resp = await asyncio.to_thread(
                    self._session.get, f"{self._base_url}/health", timeout=self._connect_timeout_s,
                )
                if resp.status_code == 200:
                    return
            except requests.RequestException:
                pass
            await asyncio.sleep(0.3)

        self._kill()
        raise BackendUnavailableError(
            f"{self._server_binary} did not become healthy within {self._startup_timeout_s}s."
        )

    def _read_tail(self, max_lines: int = 20) -> str:
        if not self._proc or not self._proc.stdout:
            return ""
        try:
            lines = self._proc.stdout.readlines()[-max_lines:]
        except Exception:
            return ""
        return "Last output: " + " | ".join(line.strip() for line in lines if line.strip())

    def _kill(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass

    async def health(self) -> BackendHealth:
        try:
            await self._ensure_started()
        except BackendUnavailableError as exc:
            return BackendHealth(healthy=False, detail=str(exc))
        try:
            resp = await asyncio.to_thread(
                self._session.get, f"{self._base_url}/health", timeout=self._connect_timeout_s,
            )
            if resp.status_code == 200:
                return BackendHealth(healthy=True, model_loaded=True, detail="ok")
            return BackendHealth(healthy=False, detail=f"llama-server returned HTTP {resp.status_code}.")
        except requests.RequestException as exc:
            return BackendHealth(healthy=False, detail=f"llama-server health check failed ({type(exc).__name__}).")

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        await self._ensure_started()

        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        if request.image_b64 and messages:
            last = messages[-1]
            last["content"] = [
                {"type": "text", "text": last["content"]},
                {"type": "image_url",
                 "image_url": {"url": f"data:{request.image_mime};base64,{request.image_b64}"}},
            ]

        payload = {
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "top_k": request.top_k,
        }
        if request.stop:
            payload["stop"] = request.stop

        def _post():
            return self._session.post(
                f"{self._base_url}/v1/chat/completions", json=payload,
                timeout=(self._connect_timeout_s, self._generate_timeout_s),
            )

        start = time.monotonic()
        try:
            resp = await asyncio.wait_for(asyncio.to_thread(_post), timeout=self._total_timeout_s)
        except asyncio.TimeoutError as exc:
            raise BackendTimeoutError(
                f"llama-server generation exceeded the {self._total_timeout_s}s total timeout."
            ) from exc
        except requests.ConnectionError as exc:
            self._proc = None  # next call will detect the crash and attempt a fresh start
            raise BackendUnavailableError("Lost connection to llama-server; it may have crashed.") from exc
        except requests.Timeout as exc:
            raise BackendTimeoutError("llama-server request timed out.") from exc
        elapsed = time.monotonic() - start

        if resp.status_code != 200:
            raise BackendError(f"llama-server returned HTTP {resp.status_code}.")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = choice.get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        return GenerateResponse(
            text=text,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            generation_time_s=elapsed,
        )

    async def close(self) -> None:
        self._session.close()
        await asyncio.to_thread(self._kill)
        self._proc = None
