# compute-commons

An open-source, community-run network for sharing spare CPU/RAM/GPU: anyone
can donate idle capacity from their Mac/Windows/Linux machine, and any
script or AI tool can offload a unit of compute to the network instead of
running it locally. A central **hub** (which you host) does discovery and
matchmaking, like a BitTorrent tracker -- it never runs anything itself.

## The core security decision: no remote code execution, ever

The single most important design choice here: **the network only ever
carries data, never code.**

A provider's machine only runs its own small set of fixed, pre-installed
handler functions (see `agent/handlers/`). A job just picks one by name
(`task_type`) and supplies data for it -- it can never supply code, a shell
command, or a container image for the provider to run. This is *why* there's
no Docker, no VM, no gVisor in this design: there's no untrusted code to
sandbox in the first place, because untrusted code is never accepted.

Concretely:
- Wire payloads are restricted to JSON, `.npy` (numpy, loaded with
  `allow_pickle=False`), and ONNX model bytes. Python `pickle`, `eval`/`exec`,
  and shell commands are never accepted, at the hub's API level.
- `tensor_op` supports a fixed allow-list of six numpy operations
  (matmul/add/multiply/relu/sum/mean) -- nothing dynamic.
- `onnx_infer` runs a supplied ONNX model via ONNX Runtime's default
  CPU execution provider. ONNX is a fixed graph of predefined operators, not
  a scripting language, so loading one doesn't grant arbitrary code execution
  the way unpickling an untrusted object would.
- `llm_infer` runs text generation against a model the *provider* chose to
  host (see below) -- unlike `onnx_infer`, the model itself never travels
  over the wire; only the prompt and generation parameters do.
- Every job still runs in its own OS subprocess (`agent/sandbox.py`) with a
  hard wall-clock timeout and a best-effort memory cap (`RLIMIT_AS` on
  Mac/Linux; best-effort only on Windows, which has no equivalent rlimit --
  see Limitations below), so a malformed or resource-hungry job gets killed
  cleanly instead of hanging or crashing the agent. This is *crash/hang
  containment*, not a security boundary against malicious code -- that
  protection comes entirely from never running requester-supplied code.
- Adding a new capability means shipping a new agent version with a new
  handler, not sending code over the wire.

## Architecture

```
hub/     FastAPI + SQLite. Tracks accounts, online providers (declared
         CPU/RAM/GPU + installed task_types), a job queue, and a reciprocal
         credit ledger (contribute compute -> earn credits; consume -> spend
         them). Never touches job payloads beyond routing them.

agent/   The thing you install. One codebase, two roles:
           - provide: agent.py daemon announces spare capacity, polls the
             hub for jobs it's capable of running, executes them via
             sandbox.py, reports results back.
           - consume: client_sdk.py -- a script or AI tool calls
             run_tensor_op(...) / run_onnx_infer(...) to offload one job.
         handlers/  the fixed, audited functions providers actually run.
         sandbox.py runs a handler in an isolated subprocess with a
                    timeout + memory cap.

mcp_server/  Exposes the network as MCP tools (list_models,
             offload_llm_generate, offload_tensor_op) so any MCP-aware
             agent -- Omnigent, Claude Code, etc. -- can reach it as a
             tool call instead of importing client_sdk.py directly.
```

## Running it

```bash
# one-time setup
cd compute-commons
python3 -m venv .venv && source .venv/bin/activate
pip install -r hub/requirements.txt -r agent/requirements.txt

# start the hub (the thing you host)
cd hub && uvicorn app:app --port 8000

# in another terminal: donate some capacity
cd agent && python3 agent.py --name "your name" --cpu-cores 2 --ram-mb 2048
```

