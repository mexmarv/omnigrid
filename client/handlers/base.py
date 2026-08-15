"""
Fixed handler registry.

The security invariant of the whole project lives here: a provider only ever
runs functions from THIS codebase, chosen by a `task_type` string. The
requester never supplies code, only data for one of these pre-installed
functions to consume. Adding a new capability means installing a new
version of the agent with a new handler -- not sending it over the wire.
"""

from typing import Callable

HANDLERS: dict[str, Callable] = {}


def handler(task_type: str):
    def register(fn: Callable):
        HANDLERS[task_type] = fn
        return fn
    return register


def get_handler(task_type: str):
    if task_type in HANDLERS:
        return HANDLERS[task_type]
    # supports "family:variant" task_types (e.g. "llm_infer:tinyllama-1.1b")
    # so one handler can serve several provider-hosted model variants.
    family = task_type.split(":", 1)[0]
    return HANDLERS.get(family)


def installed_task_types() -> list[str]:
    return list(HANDLERS.keys())
