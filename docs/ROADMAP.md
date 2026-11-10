# Roadmap

Status values: `DONE`, `IN PROGRESS`, `NOT STARTED`, `BLOCKED`. Code in this scaffold is a foundation, not a claim that all milestones are complete.

## M0 — Repository and project contract

Status: **IN PROGRESS**

- [x] Establish Python + SQLite + Telegram long-polling architecture.
- [x] Document scope, threat model, data model, and execution rules.
- [x] Add CI, synthetic fixture, and initial tests.
- [ ] Owner creates a private GitHub repository and pushes the scaffold.
- [x] Target Pi OS, Python version, available storage, and memory verified.

Exit: clean checkout installs, tests, and CI passes; private repository and no real data in Git.

## M1 — Reliable local import pipeline

Status: **IN PROGRESS**

- [x] Parse observed semicolon CSV, quoted values, UTF-8 BOM / cp1252 fallback.
- [x] Parse German date and EUR amount formats.
- [x] Ignore bank IBAN/BIC/creditor IDs and scrub obvious IBAN/card patterns.
- [x] Candidate extraction for PayPal and card descriptors.
- [x] Dry-run preview and exact-file idempotency.
- [x] Aggregate dry-run report with date, currency, direction, payment-type, and dedupe counts.
- [x] Add transaction-specific dedupe conflict review CLI report.
- [x] Add import rollback/undo with correction dependency protection.
- [x] Test against the owner-provided local file on the Pi; never upload it to GitHub.
- [x] Verify atomic rollback on any database write failure.

Exit: 100% amount/date correctness on synthetic tests and manually reconciled local sample; no silent duplicate loss.

## M2 — Canonical categories and correction memory

Status: IN PROGRESS

- [x] Define category registry and locale display labels.
- [x] Implement separate classification/category/provenance/confidence fields.
- [x] Add merchant entity/alias tables and merchant provenance/confidence.
- [x] Add transaction review queue.
- [x] Persist transaction-level merchant corrections; ensure they outrank aliases.
- [x] Reprocessing preserves user corrections.
- [x] Support deterministic refund and own-transfer classification for later review.

Exit: user can correct a candidate and see the correction consistently applied to future matching transactions.

## M3 — Analytics and monthly reports

Status: IN PROGRESS

- [x] Period selection and month-over-month calculations.
- [x] Category totals and uncategorised/uncertain totals.
- [x] Separate income, spending, transfers, refunds, fees.
- [x] Reconcile totals against imported ledger totals.
- [x] Add `/spending`, `/income`, and `/compare` with explanations.

Exit: every figure is reproducible from transactions and displays date range plus inclusion/exclusion rules.

## M4 — Budgets and alerts

Status: IN PROGRESS

- [x] CRUD budgets by month/category.
- [x] Compute actual spend using classified expense/category only.
- [x] Threshold alerts with user-controlled settings and rate limits.
- [ ] Forecast month-end budget only after sufficient observations.
- [x] Add `/budget`; alert preferences remain.

Exit: no transfer or unknown-category row silently consumes a category budget.

## M5 — Recurring payment detection

Status: IN PROGRESS

- [x] Candidate grouping by merchant, amount range, and cadence.
- [x] Require at least three observations for subscription confidence unless user explicitly marks one.
- [x] Separate stable subscription from irregular recurring payments.
- [x] User confirm/dismiss/edit.
- [x] Add `/subscriptions`.

Exit: all detected recurring items are explainable and labelled as candidates until user-confirmed.

## M6 — Insights and forecasts

Status: NOT STARTED

- [ ] Trend and anomaly detection with transparent baselines.
- [ ] Savings/budget recommendations based only on the user's data and preferences.
- [ ] Conservative cash-flow forecast with confidence interval and sparse-data warning.
- [ ] Add opt-in natural-language questions over locally calculated aggregates.
- [ ] External LLM only after explicit owner approval, data minimisation, provider review, and a kill switch.

Exit: no unsupported advice, unexplained forecasts, or external data egress.

## M7 — Optional banking automation investigation

Status: NOT STARTED — intentionally deferred

- [ ] Compare continued manual CSV, FinTS/HBCI libraries, and licensed PSD2 providers.
- [ ] Verify regional Sparkasse compatibility, authentication/TAN flows, service terms, and costs.
- [ ] Never automate browser login or store online banking credentials.
- [ ] Write an ADR and privacy review before implementing.

Exit: no automated sync is enabled without a clear consent/security/cost decision.

## M8 — Production hardening

Status: IN PROGRESS

- [x] Versioned migrations and tested rollback.
- [x] SQLite online backup and separate-file integrity restore verified.
- [x] Hardened systemd unit and dedicated user provisioned on the target Pi.
- [x] Health/status command with no financial details.
- [ ] Disk-space monitoring and graceful read-only failure when storage is low.
- [ ] Dependency review and reproducible environment.
- [x] Pi reboot/restart smoke test.
- [ ] Privacy/security release checklist.

Exit: owner can deploy, recover, update, back up, restore, and delete local data without developer intervention. Encrypted off-device backup, disk-space handling, and the final privacy/security release checklist remain.
