# Roadmap

Status values: `DONE`, `IN PROGRESS`, `NOT STARTED`, `BLOCKED`. Code in this scaffold is a foundation, not a claim that all milestones are complete.

## M0 — Repository and project contract

Status: **DONE**

- [x] Establish Python + SQLite + Telegram long-polling architecture.
- [x] Document scope, threat model, data model, and execution rules.
- [x] Add CI, synthetic fixture, and initial tests.
- [x] Owner repository is private and the verified foundation is pushed.
- [x] Target Pi OS, Python version, available storage, and memory verified.

Exit: clean checkout installs, tests, and CI passes; private repository and no real data in Git.

## M1 — Reliable local import pipeline

Status: **DONE**

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

Status: **DONE**

- [x] Define category registry and locale display labels.
- [x] Implement separate classification/category/provenance/confidence fields.
- [x] Add merchant entity/alias tables and merchant provenance/confidence.
- [x] Add transaction review queue.
- [x] Persist transaction-level merchant corrections; ensure they outrank aliases.
- [x] Reprocessing preserves user corrections.
- [x] Support deterministic refund and own-transfer classification for later review.

Exit: user can correct a candidate and see the correction consistently applied to future matching transactions.

## M3 — Analytics and monthly reports

Status: **DONE**

- [x] Period selection and month-over-month calculations.
- [x] Category totals and uncategorised/uncertain totals.
- [x] Separate income, spending, transfers, refunds, fees.
- [x] Reconcile totals against imported ledger totals.
- [x] Add `/spending`, `/income`, and `/compare` with explanations.

Exit: every figure is reproducible from transactions and displays date range plus inclusion/exclusion rules.

## M4 — Budgets and alerts

Status: **DONE**

- [x] CRUD budgets by month/category.
- [x] Compute actual spend using classified expense/category only.
- [x] Threshold alerts with user-controlled settings and rate limits.
- [x] Forecast month-end budget only after sufficient observations.
- [x] Add `/budget` and alert preferences.

Exit: no transfer or unknown-category row silently consumes a category budget.

## M5 — Recurring payment detection

Status: **DONE**

- [x] Candidate grouping by merchant, amount range, and cadence.
- [x] Require at least three observations for subscription confidence unless user explicitly marks one.
- [x] Separate stable subscription from irregular recurring payments.
- [x] User confirm/dismiss/edit.
- [x] Add `/subscriptions`.

Exit: all detected recurring items are explainable and labelled as candidates until user-confirmed.

## M6 — Insights, forecasts, and cockpit foundation

Status: **IN PROGRESS**

- [x] Trend and anomaly detection with transparent baselines.
- [x] Savings/budget review prompts based only on the user's data and budgets.
- [x] Conservative cash-flow forecast with sparse-data warning.
- [x] Add opt-in natural-language questions over locally calculated aggregates.
- [x] External LLM remains disabled pending explicit owner approval, data minimisation, provider review, and a kill switch.
- [x] Add a loopback-only dashboard/API over the existing application services.
- [x] Add structured deterministic insights with evidence transaction IDs.
- [ ] Complete review actions, category management, and full dashboard navigation.

Exit: no unsupported advice, unexplained forecasts, or external data egress.

## M6.1 — Personal Finance Cockpit extension

Status: **IN PROGRESS**

- [x] Baseline implementation audit recorded in `docs/IMPROVEMENT_AUDIT.md`.
- [x] Expand movement types, payment channels, review state, and exact splits.
- [x] Add overview, trends, budgets, recurring, insights, and transaction API
  sections.
- [x] Add merchant rankings and weekly trend API data.
- [x] Add responsive local dashboard and local development command.
- [x] Add Telegram upload preview/confirmation flow.
- [ ] Add independent 12-month oracle and end-to-end acceptance journeys.
- [ ] Add browser visual/accessibility inspection.

The dashboard remains loopback-only until a separate authentication and
threat-model decision approves any remote or Mini App exposure.

## M7 — Optional banking automation investigation

Status: **DONE** — investigation complete; implementation intentionally deferred

- [x] Compare continued manual CSV, FinTS/HBCI libraries, and licensed PSD2 providers.
- [x] Document regional compatibility, authentication/TAN, service-term, and cost verification requirements.
- [x] Never automate browser login or store online banking credentials.
- [x] Write separate proposals, an ADR, and privacy boundaries before implementing.

Exit: no automated sync is enabled without a clear consent/security/cost decision.

## M8 — Production hardening

Status: IN PROGRESS

- [x] Versioned migrations and tested rollback.
- [x] SQLite online backup and separate-file integrity restore verified.
- [x] Hardened systemd unit and dedicated user provisioned on the target Pi.
- [x] Health/status command with no financial details.
- [x] Disk-space monitoring and graceful read-only failure when storage is low.
- [ ] Dependency review and reproducible environment.
- [x] Pi reboot/restart smoke test.
- [x] Privacy/security release checklist documented; owner-only checks remain explicitly marked.

Exit: owner can deploy, recover, update, back up, restore, and delete local data without developer intervention. Encrypted off-device backup and owner-only release checks remain.
