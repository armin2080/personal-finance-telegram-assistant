# Roadmap

Status values: `DONE`, `IN PROGRESS`, `NOT STARTED`, `DEFERRED`.

## Shipped

### M0 — Project foundation

Status: **DONE**

- [x] Python application with SQLite storage and Telegram long polling.
- [x] Scope, threat model, data model, and engineering rules documented.
- [x] Continuous integration, synthetic fixtures, and automated tests.

### M1 — Local import pipeline

Status: **DONE**

- [x] Parse the observed semicolon-delimited Sparkasse export, including quoted
  values, UTF-8 BOM, and Windows-1252 fallback.
- [x] Parse German date and EUR amount formats into integer minor units.
- [x] Ignore bank IBAN/BIC/creditor identifiers and scrub IBAN and card patterns
  from stored memo text.
- [x] Extract merchant candidates from card descriptors and PayPal pass-through
  memos.
- [x] Dry-run preview, exact-file idempotency, and resumable possible-duplicate
  review.
- [x] Transactional import undo with correction dependency protection.
- [x] Atomic rollback on any write failure.

### M2 — Categories, merchants, and correction memory

Status: **DONE**

- [x] Category registry with a deterministic classifier and recorded provenance.
- [x] Separate classification, category, source, and confidence fields.
- [x] Merchant entities, exact-normalised aliases, and default categories.
- [x] Review queue with confirm, dismiss, correct, note, split, and link actions.
- [x] User corrections outrank aliases and rules, and survive reprocessing.
- [x] Refund, reversal, and own-account transfer handling kept explicit.

### M3 — Analytics and reporting

Status: **DONE**

- [x] Period selection and month-over-month comparison.
- [x] Category totals, plus separate uncategorised and uncertain totals.
- [x] Income, spending, transfers, refunds, fees, cash, and savings reported
  separately.
- [x] Split-aware aggregation through a single SQL view.
- [x] Reconciliation of period totals against stored transactions.

### M4 — Budgets

Status: **DONE**

- [x] Monthly per-category budgets with create, edit, delete, and list.
- [x] Spent, remaining, percentage, elapsed pace, and projected month-end spend.
- [x] Explicit disclosure when uncategorised spending makes a report incomplete.
- [x] Configurable early-warning thresholds, rate-limited.

### M5 — Recurring payments

Status: **DONE**

- [x] Candidate grouping by merchant, amount stability, and cadence.
- [x] At least three observations required before a candidate is proposed.
- [x] Confirmed, probable, and possible states, with user confirm/dismiss.
- [x] Recurring price-change detection with old and new amounts and evidence.

### M6 — Insights, forecasts, and cockpit

Status: **DONE**

- [x] Trend and anomaly detection with transparent baselines.
- [x] Conservative cash-flow forecast that refuses to extrapolate sparse data.
- [x] Deterministic natural-language questions over local aggregates.
- [x] Loopback-only dashboard and API over the application services.
- [x] Structured insights with supporting transaction identifiers.
- [x] Nine navigable cockpit sections with interactive charts and drill-down.

### M7 — Optional banking automation

Status: **DEFERRED** — investigation complete, implementation intentionally not started

- [x] Compare continued manual CSV import, FinTS/HBCI libraries, and licensed
  PSD2 aggregators.
- [x] Document compatibility, authentication/TAN, service-term, and cost
  verification requirements.
- [x] Record that browser login automation and stored banking credentials remain
  out of scope.

### M8 — Operational hardening

Status: **DONE**

- [x] Versioned migrations with atomic rollback and retry.
- [x] SQLite online backup and a documented, tested restore procedure.
- [x] Hardened systemd example units for the bot and the cockpit.
- [x] Privacy-safe status command and graceful read-only failure when storage is
  low.
- [x] Dependency review and reproducible environment.

### M9 — Mobile and packaging

Status: **DONE**

- [x] Installable progressive web app with manifest, maskable icons, and
  theme colour.
- [x] App-shell service worker that never caches API responses.
- [x] Bottom tab navigation, safe-area handling, and card-based mobile
  transactions.
- [x] Brand assets and an in-app install prompt.

## Next

Status: **NOT STARTED**

- [ ] Authentication and session handling for the cockpit, or a documented
  decision that it stays a loopback-only single-user tool.
- [ ] Onboarding wizard that takes a new user from empty database to first
  insight without a terminal.
- [ ] Additional import formats: ISO 20022 CAMT XML, MT940, and credit-card or
  PayPal activity exports.
- [ ] Scheduled jobs: delivered budget alerts, periodic price-change notices,
  and a backup schedule with retention.
- [ ] Balance reconciliation using the statement balance column, so a user can
  prove an import was complete.
- [ ] Data export to CSV or JSON and an in-app deletion path.
- [ ] User-defined categories with grouping and archiving.
- [ ] Rule dry-run showing how many stored transactions a rule would change.
- [ ] Transaction history view over `audit_events` so every automatic label is
  explainable after the fact.
- [ ] Distribution: one-command installer and versioned upgrade path.
- [ ] German-language interface for German bank data.
