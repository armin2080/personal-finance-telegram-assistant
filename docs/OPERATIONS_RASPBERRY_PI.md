# Raspberry Pi deployment and operations

## Target profile

The initial target is a small Raspberry Pi device, potentially a Zero 2 W (512 MB RAM). The application should remain a lightweight Python process with SQLite. Do not run an LLM, PostgreSQL, Redis, Docker engine, a public web dashboard, or a large data-science stack on this device. The optional cockpit binds to `127.0.0.1` only.

## Recommended topology

```text
Internet / Telegram Bot API
          ^
          | outbound HTTPS only (long polling)
          v
Raspberry Pi
  systemd: finance-assistant.service
  Python virtual environment
  SQLite database + WAL
  private .env / EnvironmentFile
  encrypted backup directory
```

No router port-forwarding, public webhook, reverse proxy, or public IP is required.

## Initial host preparation

1. Confirm OS and architecture with `uname -a`, `cat /etc/os-release`, and `python3 --version`.
2. Confirm available RAM and disk with `free -h` and `df -h`.
3. Update the OS and install Python venv/pip and Git.
4. Create a dedicated service account, for example `financebot`, with no interactive login if the owner's administration workflow allows it.
5. Choose a private application path such as `/opt/personal-finance-assistant` and a state path such as `/var/lib/finance-assistant`.
6. Clone only the private repository. Never copy an unredacted bank export into the repository directory.

## Python installation

Use the Python version supported by the target OS and this project's `requires-python` declaration (3.11+). Create a virtual environment:

```bash
sudo -u financebot python3 -m venv /opt/personal-finance-assistant/.venv
sudo -u financebot /opt/personal-finance-assistant/.venv/bin/pip install --upgrade pip
sudo -u financebot /opt/personal-finance-assistant/.venv/bin/pip install /opt/personal-finance-assistant
```

For development checks, install `.[dev]` on a development machine; keep test/lint packages off the production Pi unless needed.

## Configuration and permissions

- The SQLite database is not encrypted by the application. File permissions protect against other local users but not someone who can read the SD card. Evaluate full-disk/data-volume encryption against unattended-reboot and recovery needs.
- Store the real BotFather token in `/etc/finance-assistant/bot.env`.
- Set `TELEGRAM_ALLOWED_USER_IDS` to the owner's numeric ID.
- Set `FPA_DATABASE_PATH=/var/lib/finance-assistant/finance.sqlite3`.
- Set `FPA_USER_TIMEZONE=Europe/Berlin`.
- Set the environment file to `root:financebot` and mode `0640`, or `financebot:financebot` and mode `0600` according to the service-account policy.
- Make `/var/lib/finance-assistant` mode `0700` and database files mode `0600`.
- Do not put secrets in the systemd unit itself.

## Import workflow

1. Export booked transactions from the bank.
2. Transfer the file to a temporary private directory on the Pi using SFTP/SCP.
3. Run `finance-assistant inspect FILE`.
4. Review the preview locally.
5. Run `finance-assistant import FILE --commit`.
6. Remove the original export from the temporary directory according to the owner's retention policy.
7. Do not upload the file to GitHub. Telegram CSV uploads are supported only in the configured private allowlisted chat and are deleted after temporary local processing.

## systemd

Review `systemd/finance-assistant.service.example`. Replace paths and service user before installation. Keep hardening options enabled unless the owner documents why a specific option is incompatible.

