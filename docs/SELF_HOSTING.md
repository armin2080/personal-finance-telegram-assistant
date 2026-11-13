# Self-hosting

The application is a single Python process with one SQLite file. It runs on any
Linux host with Python 3.11 or newer, including small low-power machines. Choose
a host you control and keep the database on that host.

## Requirements

- Linux with Python 3.11+ and `python3-venv`.
- Roughly 100 MiB of free disk for the environment plus room for the database.
- Outbound HTTPS access, which is all the Telegram long-polling client needs.
- No inbound port, public DNS name, reverse proxy, or database server.

## Install

```bash
sudo install -d -o "$USER" -g "$USER" -m 0755 /opt/personal-finance-assistant
git clone <your-fork-url> /opt/personal-finance-assistant
cd /opt/personal-finance-assistant
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install .
```

For development, install `.[dev]` instead to get `pytest`, `ruff`, and `mypy`.

## Configuration

Copy `.env.example` to `.env` and fill it in. Keep the real file private:

```bash
install -m 0600 .env.example .env
```

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from `@BotFather`. Required to run the bot. |
| `TELEGRAM_ALLOWED_USER_IDS` | Comma-separated numeric Telegram user IDs. Empty means the bot refuses to start. |
| `FPA_DATABASE_PATH` | Absolute path to the SQLite file. Keep it outside the repository. |
| `FPA_USER_TIMEZONE` | Timezone for user-facing month and day boundaries. Default `Europe/Berlin`. |
| `FPA_LOG_LEVEL` | Operational log level. Default `INFO`. |
| `FPA_MIN_FREE_BYTES` | Minimum free disk before writes are refused. Default `104857600`. |
| `FPA_MAX_UPLOAD_BYTES` | Maximum accepted Telegram CSV upload size. Default `10485760`. |

Create the database and verify the install:

```bash
.venv/bin/finance-assistant init-db
.venv/bin/finance-assistant status
.venv/bin/finance-assistant integrity
```

`status` reports schema version and row counts only. It never prints amounts or
transaction text.

## Running under systemd

Adapt the example units in `systemd/` before installing them. Replace the
service account, paths, and the environment file location with your own.

```bash
sudo cp systemd/finance-assistant.service.example /etc/systemd/system/finance-assistant.service
sudo systemctl daemon-reload
sudo systemctl enable --now finance-assistant.service
```

Useful commands:

```bash
systemctl status finance-assistant.service
journalctl -u finance-assistant.service -n 100 --no-pager
systemctl restart finance-assistant.service
```

The units include `NoNewPrivileges`, `ProtectSystem`, `ProtectHome`, and similar
restrictions. Keep them enabled unless you can document why an option conflicts
with your host.

## Accessing the web cockpit

The cockpit is a local web app, not a Telegram web app. It binds to
`127.0.0.1` by default and has no login of its own, so treat it as a
loopback-only service:

```bash
finance-assistant web --host 127.0.0.1 --port 8000
```

Reach it from another device through a private channel rather than by exposing
the port:

- **SSH port forward** — `ssh -N -L 8000:127.0.0.1:8000 <user>@<host>`, then open
  `http://127.0.0.1:8000/` in the browser on the client.
- **Private VPN** — an overlay network that only your devices join.

If you want the cockpit reachable from your phone over HTTPS, terminate TLS in
front of the loopback listener with a private-network proxy. Do not bind the app
to `0.0.0.0` and do not forward the port on a router. The API returns
transaction-level data and has no authentication, CSRF protection, or session
handling; public exposure requires a separate authentication and threat-model
design first. See `docs/adr/0007-local-dashboard-adapter.md`.

### Install it on a phone

The cockpit is an installable progressive web app. It needs a secure context, so
serve it over HTTPS or through `http://localhost` on the device itself; a plain
HTTP tunnel to a remote host is not enough for the service worker to activate.

1. Open the cockpit URL in the phone browser.
2. Android Chrome: menu → **Add to Home screen** → **Install**.
3. iPhone Safari: Share → **Add to Home Screen**.
4. Launch it from the home screen. It opens full screen with the app icon.

The service worker caches only the app shell — the HTML entry point, CSS, JS,
icons, and manifest. It never caches `/api/` responses, so financial data is
always read live from the local SQLite database. Clearing site data refreshes
the shell.

## Backup and restore

Use the SQLite online backup API. Never copy a live WAL database with a file
copy.

```bash
finance-assistant backup /var/backups/finance-assistant/finance-$(date +%F).sqlite3
```

Encrypt any backup before it leaves the host, and keep at least one copy
offline. A backup is not verified until a restore has been tested:

1. Stop the service.
2. Restore the backup into a separate directory, not over the production path.
3. Run `PRAGMA integrity_check` on the restored file.
4. Point a test instance at it and compare counts and period totals.
5. Only then replace the production database.

## Upgrading

```bash
systemctl stop finance-assistant.service finance-assistant-web.service
finance-assistant backup /var/backups/finance-assistant/pre-upgrade.sqlite3
git -C /opt/personal-finance-assistant pull --ff-only
/opt/personal-finance-assistant/.venv/bin/pip install --upgrade /opt/personal-finance-assistant
finance-assistant init-db          # applies pending migrations
finance-assistant status           # confirm the schema version
systemctl start finance-assistant.service finance-assistant-web.service
```

Migrations run inside one transaction per step. A failure rolls the schema back
to the previous version, so the upgrade is retryable. Restore the pre-upgrade
backup if you need to return to the previous release, because an older binary
cannot read a newer schema.

## Backup-independent deletion

```bash
systemctl stop finance-assistant.service finance-assistant-web.service
finance-assistant purge --yes
```

This deletes the database and its SQLite sidecars. It cannot guarantee removal
from wear-levelled flash storage or from backups you created earlier, so handle
those separately.

## Permissions

- Service account: unprivileged, dedicated to this application.
- Database directory: `0700`.
- Database file and `.env`: `0600`.
- Logs: operational events only. Never log transaction text, merchant names,
  amounts, or Telegram message content.
