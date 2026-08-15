"""
Registers an account with a backoffice once, then caches the API key locally
so later runs reuse the same identity instead of re-registering.

There's no password, no email, no recovery -- the cached key file IS the
account. Back up ~/.omnigrid/ if you care about keeping your credits and
provider identity.
"""

import json
from pathlib import Path

import requests

CRED_DIR = Path.home() / ".omnigrid"


def _cred_path(coordinator: str, name: str) -> Path:
    safe_host = coordinator.replace("://", "_").replace("/", "_").replace(":", "_")
    return CRED_DIR / f"{safe_host}__{name}.json"


def get_api_key(coordinator: str, name: str) -> str:
    path = _cred_path(coordinator, name)
    if path.exists():
        return json.loads(path.read_text())["api_key"]

    resp = requests.post(f"{coordinator}/api/accounts_register.php", json={"name": name})
    if resp.status_code == 409:
        raise RuntimeError(
            f"Account '{name}' is already registered on {coordinator}, but you don't have "
            f"its API key cached locally (no file at {path}). There's no recovery for a lost "
            f"key -- pick a different name, or restore your ~/.omnigrid/ backup."
        )
    resp.raise_for_status()
    api_key = resp.json()["api_key"]

    CRED_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"account_name": name, "api_key": api_key}))
    path.chmod(0o600)
    return api_key