Useful commands:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now finance-assistant.service
sudo systemctl status finance-assistant.service
sudo journalctl -u finance-assistant.service -n 100 --no-pager
sudo systemctl restart finance-assistant.service
```

Logs must not contain transaction text, merchant names, amounts, or tokens.

## Backup and restore

Create a consistent backup using SQLite's backup API:

```bash
finance-assistant backup /var/backups/finance-assistant/finance-$(date +%F).sqlite3
```

Encrypt before copying the file off the Pi. Keep at least one offline copy. A backup strategy is not complete until restore has been tested:

1. Stop the service.
2. Restore into a separate test path.
3. Run SQLite `PRAGMA integrity_check` on the restored DB.
4. Start a test app pointed to the restored database and compare aggregate counts/totals.
5. Do not overwrite the production DB until the restore is verified.

## Status and deletion

`finance-assistant status` reports only schema and row counts. It does not print
financial values or transaction text. To permanently delete local transaction
data, stop the service, create and verify any required backup, then run:

```bash
sudo systemctl stop finance-assistant.service
sudo -u financebot env FPA_DATABASE_PATH=/var/lib/finance-assistant/finance.sqlite3 \
  finance-assistant purge --yes
sudo systemctl start finance-assistant.service
```

Deletion is local and cannot guarantee removal from SD-card wear-levelled
storage or previously created encrypted backups.

## Operations checklist

- [x] Service account, private state directory, and disabled systemd unit provisioned on the target Pi.
- [x] Environment file and database permissions checked (`0640` config, `0600` SQLite files, `0700` state directory).
- [x] No project inbound port is listening; the unit uses outbound Telegram long polling only.
- [x] Service restarts after a Pi reboot.
- [x] Bot reaches the Telegram Bot API over outbound HTTPS.
- [x] Owner verified `/start` and `/summary` from the allowlisted private chat.
- [x] Disk-space threshold/monitoring configured through `FPA_MIN_FREE_BYTES`.
- [ ] Backup schedule chosen and encrypted off-device backup tested.
- [x] SQLite online backup restored to a separate file and passed `PRAGMA integrity_check`.
- [x] Token is configured in the private environment file; rotation procedure remains owner-controlled.
- [ ] No financial values in journal logs.

## Verified target-Pi baseline

The target host is a Raspberry Pi Zero 2 W-class system running Debian 12,
aarch64, and Python 3.11.2. The installed virtual environment passes the full
54-test suite under Python 3.11.2. The pytest process used 51,564 KiB peak
resident memory during that run; this is a test-suite measurement, not a
production bot memory bound.

The unit is installed but remains disabled and inactive until the owner adds a
real `TELEGRAM_BOT_TOKEN` and numeric `TELEGRAM_ALLOWED_USER_IDS` to the private
environment file. Do not start it with placeholder or missing credentials.

The application refuses import, budget, and backup writes when free storage
falls below `FPA_MIN_FREE_BYTES` (100 MiB by default). Read-only status/report
operations remain available so the owner can recover space safely.


## Updating to the recovery release (schema v6)

Do this on the Pi, not against the production database from a development
machine. Stop the bot before taking the pre-upgrade backup.

```bash
cd /opt/personal-finance-assistant

# 1. Stop writes and take a pre-upgrade backup with the OLD installed code.
sudo systemctl stop finance-assistant.service
sudo -u financebot /opt/personal-finance-assistant/.venv/bin/finance-assistant   backup /var/backups/finance-assistant/pre-recovery-$(date +%F).sqlite3
sudo -u financebot sqlite3 /var/backups/finance-assistant/pre-recovery-$(date +%F).sqlite3   "PRAGMA integrity_check;"

# 2. Update the checkout and the installed package.
sudo -u financebot git fetch origin
sudo -u financebot git checkout recovery/20261110-qa-fixes
sudo -u financebot git pull --ff-only
sudo -u financebot /opt/personal-finance-assistant/.venv/bin/pip install   --upgrade /opt/personal-finance-assistant

# 3. Run the atomic migration explicitly and verify it.
sudo -u financebot env   FPA_DATABASE_PATH=/var/lib/finance-assistant/finance.sqlite3   /opt/personal-finance-assistant/.venv/bin/finance-assistant status
sudo -u financebot env   FPA_DATABASE_PATH=/var/lib/finance-assistant/finance.sqlite3   /opt/personal-finance-assistant/.venv/bin/finance-assistant integrity

