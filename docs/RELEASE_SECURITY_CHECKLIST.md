# Release security and privacy checklist

- [x] Repository excludes real exports, databases, backups, and secrets.
- [x] Synthetic parser and privacy tests pass.
- [x] Telegram uses private numeric allowlisting and outbound long polling.
- [x] CSV uploads are private-chat-only, size-limited, temporary, and aggregate-only; group access remains disabled.
- [x] Service uses a dedicated unprivileged account and systemd hardening.
- [x] SQLite backup and separate-file integrity restore were verified.
- [x] Explicit local purge path is documented.
- [x] Review, classification, and correction provenance remain local.
- [x] Disk-space write threshold and safe status output are implemented.
- [ ] Owner chooses and tests encrypted off-device backup retention.
- [ ] Owner verifies OS update and SSH recovery procedure.
- [ ] Owner reviews the live bot after future command changes.

The unchecked items require owner or device-policy decisions and cannot be
completed by repository changes alone.
