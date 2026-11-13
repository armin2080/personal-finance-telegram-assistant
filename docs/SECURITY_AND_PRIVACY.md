# Security and privacy requirements

## Threat model

This project handles highly sensitive personal financial activity. Treat any database and source export you create as private, regardless of whether the repository is public. Primary threats include accidental Git commits, leaked bot tokens, unauthorised Telegram users, logs containing transaction details, insecure backups, a compromised host account, and future dependencies sending data externally.

## Trust boundaries

1. **Bank export → local importer:** untrusted input. Validate encoding, headers, row count, dates, currency, and amounts. Never execute or interpret cell content as code.
2. **Local application → SQLite:** trusted local process; enforce narrow persistence fields and file permissions.
3. **Telegram user → bot:** untrusted updates. Require private chat and a numeric user ID allowlist; fail closed.
4. **Bot → Telegram infrastructure:** outbound message content is disclosed to Telegram as part of normal Bot API operation. Keep responses minimal and never send raw statements.
5. **Host → internet:** outbound HTTPS only, for the Telegram Bot API. No telemetry, AI, or banking API calls.
6. **Backup destination:** treat it as sensitive as the primary database. Encrypt before off-device transfer.

## Mandatory controls

### Repository and secrets

- `.gitignore` excludes `.env`, database files, backups, exports, statements, and logs.
- Never paste a real token, password, PIN, TAN, IBAN, or transaction description into code, tests, issues, pull requests, CI, or agent prompts.
- Use GitHub secret scanning and push protection where available.
- Use `.env.example` only for empty placeholders; the actual `.env` must be mode `0600`.
- Rotate any secret that appears in Git history; deleting the latest file alone is insufficient.

### Data minimisation

- Do not persist source account IBAN (`Auftragskonto`), counterparty IBAN, BIC, creditor ID, mandate reference, or collection reference.
- Source references may be used transiently to derive a digest for deduplication; raw values must be discarded.
- Strip obvious IBAN/card-number patterns from stored purpose/counterparty text.
- Do not store original CSV files by default.
- Do not log transaction text, party, merchant, amount, or Telegram message content.
- A debug mode must never dump full rows. Use synthetic fixtures for debugging.

### Telegram

- The bot must use a hard allowlist of numeric Telegram user IDs.
- Only private chats are accepted. Group chats and all non-allowlisted users are ignored.
- An empty allowlist is a startup error.
- Long polling only; no public webhook/listener in the MVP.
- CSV statement upload is limited to the allowlisted private chat, a 10 MiB
  configurable limit, temporary local processing, and aggregate-only replies.
  The source file is deleted after processing; non-CSV documents, groups, and
  non-allowlisted users are rejected.
- Commands return concise summaries, not full transaction histories by default.
- Do not treat Telegram as an encrypted private storage system. Bot messages are handled by Telegram's cloud Bot API.

### Host operating system

- The starter SQLite database is **not application-encrypted**. File permissions (`0600`) are access controls, not encryption. Consider full-disk encryption or an encrypted data volume when physical access to the host or its storage is in scope; document boot/unlock and recovery trade-offs before enabling it.
- Dedicated unprivileged account for the service.
- Database directory `0700`, database and environment file `0600` where supported.
- SSH key-based administration; disable password login only after verifying key access and a recovery path.
- Keep OS security updates current.
- No inbound ports are needed for the bot. Do not forward ports on the router.
- Use systemd restrictions from the sample service and adapt paths/account before deployment.
- Use encrypted backups before copying them off-device. Verify restore periodically.

### Dependencies and supply chain

- Keep runtime dependencies minimal.
- Pin/update dependencies through reviewed changes; use Dependabot for proposals, not blind auto-merges.
- Check Python and native-wheel compatibility on the target OS and CPU architecture before adding compiled packages.
- No dependency may make an external network request with financial data unless the maintainer explicitly approves it and the privacy design is updated.

## Data lifecycle

1. **Collection:** the user exports booked transactions and either sends a supported CSV in the allowlisted private Telegram chat or transfers it to the host.
2. **Processing:** uploaded files are downloaded into a `0700` temporary directory, parser reads rows in memory, bank identifiers are ignored, and obvious identifiers in memo/counterparty fields are scrubbed.
3. **Persistence:** only canonicalised transaction data, import metadata, and derived digests are stored in SQLite; the uploaded source is deleted in a `finally` cleanup block.
4. **Use:** local analytics and concise Telegram summaries.
5. **Backup:** consistent SQLite backup; encrypted before off-device storage.
6. **Deletion:** use the user-confirmed local purge command after creating any required backup. This removes the application database and SQLite sidecars; backups under app control must be handled separately. A secure deletion promise cannot be made for wear-levelled flash storage or managed storage.

## Incident response

If the bot token is exposed: revoke it with `@BotFather`, update the private environment file, restart the service, inspect Git history/logs, and do not merely delete the current line.

If the database or a backup is exposed: stop the service, preserve incident evidence, rotate secrets, assess which fields were retained, restore from a known-good protected backup if required, and document the incident internally.

## Release gate

Do not treat a deployment as production-ready until allowlist tests, secret scanning, data minimisation tests, service hardening, backup-and-restore verification, and a documented data deletion procedure have passed.
