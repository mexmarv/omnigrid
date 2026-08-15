"""
Exposes the compute-commons network as MCP tools, so any Omnigent-driven
agent (Claude Code, Codex, Cursor, custom agents -- any harness) can reach
community-hosted open models and compute as a tool call, via one line in
its agent YAML:

    tools:
      compute_commons:
        type: mcp
        command: python3
        args: ["/path/to/compute-commons/mcp_server/server.py"]
        env:
          COMPUTE_COMMONS_ACCOUNT: "your name"
          COMPUTE_COMMONS_HUB: "http://your-hub:8000"

Nothing here changes the underlying security model: the tool still only
ever sends prompts/tensors (data) to the network, never code, and the
network still only ever runs its own fixed handlers. This is a new
front door onto the same house.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

import requests
from mcp.server.mcpserver import MCPServer

import client_sdk as cc

HUB = os.environ.get("COMPUTE_COMMONS_HUB", "http://127.0.0.1:8000")
ACCOUNT = os.environ.get("COMPUTE_COMMONS_ACCOUNT", "anonymous")

mcp = MCPServer("compute-commons")


@mcp.tool()
def list_models() -> list[str]:
    """List LLM models currently hosted by online providers on the compute-commons network."""
    resp = requests.get(f"{HUB}/providers")
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
        prompt, model_name=model_name, account_name=ACCOUNT, coordinator=HUB,
        max_tokens=max_tokens, temperature=temperature, system=system,
    )


@mcp.tool()
def offload_tensor_op(op: str, a: list, b: list | None = None) -> list:
    """Run a numeric tensor operation (matmul/add/multiply/relu/sum/mean) on the network."""
    result = cc.run_tensor_op(op, a, b, account_name=ACCOUNT, coordinator=HUB)
    return result.tolist()


if __name__ == "__main__":
    mcp.run()
