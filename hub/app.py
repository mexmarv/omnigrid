"""
Hub: the central directory + matchmaker + credit ledger.

The hub NEVER executes anything and never inspects job payloads beyond
routing them -- it just tracks who's online with what resources, matches
queued jobs to a capable provider, and relays the (data-only) payload and
result between consumer and provider.

Every account-acting endpoint requires `Authorization: Bearer <api_key>`,
issued once by POST /accounts/register. There's no username/password, no
email, no recovery flow -- the key IS the account, like an SSH key. Losing
it means losing access to that account's credits and providers.

Run:
    uvicorn app:app --reload --port 8000
"""

from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import store

app = FastAPI(title="compute-commons hub")

ALLOWED_PAYLOAD_FORMATS = {"json", "npy", "onnx"}


def get_current_account(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing 'Authorization: Bearer <api_key>' header.")
    api_key = authorization.removeprefix("Bearer ").strip()
    conn = store.get_db()
    account = store.get_account_by_api_key(conn, api_key)
    conn.close()
    if account is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return account


class RegisterRequest(BaseModel):
    name: str


class AnnounceRequest(BaseModel):
    provider_id: Optional[int] = None
    cpu_cores: float
    ram_mb: int
    gpu_model: Optional[str] = None
    gpu_vram_mb: Optional[int] = None
    task_types: list[str]


class SubmitRequest(BaseModel):
    task_type: str
    payload_format: str
    payload_b64: str
    cpu_limit: float = 1.0
    ram_limit_mb: int = 512
    gpu_required: bool = False
    timeout_s: int = 30


class ResultRequest(BaseModel):
    job_id: int
    result_format: str
    result_b64: str
    compute_seconds: float


class FailureRequest(BaseModel):
    job_id: int
    error: str


@app.post("/accounts/register")
def register(req: RegisterRequest):
    conn = store.get_db()
    try:
        account_id, api_key = store.create_account(conn, req.name)
    except store.AccountNameTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    finally:
        conn.close()
    return {"account_id": account_id, "api_key": api_key}


@app.post("/providers/announce")
def announce(req: AnnounceRequest, account=Depends(get_current_account)):
    conn = store.get_db()
    if req.provider_id is not None:
        existing = conn.execute(
            "SELECT account_id FROM providers WHERE id = ?", (req.provider_id,)
        ).fetchone()
        if existing is None:
            conn.close()
            raise HTTPException(status_code=404, detail="Unknown provider_id.")
        if existing["account_id"] != account["id"]:
            conn.close()
            raise HTTPException(status_code=403, detail="That provider_id belongs to a different account.")
    provider_id = store.announce_provider(
        conn, account["id"], req.cpu_cores, req.ram_mb, req.gpu_model,
        req.gpu_vram_mb, req.task_types, req.provider_id,
    )
    conn.close()
    return {"provider_id": provider_id}


@app.get("/providers")
def list_providers():
    conn = store.get_db()
    rows = store.list_online_providers(conn)
    conn.close()
    return [dict(r) for r in rows]


@app.get("/providers/{provider_id}/next-job")
def next_job(provider_id: int, account=Depends(get_current_account)):
    conn = store.get_db()
    row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Unknown provider.")
    if row["account_id"] != account["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="That provider_id belongs to a different account.")
    job = store.try_assign_job(conn, row)
    conn.close()
    if job is None:
        raise HTTPException(status_code=204, detail="No job available.")
    return dict(job)


@app.post("/jobs/submit")
def submit_job(req: SubmitRequest, account=Depends(get_current_account)):
    if req.payload_format not in ALLOWED_PAYLOAD_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"payload_format must be one of {sorted(ALLOWED_PAYLOAD_FORMATS)} "
                   f"-- raw code/pickle/commands are never accepted.",
        )
    conn = store.get_db()
    job_id = store.submit_job(
        conn, account["id"], req.task_type, req.payload_format, req.payload_b64,
        req.cpu_limit, req.ram_limit_mb, req.gpu_required, req.timeout_s,
    )
    conn.close()
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: int):
    conn = store.get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return dict(row)


def _require_owns_job_provider(conn, job_id: int, account_id: int):
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    provider = conn.execute(
        "SELECT account_id FROM providers WHERE id = ?", (job["provider_id"],)
    ).fetchone()
    if provider is None or provider["account_id"] != account_id:
        raise HTTPException(status_code=403, detail="This job isn't assigned to one of your providers.")


@app.post("/jobs/result")
def post_result(req: ResultRequest, account=Depends(get_current_account)):
    conn = store.get_db()
    _require_owns_job_provider(conn, req.job_id, account["id"])
    store.report_success(conn, req.job_id, req.result_format, req.result_b64, req.compute_seconds)
    conn.close()
    return {"ok": True}


@app.post("/jobs/failure")
def post_failure(req: FailureRequest, account=Depends(get_current_account)):
    conn = store.get_db()
    _require_owns_job_provider(conn, req.job_id, account["id"])
    store.report_failure(conn, req.job_id, req.error)
    conn.close()
    return {"ok": True}


@app.get("/stats")
def get_stats():
    conn = store.get_db()
    result = store.stats(conn)
    conn.close()
    return result


@app.get("/", response_class=HTMLResponse)
def dashboard():
    s = store.stats(store.get_db())
    rows = "".join(
        f"<tr><td>{r['name']}</td><td>{r['credits']:.1f}</td></tr>" for r in s["leaderboard"]
    )
    return f"""
    <html><head><title>compute-commons</title></head>
    <body style="font-family: monospace; max-width: 700px; margin: 40px auto;">
      <h2>compute-commons -- live hub</h2>
      <p>Providers online: <b>{s['providers_online']}</b></p>
      <p>Compute donated: <b>{s['compute_hours_donated']} hours</b></p>
      <p>Jobs: <b>{s['jobs_done']} / {s['jobs_total']}</b> complete</p>
      <h3>Credit leaderboard</h3>
      <table border="1" cellpadding="6"><tr><th>account</th><th>credits</th></tr>{rows}</table>
    </body></html>
    """
