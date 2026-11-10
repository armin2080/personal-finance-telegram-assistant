# Owner setup checklist

This checklist is for the repository owner, not the coding agent. Complete it before the first real deployment. Keep every real value on the Pi or in the relevant private GitHub secret store; never put secrets in this file.

## 1. GitHub repository

- [ ] Create a **private** repository named `personal-finance-telegram-assistant`.
- [ ] Keep the repository without an open-source license until a deliberate licensing decision is made.
- [ ] Enable GitHub secret scanning and push protection if available.
- [ ] Require CI to pass before merging changes.
- [ ] Protect `main` from direct pushes once development starts.
- [ ] Never upload database files, logs, screenshots, credentials, or `.env`.

From the extracted project directory, the GitHub CLI route is:

```bash
git init --initial-branch=main
git add .
git commit -m "chore: initial project scaffold"
gh repo create personal-finance-telegram-assistant --private --source=. --remote=origin --push
```

Review `git status` and `git diff --cached --stat` before the first push. Do not push if any local export or database file is staged.

## 2. Raspberry Pi

- [ ] Confirm the board model and RAM. The initial design targets a Pi Zero 2 W class device; do not assume a different board has the same headroom.
- [ ] Confirm OS, architecture, and Python 3.11+ availability.
- [ ] Confirm sufficient free storage and a healthy SD card.
- [ ] Apply OS updates.
- [ ] Create a dedicated unprivileged `financebot` account.
- [ ] Create `/opt/personal-finance-assistant` for code and `/var/lib/finance-assistant` for data.
- [ ] Verify SSH key-based administrative access before changing SSH security settings.

## 3. Telegram

- [ ] Create a dedicated bot with `@BotFather`.
- [ ] Save the token directly into the Pi's private environment file; never paste it into GitHub issues or agent chats.
- [ ] Obtain the numeric Telegram user ID for the owner.
- [ ] Set `TELEGRAM_ALLOWED_USER_IDS` to that numeric ID.
- [ ] Verify the bot responds only to the owner in a private chat.
- [ ] Confirm no webhook is active for this bot. If it was previously connected to Telegram Serverless, disable that integration and remove the old webhook before starting long polling.
- [x] Document uploads accept only CSV files in the allowlisted private chat; group access remains disabled.

## 4. Local import

- [ ] Transfer a fresh booked-transactions export to the Pi using SFTP/SCP/USB.
- [ ] Run `finance-assistant inspect FILE` and inspect counts/date/currency locally.
- [ ] Run dry-run import first.
- [ ] Review any possible duplicates before accepting them.
- [ ] Import only after the preview is understood.
- [ ] Delete the temporary source file according to the owner's retention policy.
- [ ] Do not store the source export in the Git repository.

## 5. Backup and recovery

- [ ] Choose a backup frequency.
- [ ] Create a consistent backup with the app's SQLite backup command.
- [ ] Encrypt any backup before moving it off-device.
- [ ] Store one offline copy.
- [ ] Restore to a separate test database and verify `PRAGMA integrity_check`.
- [ ] Document where the recovery key is stored; do not put it in Git.

## 6. Product decisions intentionally left to the owner

- Display language: English first is the scaffold default; German can be added later.
- Account alias: `primary` is the default non-sensitive label.
- Backup cadence and off-device destination.
- Whether Telegram responses may include merchant names or only aggregate totals.
- [x] Owner approved private CSV statement upload with temporary local processing and aggregate-only replies.
- Whether to investigate FinTS/PSD2 bank synchronisation (default: manual export).
- Whether to investigate optional AI features (default: off).
- Repository license (default: no license granted; private repository).
