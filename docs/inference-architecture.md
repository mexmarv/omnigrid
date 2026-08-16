# Persistent inference architecture

This document covers what actually changed in this pass (Phase 1 --
persistent inference backends, and Phase 2 -- separating LLM/VLM
execution from the sandboxed job runner), the security boundaries that
were preserved throughout, and a concrete, honest roadmap for the phases
that were **not** implemented yet (Phases 3-7). Nothing described as
"deferred" below is wired up or partially enabled -- it's a plan, not a
half-shipped feature.

## What changed

Before this pass, `llm_infer`/`vlm_infer` jobs ran exactly like
`tensor_op`/`onnx_infer`: `client/handlers/llm_infer.py` and
`vlm_infer.py` instantiated `llama_cpp.Llama(model_path=...)` fresh
inside `client/sandbox.py`'s per-job subprocess, loaded the whole model
from disk, ran one generation, and threw it away. Fine for a 135M-param
model, ruinous for anything larger -- an 8B model reloading every job
turns a sub-second generation into a multi-second-to-minutes one.

Now there are two separate execution paths, chosen by `agent.py` per job:

```
tensor_op / onnx_infer  ->  client/sandbox.py (unchanged)
                             fixed op, spawned subprocess, wall-clock + memory limit

llm_infer:<model> /
vlm_infer:<model>       ->  client/inference/manager.py
                             persistent InferenceBackend, built once at
                             agent startup, reused for every job for the
                             life of the process
```

`client/handlers/llm_infer.py` and `vlm_infer.py` are gone -- their
sandboxed-per-job approach is precisely the problem this removes, not
unrelated code left to rot next to the fix.

### The backend abstraction (Phase 1)

`client/inference/types.py` defines the shape every backend implements:

```python
class InferenceBackend(Protocol):
    async def health(self) -> BackendHealth: ...
    async def generate(self, request: GenerateRequest) -> GenerateResponse: ...
    async def close(self) -> None: ...
```

Two implementations today:

- **`OllamaBackend`** (`client/inference/ollama_backend.py`) -- talks to a
  provider-controlled local Ollama server (default
  `http://127.0.0.1:11434`) over a reused `requests.Session`. Every
  `generate()` call sends `keep_alive` so Ollama keeps the model resident
  in memory between jobs. Connect, generate, and total-request timeouts
  are all enforced independently.
- **`LlamaCppBackend`** (`client/inference/llamacpp_backend.py`) --
  supervises a persistent `llama-server` process (llama.cpp's own
  long-lived HTTP worker) per configured GGUF model. The model loads once
  at process start; every job after that reuses the same warm process and
  HTTP connection. GPU offload (`--n-gpu-layers`) is set once at launch --
  Metal on Apple Silicon, CUDA on Nvidia, or `0` for CPU-only, exactly the
  same mechanism the old per-job `Llama(n_gpu_layers=...)` call used, just
  paid for once instead of per request. Vision models (`mmproj_path` set)
  are served the same way, with image content attached as an OpenAI-style
  `image_url` content part on the final user message.

Both are deliberately **non-streaming for now, by design**: `generate()`
takes one `GenerateRequest` and returns one `GenerateResponse` so a future
`generate_stream()` can be added to the Protocol without redesigning
either backend or any existing caller.

`client/inference/manager.py`'s `InferenceManager` owns one instance of
each configured backend for the life of the agent process, runs a startup
health check per model (`start()`), and gates job dispatch through an
`asyncio.Semaphore` sized by that model's `max_concurrency`. A model that
fails its startup health check is kept registered but excluded from
`available_models()` -- and therefore from what the provider announces as
capacity -- until it recovers.

### Provider configuration

`client/inference/config.py`'s `ModelConfig` is the one place backend
choice/endpoint/model live -- always set by the **provider operator**,
via `--models-config models.yaml` (or `OMNIGRID_MODELS_CONFIG`), never by
a requester's job payload:

```yaml
models:
  - public_name: qwen3-8b-m4
    backend: ollama
    endpoint: http://127.0.0.1:11434
    local_model: qwen3:8b
    max_context_tokens: 16384
    max_output_tokens: 4096
    max_concurrency: 1
```

See [client/models.example.yaml](../client/models.example.yaml) for the
full set of examples referenced below. Config is validated once,
synchronously, at startup (`load_model_configs`/`merge_configs`) --
an unknown field, an invalid backend name, or `max_output_tokens` bigger
than `max_context_tokens` exits immediately with a clear message rather
than starting in a half-valid state.

The pre-existing single-model CLI flags (`--llm-model-path`,
`--llm-model-name`, `--gpu-layers`, `--vlm-model-path`,
`--vlm-mmproj-path`, `--vlm-model-name`) still work unchanged -- they're
translated into the same `ModelConfig` shape
(`config.legacy_llamacpp_config`) and can be combined with
`--models-config` in one agent.

#### Apple Silicon (Ollama, recommended on macOS)

