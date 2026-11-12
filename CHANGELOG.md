# Changelog

## 0.2.0 — Recovery release

- Restored oracle-exact financial totals: coffee is no longer a bank fee,
  consumer categories are deterministic, and uncategorised spending stays in
  total expenditure.
- Added split-aware reporting through the `transaction_flows` view; budgets,
  merchant rankings, trends, forecasts and reconciliation now respect splits.
- Defined reversal/refund arithmetic and linked-offset behaviour; unlinked
  reversals remain outside net cash flow and visible in reconciliation.
- Made possible-duplicate imports resumable (`incomplete` → append on explicit
  acceptance) while preserving exact-file idempotency.
- Made schema upgrades atomic and added v4/v5→v6 migration coverage, including
  failure rollback and retry.
- Made import undo split-safe and foreign-key clean.
- Added transaction review/correction/note/split/link/undo controls, merchant
  entities and aliases, structured rules, and learn-from-correction.
- Added budget CRUD, pace/projection, alert thresholds and explicit uncategorised
  spending disclosure.
- Replaced the `/ask` substring matcher with a structured intent/entity parser
  covering spending, income, categories, merchants, dates, comparisons, budgets,
  savings, recurring payments and price changes.
- Rebuilt the dashboard with nine navigable sections, interactive SVG charts,
  URL state, click drill-down, mobile transaction cards, health status and clean
  error/empty/loading states.
- Added insight coverage for largest categories, changes, merchant
  concentration, unusual one-offs, income changes, fixed/discretionary spending,
  budget pace and recurring price changes.
- Added 47 recovery regression tests (129 total) and documented the recovery
  baseline, semantics, rules and acceptance evidence.

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
- Added conservative budget and cash-flow forecasts, trend/anomaly analytics, local aggregate questions, disk-capacity safeguards, and AI/bank-sync investigation proposals with no integrations enabled.
- M0–M5 are now complete; M6 remains local-only with external AI disabled, M7 investigation is documented, and M8 operational safeguards are in progress.
- Added owner-approved private CSV document uploads with temporary local processing, duplicate-aware import, aggregate analysis replies, and automatic source cleanup.
- Added transaction movement types, payment-channel and review-state persistence, exact transaction splits, deterministic overview metrics, evidence-backed insights, and a loopback-only dashboard/API.
- Added reusable merchant-ranking and Monday-based weekly-trend analytics with dashboard API coverage.