To run the hub on a real public domain instead of localhost, see
[deploy/DEPLOY.md](deploy/DEPLOY.md) (VPS + nginx + Let's Encrypt TLS).

Offload work from a script:

```python
import client_sdk as cc
import numpy as np

result = cc.run_tensor_op("matmul", a, b, account_name="your name")
```

## Hosting an LLM (`llm_infer`)

LLM weights are hundreds of MB to tens of GB, so unlike `onnx_infer` the
model is never part of the job payload -- it'd be wasteful to re-upload and
reload it on every request. Instead, a provider pre-downloads one GGUF model
and hosts it under a name of its choosing:

```bash
cd agent
python3 agent.py --name "your name" --cpu-cores 2 --ram-mb 2048 \
    --llm-model-path /path/to/model.gguf --llm-model-name tinyllama-1.1b
```

This advertises the task_type `llm_infer:tinyllama-1.1b` to the hub.
Consumers ask for that specific model by name:

```python
import client_sdk as cc

text = cc.run_llm_infer("Explain BitTorrent in one sentence.",
                         model_name="tinyllama-1.1b", account_name="your name")
```

Still no code crosses the wire -- only the prompt and generation
parameters (`max_tokens`, `temperature`, optional `system`) do. Requires
`llama-cpp-python`; if it's not installed, the agent just doesn't advertise
`llm_infer` and everything else keeps working.

**Known perf caveat:** each job runs in a fresh sandboxed subprocess (see
Architecture), so the model is reloaded from disk on *every* request. Fine
for small models and testing; a real deployment would want a persistent,
warm worker process per hosted model instead of a fresh load each time --
not built yet.

## Using it from Omnigent (or any MCP-aware agent)

[Omnigent](https://github.com/omnigent-ai/omnigent) is Databricks' open-source
meta-harness -- it lets one agent definition run across Claude Code, Codex,
Cursor, and others, with tools attached via the Model Context Protocol (MCP).
`mcp_server/` exposes this network as MCP tools, so any Omnigent agent (on
any harness) can reach community-hosted models with three lines in its YAML:

```yaml
tools:
  compute_commons:
    type: mcp
    command: python3
    args: ["/path/to/compute-commons/mcp_server/server.py"]
    env:
      COMPUTE_COMMONS_ACCOUNT: "your name"
      COMPUTE_COMMONS_HUB: "http://your-hub:8000"
```

That exposes three tools to the agent: `list_models` (what's currently
hosted), `offload_llm_generate` (route a generation to a community model),
and `offload_tensor_op`. Tested against a real MCP client (not just direct
function calls) -- tool discovery, `list_models` reflecting live hub state,
and both offload tools all round-trip correctly.

**Important, and worth repeating:** this is *not* a way to share access to
someone's paid Claude/Codex/etc. account. Omnigent's own session-sharing
feature deliberately keeps execution and credentials on the session owner's
machine, and this integration follows the same rule -- it only ever reaches
*self-hosted, open-weight* models a provider chose to donate (the same
`llm_infer` handler from earlier), never a proprietary assistant or its
credentials. Nothing about the underlying security model changes here: this
is a new front door (MCP) onto the same house (data-only jobs, fixed
handlers, no remote code execution).

## Accounts and credits

The first time `agent.py` or `client_sdk.py` sees a given `account_name`
against a given hub, it calls `POST /accounts/register`, gets back an API
key, and caches it at `~/.compute-commons/`. Every request after that
authenticates with `Authorization: Bearer <api_key>`. **There's no
password, no email, no recovery flow -- the cached key file IS the
account.** Losing it means losing that account's credits and provider
identity for good; back up `~/.compute-commons/` if you care about either.

New accounts start with 50 free credits (so you can try consuming before
you've contributed anything -- otherwise nobody would ever go first).
Completing a job earns the provider `compute_seconds * (cpu_limit +
ram_limit_gb)` credits, debited from the consumer. Purely a fairness
ledger -- no real money, no blockchain, nothing that touches payment.

The hub enforces ownership everywhere it matters: you can't announce
capacity under someone else's `provider_id`, steal another provider's
queued job, or report a fake result for a job that isn't assigned to one
of your own providers. All verified against real negative tests (wrong/
missing keys, provider-id hijacking, forged results, duplicate names) --
see the test history, not just the claim.

## Honest limitations -- read before pointing this at strangers' machines

- **GPU support is CPU-provider-only right now.** `onnx_infer` only requests
  `CPUExecutionProvider`. Wiring up `CUDAExecutionProvider` for NVIDIA
  providers is straightforward to add but not done yet -- don't advertise
  GPU capacity expecting GPU-accelerated jobs today.
- **Memory caps are soft on Windows.** `RLIMIT_AS` doesn't exist there;
  `sandbox.py` currently has no memory-enforcement fallback for Windows
  providers (only the wall-clock timeout is fully cross-platform). Add a
  `psutil`-based watcher thread that kills over-budget processes before
  running this on Windows providers with untrusted consumers.
- **Job results are still readable by anyone who knows the job_id.**
  `GET /jobs/{id}` has no auth -- submitting a job doesn't currently keep its
  payload/result private from someone else guessing or enumerating IDs. Fine
  for non-sensitive data (the tensor_op/LLM examples here); add auth on this
  route too before sending anything sensitive through the network.
- **No transport encryption yet.** Payloads travel as plain HTTP. Put a
  reverse proxy with TLS (nginx + Let's Encrypt, see `deploy/`) in front of
  the hub before running this over the open internet -- otherwise API keys
  and payloads are readable to anyone on the network path.
- **No rate limiting.** A single account can currently hammer
  `/jobs/submit` or `/accounts/register` as fast as it wants; add rate
  limits before this is reachable from the open internet.
- **No redundancy/consensus on results.** Unlike SETI@home's quorum model,
  a job runs on exactly one provider and its answer is taken on faith.
  Fine for tasks where the consumer can sanity-check the result itself;
  risky if you need to trust a stranger's provider blindly.
- **This has not had a security review.** The "never run remote code"
  principle is sound in design, but the implementation (input validation,
  the resource-limit fallbacks, the hub's trust boundary) hasn't been
  audited. Treat this as a working prototype proving the architecture, not
  something to hand out to the public internet as-is.
