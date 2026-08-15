# Running the backoffice

No VPS, no systemd, no nginx, no certbot needed for real hosting -- this is
plain PHP + SQLite by default, the simplest thing that could work. Test it
on your own machine in two minutes, then upload the same files to Hostinger
(or any shared PHP host) when you're ready.

## Test it locally first

Requires PHP (`php -v` to check; `brew install php` on a Mac if you don't
have it).

```bash
git clone https://github.com/mexmarv/omnigrid.git
cd omnigrid/backoffice
cp config.example.php config.php   # SQLite is the default, nothing to edit
php -S 127.0.0.1:8000
```

That's it -- a full backoffice is now running at `http://127.0.0.1:8000`.
Open it in a browser to see the dashboard, and visit `/register.php` to
create an account and see an API key -- that page also generates the
Omnigent YAML block and CLI command with your name/key already filled in,
so it doubles as the "how do I configure my multi-harness" answer for
whoever's looking at the dashboard. Or check everything's alive via curl:

```bash
curl http://127.0.0.1:8000/api/stats.php
# {"providers_online":0,"jobs_total":0,"jobs_done":0,"compute_hours_donated":0,"leaderboard":[]}
```

Tables are created automatically on first request -- no migration step.
Now point a client at it to see the whole thing work end to end:

```bash
cd ../client
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 agent.py --name "test" --cpu-cores 1 --ram-mb 512 --ignore-idle \
    --coordinator http://127.0.0.1:8000
```

In another terminal, submit it something to do:

```bash
python3 -c "
import client_sdk as cc
import numpy as np
print(cc.run_tensor_op('matmul', np.array([[1.,2.],[3.,4.]]), np.array([[5.,6.],[7.,8.]]),
                        account_name='me', coordinator='http://127.0.0.1:8000'))
"
```

Delete `backoffice/data/omnigrid.sqlite` any time to reset and start clean.

## Putting it on a real domain (Hostinger or any shared PHP host)

Exact hPanel wording may differ slightly from what's below; the shape of
the steps won't.

1. **Upload just the `backoffice/` folder's contents** to a subdomain's
   document root -- e.g. if `chanza.ai` has a subdomain `hub.chanza.ai`
   pointed at `/public_html/hub/`, upload everything in `backoffice/` there
   (hPanel's File Manager, or FTP/SFTP). You don't need `client/` or
   `mcp_server/` on the server -- those are what people install on their
   own machines.
2. **Make sure `data/` is writable** by the PHP process (shared hosts
   usually make anything under your own web root writable by default;
   if not, `chmod 755 data/` via File Manager or SFTP).
3. **Copy `config.example.php` to `config.php`.** SQLite is the default --
   nothing to fill in. Only switch to the commented-out MySQL block if you
   specifically want a managed database (see below).
4. **Turn on TLS.** Hostinger shared plans normally offer free AutoSSL /
   Let's Encrypt directly in hPanel for any domain pointed at your account.
   Don't run this over plain HTTP in production -- API keys travel in the
   `Authorization` header on every request.
5. **Verify:** `curl https://hub.chanza.ai/api/stats.php` should return the
   same empty stats JSON as the local test above.

Point anyone's `client/` or `mcp_server/` at `https://hub.chanza.ai` as the
`--coordinator` / `coordinator=` / `OMNIGRID_HUB` value.

## SQLite vs. MySQL

SQLite is the default for a reason: one file, nothing to provision, nothing
to leak if it's ever misconfigured, and it comfortably handles a community
project's request volume -- this isn't a high-frequency trading system.
The one real tradeoff is SQLite serializes writes (one writer at a time),
which matters if you expect heavy concurrent job submission at real scale.
If you outgrow it, switch to the MySQL block in `config.example.php` --
nothing else about the code changes.

## Ongoing care

- **Back up `backoffice/data/omnigrid.sqlite`** (or your MySQL database if
  you went that route). It's the entire account/credit/job ledger, no
  replication. A daily copy off the server is enough for now.
- **Watch storage size** if a lot of job payloads/results accumulate --
  there's currently no automatic cleanup of old finished jobs.
- Before wide public use, also read the main README's "Honest limitations"
  section -- job-result read auth and rate limiting aren't done yet.