```yaml
models:
  - public_name: qwen3-8b-m4
    backend: ollama
    endpoint: http://127.0.0.1:11434
    local_model: qwen3:8b
    max_context_tokens: 16384
    max_output_tokens: 4096
    max_concurrency: 1
```

#### Nvidia Linux (persistent llama.cpp, CUDA build)

```yaml
models:
  - public_name: qwen3-8b-cuda
    backend: llamacpp
    model_path: /srv/models/Qwen3-8B-Q4_K_M.gguf
    n_gpu_layers: -1
    max_context_tokens: 16384
    max_output_tokens: 4096
    max_concurrency: 1
```

Requires the `llama-server` binary on `PATH` (llama.cpp built with
`GGML_CUDA=ON`, or `brew install llama.cpp` on macOS).

#### CPU-only fallback (any platform)

```yaml
models:
  - public_name: smollm2-135m-cpu
    backend: llamacpp
    model_path: /path/to/SmolLM2-135M-Instruct-Q4_K_M.gguf
    n_gpu_layers: 0
    max_context_tokens: 2048
    max_output_tokens: 1024
    max_concurrency: 1
```

#### API keys never on the command line

If an Ollama endpoint or `llama-server` instance needs a bearer token
(e.g. a shared/remote deployment), set `api_key_env` to the name of an
environment variable and export it before starting the agent -- it's
never written into `models.yaml` or passed as a CLI argument:

```bash
export OMNIGRID_OLLAMA_API_KEY="..."
python3 agent.py --api-key "$OMNIGRID_API_KEY" --cpu-cores 2 --ram-mb 2048 \
    --models-config models.yaml
```

```yaml
models:
  - public_name: qwen3-8b-remote
    backend: ollama
    endpoint: https://ollama.internal.example:443
    local_model: qwen3:8b
    api_key_env: OMNIGRID_OLLAMA_API_KEY
    max_context_tokens: 16384
    max_output_tokens: 4096
```

### Request validation (Phase 2)

`client/inference/schema.py`'s `normalize_generate_payload()` is the
boundary between an untrusted job payload and the model. Current schema:

```json
{
  "messages": [{"role": "system|user|assistant", "content": "..."}],
  "max_output_tokens": 512,
  "temperature": 0.7,
  "top_p": 0.8,
  "top_k": 20,
  "stop": []
}
```

The pre-existing `{"prompt": "...", "system": "...", "max_tokens": ...}`
shape is still accepted (it's what `client_sdk.py`/`mcp.php` send today)
and translated internally -- new integrations should target `messages`
directly; the flat-prompt shape is deprecated, not removed.

Enforced, all provider-controlled (a job can ask for less, never more):
allowed roles only; a maximum message count and per-message/total content
size; `max_output_tokens` clamped to the model's configured
`max_output_tokens`; `temperature`/`top_p`/`top_k` clamped to sane ranges;
`stop` bounded in count and length; any field outside the documented
schema rejected outright; a conservative chars-per-token estimate of the
input, rejected up front if it plus `max_output_tokens` would exceed the
model's `max_context_tokens` (no tokenizer round-trip needed just to
reject an oversized request). `agent.py`'s job loop also caps generation
wall-clock time at `MAX_GENERATION_TIMEOUT_S`, regardless of what
`timeout_s` a job requests.

## Security boundaries (unchanged, restated)

- Requesters submit **data and bounded generation parameters only** --
  `messages`/`prompt`, size/token/temperature bounds. Nothing in the
  schema lets a job specify a model path, backend endpoint, API key, or
  any executable configuration.
- Providers execute **fixed, provider-installed operations only**. Which
  backend/model answers a given `public_name` is decided once, by the
  provider operator, in `models.yaml`/CLI flags -- never by a job payload.
- No requester-supplied script, command, container, or arbitrary code is
  ever executed. `tensor_op` is six fixed numpy operations; `onnx_infer`
  loads a supplied *graph* of predefined operators (not a scripting
  language) with `allow_pickle=False` array decoding; `llm_infer`/
  `vlm_infer` only ever reach a provider-chosen model through the
  validated schema above.
- Error messages from both backends are written to never include
  secrets: no API key, Authorization header value, full prompt, or
  private result is ever formatted into a raised exception or
  `BackendHealth.detail` (see `client/tests/test_secret_redaction.py`).

## Deferred: Phases 3-7 (roadmap, not implemented)

These phases require schema/scheduler changes to the shared PHP
coordinator (`backoffice/`), which is currently working correctly. Rather
than land them partially against a live, working backend, they're left
untouched this pass and documented here as a concrete plan.

### Phase 3 -- structured provider capabilities

Replace the current comma-separated `providers.task_types` column with
proper tables:

```
providers              (id, account_id, cpu_cores, ram_mb, gpu_model, ..., last_heartbeat)
provider_models        (id, provider_id, public_name, backend, model_family, quantization,
                         model_hash, max_context_tokens, max_output_tokens, vision, tools,
                         json_mode, max_concurrency, available_concurrency, recent_tps,
                         last_health_check, last_heartbeat, verification_level)
provider_capabilities  (provider_id, capability)  -- e.g. gpu_cuda, gpu_metal
```

