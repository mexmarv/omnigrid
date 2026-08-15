# Deploying the hub on a VPS (e.g. Hostinger VPS, chanza.io)

Shared/WordPress hosting (cPanel/hPanel-only plans) can't reliably run a
persistent Python process -- this needs a VPS or Cloud plan with real SSH
access. Exact menu wording in Hostinger's panel may differ slightly from
what's below; the shape of the steps won't.

Assumes Ubuntu 22.04/24.04 (Hostinger's standard VPS template) and that
you've already pushed this repo to GitHub.

## 1. Provision the VPS

In Hostinger's hPanel: order a VPS plan, choose an Ubuntu LTS template,
note the server's public IP and root password (or upload an SSH key during
setup, which is better than password auth).

## 2. Point a subdomain at it

`chanza.io`'s DNS is already managed in Hostinger -- in its DNS zone editor,
add:

```
Type: A
Name: hub
Value: <your VPS's public IP>
```

This gives you `hub.chanza.io` without touching your main site.

## 3. SSH in and do base setup

```bash
ssh root@<vps-ip>

adduser --disabled-password --gecos "" compute-commons
apt update && apt install -y python3.12 python3.12-venv git nginx certbot python3-certbot-nginx ufw

ufw allow OpenSSH
ufw allow "Nginx Full"
ufw enable
```

## 4. Get the code and install dependencies

```bash
mkdir -p /opt/compute-commons && chown compute-commons:compute-commons /opt/compute-commons
su - compute-commons
git clone https://github.com/mexmarv/omnigrid.git /opt/compute-commons/repo
cd /opt/compute-commons/repo
python3.12 -m venv /opt/compute-commons/.venv
source /opt/compute-commons/.venv/bin/activate
pip install -r hub/requirements.txt
exit  # back to root
```

(The hub itself only needs `hub/requirements.txt`. You don't need
`agent/requirements.txt` or a downloaded model on this box unless you also
want this same VPS to act as a provider -- usually you don't; keep the hub
lightweight and let community members' own machines be providers.)

## 5. Install the systemd service

```bash
cp /opt/compute-commons/repo/deploy/hub.service /etc/systemd/system/
# hub.service's WorkingDirectory expects the hub/ subfolder at
# /opt/compute-commons/hub -- symlink the cloned repo's hub/ dir there
ln -s /opt/compute-commons/repo/hub /opt/compute-commons/hub
systemctl daemon-reload
systemctl enable --now hub
systemctl status hub   # should show "active (running)"
```

## 6. Nginx + TLS

```bash
cp /opt/compute-commons/repo/deploy/nginx.conf /etc/nginx/sites-available/hub.chanza.io
ln -s /etc/nginx/sites-available/hub.chanza.io /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

certbot --nginx -d hub.chanza.io   # gets a free Let's Encrypt cert, edits the config for you
```

## 7. Verify

```bash
curl https://hub.chanza.io/stats
# {"providers_online":0,"jobs_total":0,"jobs_done":0,"compute_hours_donated":0.0,"leaderboard":[]}
```

Anyone can now point their agent/client at `https://hub.chanza.io` as the
`--coordinator`/`coordinator=` value instead of `http://127.0.0.1:8000`.

## Ongoing care

- **Back up `hub/data/hub.db`.** It's the entire account/credit/job
  ledger -- a plain SQLite file, no replication. A daily `cp` to somewhere
  off the VPS is enough for now.
- **Watch disk usage** if providers host large models or many jobs queue up.
- The hub itself binds to `127.0.0.1:8000` (see `hub.service`) -- it's not
  reachable except through nginx, so there's no need to separately firewall
  off port 8000.
- Before real public use, also read the README's "Honest limitations"
  section -- job-result read auth and rate limiting aren't done yet.
