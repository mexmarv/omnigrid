"""
Exposes the Omnigrid network as MCP tools, so any Omnigent-driven agent
(Claude Code, Codex, Cursor, custom agents -- any harness) can reach
community-hosted open models and compute as a tool call, via one line in
its agent YAML. Simplest setup -- already have an API key from
chanza.ai/register.php? Use it directly:

    tools:
      omnigrid:
        type: mcp
        command: python3
        args: ["/path/to/omnigrid/mcp_server/server.py"]
        env:
          OMNIGRID_API_KEY: "your-api-key-from-register.php"
          OMNIGRID_HUB: "https://chanza.ai"

No key yet? Give it a name (and email, the first time that name is used
on this hub) and it registers on first use instead:

        env:
          OMNIGRID_ACCOUNT: "your name"
          OMNIGRID_EMAIL: "you@example.com"
          OMNIGRID_HUB: "https://chanza.ai"

Nothing here changes the underlying security model: the tool still only
ever sends prompts/tensors (data) to the network, never code, and the
network still only ever runs its own fixed handlers. This is a new
front door onto the same house.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "client"))

import requests
from mcp.server.mcpserver import MCPServer

import client_sdk as cc

HUB = os.environ.get("OMNIGRID_HUB", "http://127.0.0.1:8000")
API_KEY = os.environ.get("OMNIGRID_API_KEY")
ACCOUNT = os.environ.get("OMNIGRID_ACCOUNT", "anonymous")
EMAIL = os.environ.get("OMNIGRID_EMAIL")

mcp = MCPServer("omnigrid")


@mcp.tool()
def list_models() -> list[str]:
    """List LLM models currently hosted by online providers on the Omnigrid network."""
    resp = requests.get(f"{HUB}/api/providers_list.php")
    resp.raise_for_status()
    models = set()
    for provider in resp.json():
        for task_type in provider["task_types"].split(","):
            if task_type.startswith("llm_infer:"):
                models.add(task_type.split(":", 1)[1])
    return sorted(models)


@mcp.tool()
def offload_llm_generate(prompt: str, model_name: str, max_tokens: int = 256,
                          temperature: float = 0.7, system: str | None = None) -> str:
    """Generate text using a community-hosted open model instead of your own configured model.

    Use list_models() first to see what's currently available.
    """
    return cc.run_llm_infer(
        prompt, model_name=model_name, account_name=ACCOUNT, email=EMAIL, api_key=API_KEY,
        coordinator=HUB, max_tokens=max_tokens, temperature=temperature, system=system,
    )


@mcp.tool()
def offload_tensor_op(op: str, a: list, b: list | None = None) -> list:
    """Run a numeric tensor operation (matmul/add/multiply/relu/sum/mean) on the network."""
    result = cc.run_tensor_op(op, a, b, account_name=ACCOUNT, email=EMAIL, api_key=API_KEY, coordinator=HUB)
    return result.tolist()


if __name__ == "__main__":
    mcp.run()