Migration path: add the new tables alongside the existing `providers`
table via an additive migration (no column drops), backfill
`provider_models` from the current `task_types` CSV for already-registered
providers, and have `providers_announce.php` write to both forms until
every client-side consumer (`agent.py`, `mcp.php`, `mcp_server/server.py`)
reads from the new tables. Only once nothing reads `task_types` would it
be dropped, in its own migration.

### Phase 4 -- lease-based job lifecycle

```
queued -> offered -> assigned/running -> completed
                              |-> failed
                              |-> expired -> queued for retry
                              |-> cancelled
```

New `jobs` columns: `lease_owner`, `lease_token`, `lease_expires_at`,
`attempt`, `max_attempts`, `started_at`, `completed_at`, `failure_code`,
`idempotency_key`. `providers_next_job.php`'s existing
`UPDATE ... WHERE status='queued'` claim pattern is the right foundation
(it's already transactional and race-safe under SQLite/MySQL via PDO,
per `33acda4`'s recent fix in the same spirit) -- extend it to also set
`lease_token`/`lease_expires_at`, and require the matching `lease_token`
on `jobs_result.php`/`jobs_failure.php` so a provider can only complete a
job it actually holds the lease for. A scheduled sweep (or a check at
claim time) requeues jobs whose lease expired without completion, up to
`max_attempts`, and skips retry entirely for validation/auth/permanent
model errors (`failure_code` distinguishes these from transient ones).

SQLite caveat to document plainly: its single-writer model means high
write concurrency across many simultaneous provider claims will
serialize, not parallelize -- fine for the current scale, and the fix
when it isn't is the MySQL/PostgreSQL DSN path already supported by
`backoffice/config.php`, not a rewrite.

### Phase 5 -- scheduler improvements

Move today's "fetch all queued jobs, filter in PHP" matching
(`providers_next_job.php`) into indexed queries: an index on
`jobs(status, task_type, created_at)` and `provider_models(public_name,
last_heartbeat)` so matching is a query-planner decision, not an
application-level scan. Rank eligible jobs/providers with a documented,
unit-tested score (queue age, estimated time-to-first-token, provider
queue depth, recent tokens/sec, recent failure rate, available slots) --
deliberately simple and deterministic, not a learned model.

### Phase 6 -- metering and model identity

Stop treating provider-reported `compute_seconds` as ground truth for
credit accounting; record it as untrusted telemetry alongside
coordinator-observed wall time, input/output token counts,
time-to-first-token, and generation duration (the agent-side
`GenerateResponse` already carries token counts and elapsed time -- Phase
6 is wiring those into the coordinator's ledger, not producing them, which
this pass already does). Introduce a provider model manifest
(`family`, `parameters`, `quantization`, `sha256`, `source`, `backend`,
`runtime_version`, `chat_template_hash`) with honest verification labels
(`self_reported`, `hash_verified`, `challenge_verified`,
`operator_verified`) -- no claim of cryptographic attestation beyond what
each label actually means.

### Phase 7 -- observability and hardening

Structured logs/metrics for queue depth, assignment latency,
time-to-first-token, tokens/sec, retry/lease-expiration counts, and
backend health (this pass's `logging.getLogger("omnigrid.inference")`
calls are a starting point, not the full story); scoped credentials,
API-key rotation/revocation, per-account/per-IP rate limits, request/
output size limits, and SSRF protection on the coordinator's HTTP
surface.

## Troubleshooting

- **"'llama-server' was not found on PATH"** -- install llama.cpp's
  server binary (`brew install llama.cpp` on macOS, or build from source)
  and make sure it's on `PATH`, or set a `server_binary` with the full
  path in `models.yaml`.
- **A model reports unhealthy at startup but the agent still runs** --
  by design: other configured models and `tensor_op`/`onnx_infer` keep
  working. Check the printed `model '<name>': UNHEALTHY -- <detail>` line
  for the reason (Ollama unreachable, model not pulled, `llama-server`
  exited during startup, etc.) and re-run once it's fixed -- there's no
  need to restart the whole provider for an unrelated model.
- **Ollama backend reports the endpoint reachable but the model
  missing** -- run `ollama pull <local_model>` for the exact tag in
  `models.yaml`; the health check requires the model to already be
  pulled, it won't pull it for you.
- **A generation job fails with "exceeded the ...s total timeout"** --
  either the model/hardware is too slow for the configured timeout, or
  the backend hung; check `connect_timeout_s`/`generate_timeout_s`/
  `total_timeout_s` (currently backend constructor defaults, not yet
  exposed as separate `models.yaml` fields -- open an issue if you need
  them tunable per model sooner than that lands).
- **A job fails with a schema validation message** -- that's Phase 2
  working as intended: the message names exactly which bound was
  violated (role, message count, content size, context budget, etc.).