# 4. Reapply the new deterministic rules to historical rows. User corrections
#    and dismissed rows are preserved; non-user merchant labels are normalised.
sudo -u financebot env   FPA_DATABASE_PATH=/var/lib/finance-assistant/finance.sqlite3   /opt/personal-finance-assistant/.venv/bin/finance-assistant reprocess

# 5. Start the bot and verify the service.
sudo systemctl start finance-assistant.service
sudo systemctl status finance-assistant.service
sudo journalctl -u finance-assistant.service -n 50 --no-pager
```

The migration v5→v6 adds the split-aware view, note/evidence fields, structured
rules and link table. It also marks old import batches with
`possible_duplicate_count > 0` as `incomplete` so they can be resumed with
`--accept-possible-duplicates` instead of being permanently locked out.

### Rollback

The migration runs in one transaction and leaves the previous schema intact on
failure. If you need to roll back after a successful migration:

```bash
sudo systemctl stop finance-assistant.service
sudo -u financebot git checkout 13e40b6
sudo -u financebot /opt/personal-finance-assistant/.venv/bin/pip install   --upgrade /opt/personal-finance-assistant
# Either restore the verified pre-upgrade backup into the production path, or
# keep the v6 database and run the previous release only after confirming that
# it can read the schema (it cannot; restore the backup).
sudo systemctl start finance-assistant.service
```

Prefer restoring the verified pre-upgrade backup. Do not edit the production
database by hand.

## Optional local cockpit

The cockpit is a local FastAPI/HTML application, not a Telegram web app. No
BotFather setting is required. Install the example unit only if you want it
running continuously:

```bash
sudo cp systemd/finance-assistant-web.service.example   /etc/systemd/system/finance-assistant-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now finance-assistant-web.service
```

It binds to `127.0.0.1:8000`. From your laptop, create an SSH tunnel:

```bash
ssh -N -L 8000:127.0.0.1:8000 financebot@<pi-host>
```

Then open `http://127.0.0.1:8000/` on the laptop. Do not change the bind address
to `0.0.0.0` or expose the port through the router. Doing so would require a
separate authentication, CSRF and threat-model decision.

### Mobile access (Android)

The cockpit has no login of its own. Use an SSH local port forward from the
phone; the phone's loopback address becomes the authenticated path to the Pi.

1. On the Pi, install and start the optional cockpit service, then verify it:
   `sudo systemctl enable --now finance-assistant-web.service`,
   `sudo systemctl status finance-assistant-web.service --no-pager`, and
   `curl -fsS http://127.0.0.1:8000/api/health`.
2. Confirm SSH is running (`sudo systemctl status ssh --no-pager`) and note the
   login account (`whoami`). Use the account you normally administer the Pi
   with; the unprivileged `financebot` service account may have no login shell.
3. On Android, install **Termux** from F-Droid (the Play Store build is
   deprecated) and **Tailscale** from the Play Store/F-Droid if the Pi is
   reached through a tailnet. Both are free and open source.
4. In Termux:
   `pkg update && pkg install openssh`,
   `ssh-keygen -t ed25519 -C android`, then `cat ~/.ssh/id_ed25519.pub`.
   Add that public key to the Pi account's `~/.ssh/authorized_keys`
   (`chmod 700 ~/.ssh`, `chmod 600 ~/.ssh/authorized_keys`).
5. Test the route, then leave the tunnel running:
   `ssh -N -L 8000:127.0.0.1:8000 <login-user>@<pi-lan-ip>` on the home Wi-Fi,
   or `ssh -N -L 8000:127.0.0.1:8000 <login-user>@<pi-vpn-ip>` when remote.
6. Open `http://127.0.0.1:8000/` in the phone browser. Use `127.0.0.1`, not
   the Pi's address: the listener is on the phone. If phone port 8000 is busy,
   forward `-L 8080:127.0.0.1:8000` and open `http://127.0.0.1:8080/`.
