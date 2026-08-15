# Hosting the backoffice on Hostinger (or any shared PHP host)

No VPS, no systemd, no nginx, no certbot -- this is plain PHP + MySQL, the
thing shared hosting is built for. Exact hPanel wording may differ slightly
from what's below; the shape of the steps won't.

## 1. Create a MySQL database

In Hostinger's hPanel: **Databases -> MySQL Databases**. Create a database,
a database user, and a password. Note all three plus the host (usually
`localhost` on shared plans).

## 2. Upload the `backoffice/` folder

Upload just this `backoffice/` folder's contents to a subdomain's document
root -- e.g. if `chanza.ai` has a subdomain `hub.chanza.ai` pointed at
`/public_html/hub/`, upload everything in `backoffice/` into that folder
(via hPanel's File Manager, or FTP/SFTP -- whichever you're used to).

You do **not** need to upload `client/` or `mcp_server/` here -- those are
what people install on their own machines, not part of the hosted backoffice.

## 3. Configure

Copy `config.example.php` to `config.php` (same folder) and fill in the
database details from step 1:

```php
<?php
return [
    'dsn' => 'mysql:host=localhost;dbname=your_db_name;charset=utf8mb4',
    'db_user' => 'your_db_user',
    'db_pass' => 'your_db_password',
];
```

`.htaccess` already blocks direct access to `config.php` and fixes a common
shared-hosting gotcha (some Apache/CGI setups strip the `Authorization`
header before PHP ever sees it).

## 4. Verify

Visit `https://hub.chanza.ai/` -- you should see the live dashboard (0
providers, 0 jobs, since nobody's connected yet). Tables are created
automatically on first request; there's no separate migration step.

```bash
curl https://hub.chanza.ai/api/stats.php
# {"providers_online":0,"jobs_total":0,"jobs_done":0,"compute_hours_donated":0,"leaderboard":[]}
```

Point anyone's `client/` or `mcp_server/` at `https://hub.chanza.ai` as the
`--coordinator` / `coordinator=` / `OMNIGRID_HUB` value.

## TLS

Hostinger shared plans normally offer free AutoSSL / Let's Encrypt directly
in hPanel for any domain or subdomain pointed at your account -- turn that
on for whichever domain you use. Don't run this over plain HTTP in
production; API keys travel in the `Authorization` header on every request.

## Ongoing care

- **Back up the database** (hPanel's phpMyAdmin has an Export tab, or set
  up scheduled backups if your plan includes them). It's the entire
  account/credit/job ledger.
- **Watch your database size** if a lot of job payloads/results accumulate
  -- there's currently no automatic cleanup of old finished jobs.
- Before wide public use, also read the main README's "Honest limitations"
  section -- job-result read auth and rate limiting aren't done yet.
