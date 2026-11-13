# Architecture

## Decision summary

**One Python application, one SQLite database, one Telegram bot process, one user.** Import data locally first. Telegram handlers are thin adapters. No separate cloud compute or database service is required; Telegram still processes bot updates and replies through its Bot API.

```text
Sparkasse CSV file (local)
          |
          v
[Source adapter: sparkasse_csv_camt_v8]
          |
          v
[Validation + normalisation + PII minimisation]
          |
          v
[Canonical transaction + merchant candidate + dedupe metadata]
          |
          v
[Application services]
    |       |        |        |
    v       v        v        v
  SQLite  Rules   Analytics  Review workflow
    ^                          |
    |                          v
    +--------------------- User corrections
                               |
                               v
                       Merchant/category memory

Telegram private chat <-> thin bot adapter <-> application services <-> SQLite
Local CLI -------------> same application services
Loopback web dashboard -> same application services
```

## Layers and responsibilities

### Ingestion

- Understand source-specific headers, encodings, quoting, dates, decimal formats, and source references.
- Validate every required field.
- Convert source rows to canonical domain records.
- Strip unused bank identifiers before data reaches persistence.
- Extract a merchant candidate conservatively; never infer a category here.

### Domain/application

- Define transaction classifications, category taxonomy, confidence, and provenance.
- Apply user corrections before generic rules.
- Calculate totals using integer minor units.
- Decide which records qualify for expenses, income, transfers, refunds, and recurring-payment analysis.
- Provide use-case functions to both CLI and Telegram.

### Storage

- SQLite only for the MVP.
- Explicit schema version and migrations (current schema v6). Migrations run in
  one explicit transaction and roll back completely on failure.
- Transactional import batches with an explicit `pending`/`incomplete`/
  `completed` lifecycle for possible-duplicate review.
- A split-aware `transaction_flows` view expands split parents; all analytics,
  budgets, forecasts and reconciliation read that view so a parent is never
  double-counted.
- Indexed queries by booking date, merchant, category, and classification.
- Use SQLite online backup API for consistent backups.

### Interfaces

- CLI: import, inspect, backup, database maintenance, recovery.
- Telegram: user commands and concise results. No SQL in handlers.
- Web dashboard: local FastAPI adapter serving a responsive static cockpit. It
  binds to loopback by default, exposes read and user-management endpoints over
  the application services, and performs no independent financial calculations.
  The presentation uses dependency-light HTML/CSS/JS with interactive SVG charts;
  financial values, shares and projections are computed server-side. The same
  adapter offers a mobile-first CSV import preview/commit flow; uploads are parsed
  locally, previews expire, and the source file is not retained after the request
  or sent to Telegram. The shell is an installable PWA with a manifest, an
  offline app-shell service worker that never caches `/api/`, and a bottom tab
  bar below 880 px.
- A future Telegram Mini App requires a separate authentication and threat-model
  decision; it must not be inferred from the local dashboard.

## Runtime decision: self-hosted Python over Telegram Serverless

Telegram Serverless runs JavaScript ES modules in Telegram's V8 runtime with its own database interface. It is not a Python host, and it would move transaction storage to a hosted service. Running the application on a self-hosted Linux machine keeps the implementation in Python and keeps financial data on hardware the user controls. The Bot API supports long polling; polling and webhooks are mutually exclusive, so this application must not run a webhook at the same time.

For the first release, long polling is preferable to a webhook: the host needs outbound HTTPS connectivity only, with no public inbound listener. The process can run under systemd. A bot token and at least one allowlisted numeric user ID are required.

## Data flow for importing a CSV

1. Read file bytes; calculate a SHA-256 file digest for exact-file idempotency.
2. Decode UTF-8 with BOM support; fallback to Windows-1252 only if UTF-8 decoding fails.
3. Parse semicolon-delimited quoted CSV.
4. Validate the observed header signature.
5. Parse booking date and optional value date.
6. Parse EUR decimal using `Decimal`; convert to integer cents.
7. Read booking text, purpose, and counterparty; ignore IBAN/BIC and other bank identifiers.
8. Scrub obvious IBAN/card-number patterns in stored purpose/counterparty text.
9. Derive a merchant candidate from counterparty/purpose.
10. Build a reference-backed or content-only duplicate key.
11. Preview, then commit one transaction batch atomically.

## Duplicate strategy

- Exact-file hash: importing identical file bytes again is a no-op.
- Reference-backed transaction: a digest derived from the transaction-specific end-to-end reference + date + amount + currency gives a stronger dedupe key. Mandate references are not treated as unique booking IDs. The source reference itself is not persisted.
- Content-only transaction: a digest of normalised fields is a weak match. Two legitimate same-day identical purchases can be identical, so the app must flag the match as a possible duplicate and require an explicit decision. It must never silently discard or auto-merge weak matches.
- Do not rely on row numbers for cross-export deduplication; row order changes when the date range changes.

## Canonical transaction fields

See `DATA_MODEL.md`. Keep source-specific metadata in the adapter, not in the domain model, unless a real use case justifies it.

## Analytics rules

- Expense/income/transfer/refund is a classification, not a category.
- Category is a separate label, e.g. `food.groceries` or `housing.rent`.
- Exclude transfer candidates from expense/income totals until reviewed.
- Refunds should offset only a matching category when confidently linked; otherwise show separately.
- “Uncategorised” is a valid state. Uncategorised spending remains in total
  expenses and is disclosed wherever category totals or budgets are shown.
- Every summary includes date bounds and inclusion/exclusion logic.
- Split allocations are expanded before aggregation; the parent amount is never
  counted again.
- Unlinked reversals are kept outside net cash flow but shown in reconciliation.
  Linked refunds/reversals offset the original expense instead of being counted
  twice.
- Net cash flow is `income + refunds − expenses − fees`. Transfers, cash
  withdrawals, savings movements and unlinked reversals are excluded.

## Resilience and observability

- SQLite writes are short and transactional.
- Telegram retries must not duplicate imports or state changes.
- Keep structured logs to operational metadata only (startup, shutdown, errors, import batch ID and counts). Do not log rows.
- A crash during import must leave either the entire transaction batch committed or none of it.
- Database backup and restore must be tested before production deployment.
