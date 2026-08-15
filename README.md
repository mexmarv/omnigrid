# Omnigrid

Spare CPU, RAM, and GPU cycles, shared across a community instead of sold
by a cloud. Point an idle laptop at the network and it starts doing real
work for other people; point your own AI agent at the network and it can
reach compute and open models beyond what your own machine has.

The live network's dashboard and credit leaderboard: **[chanza.ai](https://chanza.ai)**

No signup form, no plan tiers -- installing the client *is* the account.

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

## Share your compute

Install the client, tell it how much you're willing to give away, and
leave it running. It only picks up work while your machine looks idle.

```bash
git clone https://github.com/mexmarv/omnigrid.git
cd omnigrid/client
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 agent.py --name "your name" --cpu-cores 2 --ram-mb 2048 \
    --coordinator https://chanza.ai
```

Got a GPU and an open-weight GGUF model sitting around (Llama, Mistral,
Qwen, whatever)? Host it for text generation too:

```bash
python3 agent.py --name "your name" --cpu-cores 2 --ram-mb 2048 \
    --coordinator https://chanza.ai \
    --llm-model-path /path/to/model.gguf --llm-model-name my-model
```

The first run registers you an account (50 free credits to start) and
caches an API key at `~/.omnigrid/` -- there's no password or recovery,
so back that folder up if you care about keeping the identity. Every
job you complete earns credits from whoever consumed it; nobody has to
trust anybody, the ledger just tracks who's given what.

## Use the network

**From your own Python script or notebook:**

```python
import client_sdk as cc
import numpy as np

result = cc.run_tensor_op("matmul", a, b, account_name="your name",
                           coordinator="https://chanza.ai")

text = cc.run_llm_infer("Explain BitTorrent in one sentence.",
                         model_name="some-hosted-model", account_name="your name",
                         coordinator="https://chanza.ai")
```

**From [Omnigent](https://github.com/omnigent-ai/omnigent)** (Databricks'
open-source meta-harness -- one agent definition, any harness: Claude Code,
Codex, Cursor, and more) -- add three lines to your agent's YAML and the
network becomes a tool call:

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

That gives the agent three tools: `list_models` (what's currently hosted),
`offload_llm_generate`, and `offload_tensor_op`. This is *not* a way to
share access to your paid Claude/Codex/etc. account or its credentials --
Omnigent's own session-sharing deliberately keeps those on your machine,
and this integration follows the same rule. It only ever reaches
self-hosted, open-weight models someone chose to donate.

## Want to run your own network instead of chanza.ai?

The whole backoffice (the directory + matchmaking + credit ledger) is
plain PHP + MySQL -- upload it to any shared host, no VPS required. See
[backoffice/HOSTING.md](backoffice/HOSTING.md).

## Honest limitations -- read before relying on this for anything serious

- **GPU inference is CPU-only right now.** `onnx_infer` only requests
  `CPUExecutionProvider`. Cross-vendor GPU execution providers (CUDA,
  DirectML, CoreML) are a natural next step, not done yet.
- **Job results are readable by anyone who knows the job_id.** There's no
  auth on reading a job's payload/result yet. Fine for non-sensitive data;
  don't send anything private through the network until this is fixed.
- **No rate limiting.** An account can currently submit as fast as it wants.
- **No transport encryption is enforced by the code itself** -- put this
  behind HTTPS (Hostinger's free AutoSSL, or any reverse proxy) before
  running it for real. chanza.ai already does.
- **The LLM handler reloads the model from disk on every job** (each job
  runs in a fresh sandboxed subprocess). Fine for small models; a
  persistent warm worker per model would be the real fix.
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
model, data-only), `llm_infer` (text generation against a model the
*provider* chose to host -- the model itself never crosses the wire, only
prompts and generation params do). Every job still runs in its own OS
subprocess with a wall-clock timeout and memory cap, purely to contain
crashes -- not as a security boundary, since there's nothing untrusted to
contain. Accounts authenticate with an API key (no password, no email);
the backoffice enforces that you can only announce as, or report results
for, providers you actually own.
