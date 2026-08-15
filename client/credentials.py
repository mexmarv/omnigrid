"""
Registers an account with a backoffice once, then caches the API key locally
so later runs reuse the same identity instead of re-registering.

No password, ever. Email is only collected so reset.php on the backoffice
can email you a link to reissue a lost key or delete the account -- it's
not used for anything else. The cached key file is still what authenticates
you day to day; back up ~/.omnigrid/ if you care about keeping your
credits and provider identity between machines.
"""

import json
from pathlib import Path

import requests

CRED_DIR = Path.home() / ".omnigrid"


def _cred_path(coordinator: str, name: str) -> Path:
    safe_host = coordinator.replace("://", "_").replace("/", "_").replace(":", "_")
    return CRED_DIR / f"{safe_host}__{name}.json"


def get_api_key(coordinator: str, name: str, email: str | None = None) -> str:
    path = _cred_path(coordinator, name)
    if path.exists():
        return json.loads(path.read_text())["api_key"]

    if not email:
        raise RuntimeError(
            f"No cached key for '{name}' on {coordinator} yet, so this needs to register -- "
            f"pass an email (used only for account recovery via reset.php, e.g. --email you@example.com)."
        )

    resp = requests.post(f"{coordinator}/api/accounts_register.php", json={"name": name, "email": email})
    if resp.status_code == 409:
        raise RuntimeError(
            f"Account '{name}' is already registered on {coordinator}, but you don't have "
            f"its API key cached locally (no file at {path}). Use {coordinator}/reset.php "
            f"to recover it via email, or pick a different name."
        )
    resp.raise_for_status()
    api_key = resp.json()["api_key"]

    CRED_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"account_name": name, "api_key": api_key}))
    path.chmod(0o600)
    return api_key
