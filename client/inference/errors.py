"""
Error types for the inference backend layer.

Messages on these must never include secrets -- API keys, Authorization
header values, full prompts, or private results. Callers should only ever
see a short, actionable description (endpoint reachability, timeout,
process exit code, HTTP status), never raw request/response bodies.
"""


class BackendError(Exception):
    """Base class for all inference backend failures."""


class BackendUnavailableError(BackendError):
    """The backend process/endpoint could not be reached or started."""


class BackendTimeoutError(BackendError):
    """A connection, generation, or total-request timeout was exceeded."""
