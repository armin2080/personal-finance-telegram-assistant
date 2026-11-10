# Raspberry Pi deployment and operations

## Target profile

The initial target is a small Raspberry Pi device, potentially a Zero 2 W (512 MB RAM). The application should remain a single lightweight Python process with SQLite. Do not run an LLM, PostgreSQL, Redis, Docker engine, web dashboard, or large data-science stack on this device.

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
7. Do not upload the file to Telegram or GitHub.

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
- [ ] Disk-space threshold/monitoring configured.
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