7. Keep the tunnel alive with `termux-wake-lock` and by disabling Android
   battery optimisation for Termux. `tmux` is useful for detaching/reattaching.

ConnectBot (Apache-2.0) is an alternative: add the Pi host, then configure a
local port forward from `8000` to `127.0.0.1:8000` and keep the session open.

Remote access must go through a private VPN such as Tailscale/WireGuard, not a
router port forward of the cockpit or SSH. Tailscale `serve` can proxy the
loopback cockpit over a private tailnet, but that exposes the unauthenticated
cockpit to every device in that tailnet; prefer the SSH tunnel unless the
tailnet and its devices are fully trusted. Never enable Telegram inline mode,
a Web App/Mini App, or a public webhook for cockpit access.

### Web statement import

The cockpit can preview and import a Sparkasse CSV without the CLI. Open
**Import**, choose the file, review each suggested merchant/category/type, edit
ambiguous rows (for example PayPal descriptors), then commit. The parsed preview
is held in memory for 30 minutes, is limited to 10 MB, and is never sent to
Telegram or an external service. The uploaded source is not retained after the
request. Exact-file protection and possible-duplicate review remain in force;
possible duplicates are skipped unless explicitly included. Use this flow only
through the private loopback/Tailscale path.

The bot and cockpit can share the same SQLite database. WAL mode and a 15-second
busy timeout allow concurrent reads and short writes. Keep both writing paths
(corrections, budgets, imports) short.

## Testing the recovery release

Safe read-only bot checks in the allowlisted private chat:

- `/start`, `/help`, `/summary`, `/spending`, `/income`, `/compare`, `/trend`,
  `/forecast`, `/subscriptions`, `/rules`, `/merchants`, `/privacy`
- `/ask How much did I spend this month?`
- `/ask Where did most of my money go?`
- `/ask How much budget do I have left?`
- `/ask Did any subscriptions increase in price?`

Write checks (these modify the production database; corrections can be undone):

- `/review` and use the inline Confirm/Dismiss buttons.
- `/budget set food.groceries 150,00 2026-11`, then `/budget food.groceries 2026-11`
  and `/budget list 2026-11`.
- `/correct TRANSACTION_ID food.groceries` and then
  `finance-assistant correct TRANSACTION_ID --undo` on the Pi.
- `/ask Show transactions that have not been categorised.`

Do **not** send a synthetic CSV to the production bot: it would import synthetic
rows into the real ledger. To exercise the upload flow, use a separate test
database and, if needed, a separate test bot token:

```bash
sudo systemctl stop finance-assistant.service
sudo -u financebot env FPA_DATABASE_PATH=/var/lib/finance-assistant/test-recovery.sqlite3   /opt/personal-finance-assistant/.venv/bin/finance-assistant init-db
sudo -u financebot env FPA_DATABASE_PATH=/var/lib/finance-assistant/test-recovery.sqlite3   TELEGRAM_BOT_TOKEN=<test-token> TELEGRAM_ALLOWED_USER_IDS=<your-id>   /opt/personal-finance-assistant/.venv/bin/finance-assistant bot
```

Then restore the production service. The same test database can be served on a
different loopback port for cockpit testing:

```bash
sudo -u financebot env FPA_DATABASE_PATH=/var/lib/finance-assistant/test-recovery.sqlite3   /opt/personal-finance-assistant/.venv/bin/finance-assistant web   --host 127.0.0.1 --port 8001
```

## BotFather settings

No BotFather change is required for the recovery release:

- Keep the bot in private-chat mode with the existing numeric owner allowlist.
- Keep long polling. Do not configure a webhook.
- Do not enable inline mode or group joining.
- Do not add a Web App / Mini App button. The cockpit is a loopback web app, not
  a Telegram-hosted web app; exposing it would require public HTTPS and a new
  authentication/threat-model decision.
- Optional cosmetic step: use `/setcommands` in BotFather to show the command
  menu. This does not enable inline mode or public access.
