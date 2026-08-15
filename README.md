<p align="center">
  <img src="docs/logo.png" alt="Omnigrid" width="110">
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://github.com/omnigent-ai/omnigent"><img src="docs/omnigent-logo.svg" alt="Omnigent" width="170"></a>
</p>

<h1 align="center">Omnigrid</h1>
<p align="center"><b>Community compute for AI agents -- built to plug straight into <a href="https://github.com/omnigent-ai/omnigent">Omnigent</a>.</b></p>

### Spare compute, shared like a signal -- not sold like a service.

In 1999, SETI@home let millions of ordinary computers donate their idle
CPU cycles to a single shared goal: sift through radio-telescope noise
for a signal that might mean we're not alone. It worked because giving
away spare compute cost nothing and the ledger of who'd contributed was
public and fair.

Omnigrid borrows that exact idea and points it somewhere new. The thing
worth searching for now isn't a signal from space -- it's more capacity
for the AI agents already running on our own machines. Donate a laptop's
idle CPU/RAM/GPU, or an open model you're already hosting, and it goes to
work for someone else's agent. Need more than your own machine has? Reach
into the same pool. No cloud bill, no plan tiers, no signup form --
installing the client *is* the account.

**Live network, dashboard, and credit leaderboard: [chanza.ai](https://chanza.ai)**

> ### Connect Omnigent in one block, nothing to install
> Get a key at [chanza.ai/register.php](https://chanza.ai/register.php), add this to your agent's YAML, done:
> ```yaml
> tools:
>   omnigrid:
>     type: mcp
>     url: "https://chanza.ai/mcp.php"
>     headers:
>       Authorization: "Bearer your-api-key"
> ```
> No Python, no download, no local process -- Omnigent talks straight to the
> hosted endpoint. Full walkthrough, example prompt, and the local-process
> alternative: [Use the network](#use-the-network).

---

## The one rule everything else follows

**Nothing here ever runs code that someone else sends you.** A machine
sharing its compute only ever runs its own small set of fixed, pre-installed
functions (matrix ops, ONNX model inference, LLM text generation) on
*data* that arrives over the wire -- never a script, a shell command, or a
container image supplied by whoever's asking. That single rule is what
makes it safe to let a stranger's request run on your laptop at all, and
it's why there's no Docker, no VM, no sandboxing arms race anywhere in
this project: there's no untrusted code to contain in the first place.

```mermaid
flowchart LR
    subgraph Share["Share compute"]
        P1["Idle laptop\n(CPU/RAM)"]
        P2["GPU machine\n+ hosted model"]
    end

    subgraph HQ["Backoffice -- chanza.ai"]
        B[("Directory +\nmatchmaking +\ncredit ledger")]
    end

    subgraph Use["Use compute"]
        C1["Your Python script"]
        C2["Omnigent agent\n(via MCP)"]
    end

    P1 -- "announce capacity" --> B
    P2 -- "announce capacity" --> B
    C1 -- "submit job (data only)" --> B
    C2 -- "submit job (data only)" --> B
    B -- "assign job" --> P1
    B -- "assign job" --> P2
    P1 -- "result" --> B
    P2 -- "result" --> B
    B -- "result" --> C1
    B -- "result" --> C2
```

## Share your compute

Install the client, tell it how much you're willing to give away, and
leave it running. It only picks up work while your machine looks idle.

```bash
git clone https://github.com/mexmarv/omnigrid.git
cd omnigrid/client
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 agent.py --name "your name" --email "you@example.com" --cpu-cores 2 --ram-mb 2048 \
    --coordinator https://chanza.ai
```

Already have an API key from [chanza.ai/register.php](https://chanza.ai/register.php)?
Skip `--name`/`--email` and pass `--api-key` directly instead.

**Got a GPU?** It's used automatically. On Apple Silicon the client
detects Metal and offloads LLM layers to it; on NVIDIA it does the same
via CUDA; `onnx_infer` tries CoreML/CUDA first and only falls back to CPU
if neither is available. Verified for real on Apple Silicon -- llama.cpp's
own device-init log confirms all layers land on the GPU, not just assumed.

Have an open-weight GGUF model sitting around (Llama, Mistral, Qwen,
whatever)? Host it for text generation, GPU offload included:

```bash
python3 agent.py --name "your name" --email "you@example.com" --cpu-cores 2 --ram-mb 2048 \
    --coordinator https://chanza.ai \
    --llm-model-path /path/to/model.gguf --llm-model-name my-model
```

The first run registers you an account (50 free credits to start) and
caches an API key at `~/.omnigrid/` -- no password, ever. Your email is
only used by [reset.php](https://chanza.ai/reset.php) if you ever need to
reissue a lost key or delete the account; back up `~/.omnigrid/` if you'd
rather not rely on that. Every job you complete earns credits from
whoever consumed it; nobody has to trust anybody, the ledger just tracks
who's given what.

<details>
<summary>What actually happens when a job runs (sequence diagram)</summary>

```mermaid
sequenceDiagram
    participant Consumer
    participant Backoffice as Backoffice (chanza.ai)
    participant Provider

    Provider->>Backoffice: announce capacity + installed handlers
    Consumer->>Backoffice: submit job (task_type + data payload)
    Backoffice-->>Consumer: job_id (queued)
    Provider->>Backoffice: poll for next job
    Backoffice-->>Provider: matching job (data payload)
    Provider->>Provider: run fixed handler in sandboxed subprocess
    Provider->>Backoffice: report result
    Backoffice->>Backoffice: credit provider, debit consumer
    Consumer->>Backoffice: poll job status
    Backoffice-->>Consumer: result
```
</details>

## Use the network

**From your own Python script or notebook:**

```python
import client_sdk as cc
import numpy as np

result = cc.run_tensor_op("matmul", a, b, account_name="your name", email="you@example.com",
                           coordinator="https://chanza.ai")

text = cc.run_llm_infer("Explain BitTorrent in one sentence.",
                         model_name="some-hosted-model", account_name="your name",
                         email="you@example.com", coordinator="https://chanza.ai")

# Already have a key from register.php? Skip account_name/email and pass api_key= instead.
```

**From [Omnigent](https://github.com/omnigent-ai/omnigent)** (Databricks'
open-source meta-harness -- one agent definition, any harness: Claude Code,
Codex, Cursor, and more), point your agent at the network as an MCP tool --
**hosted, so there's nothing to install.** This is the whole point of the
integration, so here's the complete path, not just a snippet.

```mermaid
flowchart LR
    A["Your Omnigent agent\n(Claude Code / Codex / Cursor / custom)"]
    M["chanza.ai/mcp.php\n(hosted, no install)"]
    B[("Omnigrid backoffice")]
    N["Community providers"]

    A -- "tools: omnigrid\n(url + API key)" --> M
    M -- "offload_llm_generate /\noffload_tensor_op" --> B
    B --> N
```

**1. Get an account and API key.** Visit `https://chanza.ai/register.php`
(or `http://127.0.0.1:8000/register.php` if you're running your own
backoffice locally), pick a name, and you'll get an API key shown once --
save it. The same page also hands you the exact YAML block below with your
name and key already filled in, so you don't have to copy-paste-and-edit.

**2. Check what's actually available to use.** The dashboard at
`chanza.ai` (or your own backoffice's `/`) lists every model currently
being hosted for free under "Being shared for free, right now" -- that's
what you can ask for by name in step 4. In this repo's own local testing,
for instance, that list has included a small instruction-tuned model
(`smollm2-135m`, ~135M parameters, someone's spare CPU/GPU keeping it warm).

**3. Add the tool to your agent's YAML** -- point `url:` at the hosted
endpoint, no download, no local process, no Python required on your side
at all. Omnigent agents are defined in a YAML file with a `prompt`, an
`executor` (which harness/model runs it), and a `tools` section --
adapting the shape from
[Omnigent's own Agent YAML spec](https://github.com/omnigent-ai/omnigent/blob/main/docs/AGENT_YAML_SPEC.md):

```yaml
name: my_agent
prompt: |
  You are a helpful assistant with access to the Omnigrid community
  compute network via the omnigrid tool.
executor:
  harness: claude-sdk   # or codex, cursor, etc. -- whatever you're already using
  model: your-model-here
tools:
  omnigrid:
    type: mcp
    url: "https://chanza.ai/mcp.php"     # or your own backoffice's URL
    headers:
      Authorization: "Bearer your-api-key-from-step-1"
```

`backoffice/mcp.php` implements MCP's Streamable HTTP transport directly in
PHP -- verified against the real `mcp` Python client library, not just
"looks like the spec." Same three tools, same security model (data only,
never code); the only thing that moved is where the server runs.

<details>
<summary>Prefer a local process instead of the hosted endpoint?</summary>

If you'd rather run your own MCP process (e.g. a fully private setup, or
you just don't want a network hop), `mcp_server/server.py` does the same
three tools over stdio -- requires Python + this repo checked out locally:

```yaml
tools:
  omnigrid:
    type: mcp
    command: python3
    args: ["/path/to/omnigrid/mcp_server/server.py"]
    env:
      OMNIGRID_ACCOUNT: "your name"
      OMNIGRID_HUB: "https://chanza.ai"
```
</details>

(`executor:` varies by which harness/model you're actually running --
adjust it to match your existing Omnigent setup; the `tools:` block is the
part that's specific to this project.)

**4. Run it and ask for the shared resource by name.**

```bash
omnigent run my_agent.yaml
```

Then, in the chat, just ask for it in plain language -- for example:

> List the models available on Omnigrid, then use whichever one is hosted
> to write a two-sentence summary of why octopuses are considered
> intelligent.

The agent calls `list_models` to see `smollm2-135m` is available, then
`offload_llm_generate` to actually run the prompt on the community-hosted
GPU/CPU behind it -- text comes back into your conversation like any other
tool result, except the compute for it happened on someone else's machine.

This is *not* a way to share access to your paid Claude/Codex/etc. account
or its credentials -- Omnigent's own session-sharing deliberately keeps
those on your machine, and this integration follows the same rule. It only
ever reaches self-hosted, open-weight models someone chose to donate.

## Run it yourself, right now

```bash
git clone https://github.com/mexmarv/omnigrid.git
cd omnigrid/backoffice
cp config.example.php config.php   # SQLite by default, nothing to edit
php -S 127.0.0.1:8000
```

That's a complete backoffice running locally -- open `http://127.0.0.1:8000`
for the dashboard. Full walkthrough (including wiring up a client against
it) in [backoffice/HOSTING.md](backoffice/HOSTING.md).

## Want to run your own network instead of chanza.ai?

The whole backoffice (directory + matchmaking + credit ledger) is plain
PHP, defaulting to SQLite -- one file, nothing to provision, upload it to
any shared host. See [backoffice/HOSTING.md](backoffice/HOSTING.md).

## Honest limitations -- read before relying on this for anything serious

- **Job results are readable by anyone who knows the job_id.** There's no
  auth on reading a job's payload/result yet. Fine for non-sensitive data;
  don't send anything private through the network until this is fixed.
- **No rate limiting.** An account can currently submit as fast as it wants.
- **Reset emails use PHP's built-in `mail()`.** It works out of the box on
  most shared hosting, but deliverability to Gmail/Outlook etc. without
  proper SPF/DKIM records can be spotty. If reset links aren't arriving,
  that's the first thing to check -- not a bug in the reset logic itself.
- **No transport encryption is enforced by the code itself** -- put this
  behind HTTPS (Hostinger's free AutoSSL, or any reverse proxy) before
  running it for real. chanza.ai already does.
- **The LLM handler reloads the model from disk on every job** (each job
  runs in a fresh sandboxed subprocess). Fine for small models; a
  persistent warm worker per model would be the real fix.
- **The hosted MCP endpoint (`mcp.php`) caps how long it'll wait for a
  result at 20 seconds.** It blocks synchronously inside one HTTP request
  while polling for a provider to finish, and shared hosting typically
  kills PHP scripts around 30s regardless -- found by actually testing a
  longer wait and watching it get killed mid-request, not assumed. A slow
  provider or a big model can outrun that; you'll get a clear "still
  processing" message with the job_id rather than a silent hang, but the
  result itself won't come back through that same call.
- **GPU support is verified on Apple Silicon; the CUDA path is untested**
  on real NVIDIA hardware here (it uses the same llama-cpp-python/onnxruntime
  mechanism, and falls back safely if unavailable, but hasn't been run on
  an NVIDIA box). If you test it, contributions/reports welcome.
- **No redundancy/consensus on results.** A job runs on exactly one
  provider and its answer is taken on faith -- fine when you can sanity-check
  the result yourself, risky if you need to trust a stranger blindly.
- **This has not had an independent security review.** The "never run
  remote code" principle is sound by design, but the implementation
  hasn't been audited. Treat this as a working, tested prototype -- not
  a hardened public service, yet.

## How it's actually built

Providers run a small, fixed set of audited handlers (`client/handlers/`):
`tensor_op` (six safe numpy operations), `onnx_infer` (a supplied ONNX
model, data-only, CoreML/CUDA-accelerated when available), `llm_infer`
(text generation against a model the *provider* chose to host, GPU-offloaded
when available -- the model itself never crosses the wire, only prompts
and generation params do). Every job still runs in its own OS subprocess
with a wall-clock timeout and memory cap, purely to contain crashes -- not
as a security boundary, since there's nothing untrusted to contain.
Accounts authenticate with an API key, never a password -- email is
collected only so `reset.php` can send a one-time link to reissue a lost
key or delete the account. The backoffice enforces that you can only
announce as, or report results for, providers you actually own.

Two ways to reach it as an MCP tool, both exposing the same three tools:
`mcp_server/server.py` (Python, stdio, run locally) and `backoffice/mcp.php`
(hosted, HTTP) -- the latter hand-implements the JSON-RPC subset of MCP's
Streamable HTTP transport needed for a stateless tools-only server (no
session state, no SSE), including a from-scratch but numpy-byte-verified
encoder/decoder for the `.npy` tensor format so `offload_tensor_op`'s
payloads are readable by the same Python `tensor_op` handler every other
path uses.
