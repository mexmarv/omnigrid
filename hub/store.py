import hashlib
import secrets
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "hub.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    api_key_hash TEXT NOT NULL UNIQUE,
    credits REAL NOT NULL DEFAULT 50.0,  -- small free grant so newcomers can consume before contributing
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    cpu_cores REAL NOT NULL,
    ram_mb INTEGER NOT NULL,
    gpu_model TEXT,
    gpu_vram_mb INTEGER,
    task_types TEXT NOT NULL,   -- comma-separated list of handlers this agent has installed
    last_heartbeat REAL NOT NULL,
    busy INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumer_account_id INTEGER NOT NULL,
    provider_id INTEGER,
    task_type TEXT NOT NULL,
    payload_format TEXT NOT NULL,   -- 'json' | 'npy' | 'onnx'
    payload_b64 TEXT NOT NULL,
    cpu_limit REAL NOT NULL,
    ram_limit_mb INTEGER NOT NULL,
    gpu_required INTEGER NOT NULL DEFAULT 0,
    timeout_s INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | assigned | done | failed
    error TEXT,
    result_format TEXT,
    result_b64 TEXT,
    compute_seconds REAL,
    created_at REAL NOT NULL,
    finished_at REAL
);
"""

HEARTBEAT_TIMEOUT_S = 60
STARTING_CREDITS = 50.0
CREDIT_RATE_PER_RESOURCE_SECOND = 1.0  # credits per (cpu_cores + ram_gb) of compute-second


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class AccountNameTaken(Exception):
    pass


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def create_account(conn, name: str) -> tuple[int, str]:
    """Registers a brand-new account and returns (account_id, plaintext_api_key).

    The plaintext key is only ever available at this one moment -- only its
    hash is stored. Losing it means losing access to that account; there's
    no recovery mechanism (no email, no password reset) in this design.
    """
    api_key = secrets.token_urlsafe(32)
    try:
        cur = conn.execute(
            "INSERT INTO accounts (name, api_key_hash, credits, created_at) VALUES (?, ?, ?, ?)",
            (name, _hash_key(api_key), STARTING_CREDITS, time.time()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise AccountNameTaken(f"Account name '{name}' is already registered.")
    return cur.lastrowid, api_key


def get_account_by_api_key(conn, api_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM accounts WHERE api_key_hash = ?", (_hash_key(api_key),)
    ).fetchone()


def announce_provider(conn, account_id: int, cpu_cores: float, ram_mb: int,
                       gpu_model, gpu_vram_mb, task_types: list[str], provider_id=None) -> int:
    now = time.time()
    task_types_csv = ",".join(task_types)
    if provider_id is not None:
        existing = conn.execute("SELECT id FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE providers SET cpu_cores=?, ram_mb=?, gpu_model=?, gpu_vram_mb=?, "
                "task_types=?, last_heartbeat=? WHERE id=?",
                (cpu_cores, ram_mb, gpu_model, gpu_vram_mb, task_types_csv, now, provider_id),
            )
            conn.commit()
            return provider_id
    cur = conn.execute(
        "INSERT INTO providers (account_id, cpu_cores, ram_mb, gpu_model, gpu_vram_mb, "
        "task_types, last_heartbeat) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (account_id, cpu_cores, ram_mb, gpu_model, gpu_vram_mb, task_types_csv, now),
    )
    conn.commit()
    return cur.lastrowid


def list_online_providers(conn, min_cpu=0, min_ram_mb=0, require_gpu=False, min_vram_mb=0):
    cutoff = time.time() - HEARTBEAT_TIMEOUT_S
    rows = conn.execute(
        "SELECT * FROM providers WHERE last_heartbeat >= ? AND busy = 0 "
        "AND cpu_cores >= ? AND ram_mb >= ?",
        (cutoff, min_cpu, min_ram_mb),
    ).fetchall()
    if require_gpu:
        rows = [r for r in rows if r["gpu_model"] and (r["gpu_vram_mb"] or 0) >= min_vram_mb]
    return rows


def submit_job(conn, consumer_account_id: int, task_type: str, payload_format: str,
               payload_b64: str, cpu_limit: float, ram_limit_mb: int, gpu_required: bool,
               timeout_s: int) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (consumer_account_id, task_type, payload_format, payload_b64, "
        "cpu_limit, ram_limit_mb, gpu_required, timeout_s, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (consumer_account_id, task_type, payload_format, payload_b64,
         cpu_limit, ram_limit_mb, int(gpu_required), timeout_s, time.time()),
    )
    conn.commit()
    return cur.lastrowid


def try_assign_job(conn, provider_row) -> sqlite3.Row | None:
    """Find one queued job this provider can handle (resources + installed handler) and assign it."""
    supported = provider_row["task_types"].split(",")
    placeholders = ",".join("?" for _ in supported)
    gpu_clause = "" if provider_row["gpu_model"] else "AND gpu_required = 0"
    job = conn.execute(
        f"SELECT * FROM jobs WHERE status = 'queued' AND cpu_limit <= ? AND ram_limit_mb <= ? "
        f"AND task_type IN ({placeholders}) {gpu_clause} ORDER BY created_at ASC LIMIT 1",
        (provider_row["cpu_cores"], provider_row["ram_mb"], *supported),
    ).fetchone()
    if job is None:
        return None
    conn.execute(
        "UPDATE jobs SET status = 'assigned', provider_id = ? WHERE id = ?",
        (provider_row["id"], job["id"]),
    )
    conn.execute("UPDATE providers SET busy = 1 WHERE id = ?", (provider_row["id"],))
    conn.commit()
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()


def report_success(conn, job_id: int, result_format: str, result_b64: str, compute_seconds: float):
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        return
    conn.execute(
        "UPDATE jobs SET status='done', result_format=?, result_b64=?, compute_seconds=?, "
        "finished_at=? WHERE id=?",
        (result_format, result_b64, compute_seconds, time.time(), job_id),
    )
    conn.execute("UPDATE providers SET busy = 0 WHERE id = ?", (job["provider_id"],))

    resource_weight = job["cpu_limit"] + job["ram_limit_mb"] / 1024
    credits = compute_seconds * resource_weight * CREDIT_RATE_PER_RESOURCE_SECOND
    provider_account_id = conn.execute(
        "SELECT account_id FROM providers WHERE id = ?", (job["provider_id"],)
    ).fetchone()["account_id"]
    conn.execute("UPDATE accounts SET credits = credits + ? WHERE id = ?",
                 (credits, provider_account_id))
    conn.execute("UPDATE accounts SET credits = credits - ? WHERE id = ?",
                 (credits, job["consumer_account_id"]))
    conn.commit()


def report_failure(conn, job_id: int, error: str):
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        return
    conn.execute(
        "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
        (error, time.time(), job_id),
    )
    if job["provider_id"] is not None:
        conn.execute("UPDATE providers SET busy = 0 WHERE id = ?", (job["provider_id"],))
    conn.commit()


def stats(conn):
    cutoff = time.time() - HEARTBEAT_TIMEOUT_S
    online = conn.execute(
        "SELECT COUNT(*) AS n FROM providers WHERE last_heartbeat >= ?", (cutoff,)
    ).fetchone()["n"]
    jobs = conn.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done, "
        "COALESCE(SUM(compute_seconds), 0) AS secs FROM jobs"
    ).fetchone()
    leaderboard = conn.execute(
        "SELECT name, credits FROM accounts ORDER BY credits DESC LIMIT 10"
    ).fetchall()
    return {
        "providers_online": online,
        "jobs_total": jobs["total"] or 0,
        "jobs_done": jobs["done"] or 0,
        "compute_hours_donated": round((jobs["secs"] or 0) / 3600, 3),
        "leaderboard": [dict(r) for r in leaderboard],
    }
