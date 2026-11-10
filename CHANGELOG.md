# Changelog

## 0.1.0 — Initial project foundation

- Defined local-first Python, SQLite, Raspberry Pi, and Telegram long-polling architecture.
- Added binding agent instructions, project/product requirements, architecture, data model, privacy and operations documentation.
- Added a parser for the observed Sparkasse CSV-CAMT V8-style layout.
- Added local inspect/import/backup CLI commands, duplicate-aware SQLite persistence, and a tested application-service layer for month summaries.
- Added canonical Sparkasse header aliases, safe row/column validation errors, and aggregate import previews.
- Added database-aware duplicate review with safe row/reason reports, explicit weak-duplicate acceptance, and transactional import undo.
- Added canonical merchant entities, exact normalised aliases, merchant provenance/confidence, and transaction-level correction precedence.
- Added deterministic classification/category provenance, refund candidates, and versioned user classification rules.
- Added a code-level category registry and audited user classification corrections for transfer/refund review.
- Added explainable period reports, thin Telegram spending/income/comparison commands, and safe command error references.
- Added classified-expense budget status and recurring-payment candidates requiring repeated evidence and user confirmation.
- Validated the project on Python 3.14.4 and Ubuntu 26.04.1 LTS (Linux 7.0.0-43-generic, x86_64) with Ruff, mypy, and pytest.
- Added a private allowlisted Telegram bot skeleton with `/start`, `/help`, `/summary`, and `/privacy`.
- Added synthetic-only fixtures, 30 automated tests, GitHub Actions CI, issue templates, and a hardened systemd example.
- Added read-only Telegram budget and repeated-payment candidate commands with conservative limits and explicit review wording.
- Verified the target Raspberry Pi deployment with Python 3.11.2, Pi-native tests, a dedicated service account, restrictive state/config permissions, systemd validation, and SQLite backup integrity restoration.
- Activated the owner-configured Telegram service, verified outbound Bot API reachability, reboot recovery, private listeners/config permissions, and a post-reboot live backup.
- Completed the owner-side Telegram smoke test for `/start` and `/summary`; the empty summary is expected before local import.
- Added local review/status commands and an explicit, documented database deletion path.
- Added reconciliation aggregates, review queue Telegram count, rate-limited budget alerts, and recurring candidate confirm/dismiss decisions.
- Validated the owner-provided CSV on the Pi with aggregate inspect/dry-run output only; the temporary source file was removed and the deployed 62-test suite remains green.
