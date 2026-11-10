# Architecture

## Decision summary

**One Python application, one SQLite database, one Telegram bot process, one owner.** Import data locally first. Telegram handlers are thin adapters. No separate cloud compute or database service is required; Telegram still processes bot updates and replies through its Bot API.

```text
Sparkasse CSV file (local on Pi)
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
- Explicit schema version and migrations.
- Transactional import batches.
- Indexed queries by booking date, merchant, category, and classification.
- Use SQLite online backup API for consistent backups.

### Interfaces

- CLI: import, inspect, backup, database maintenance, recovery.
- Telegram: user commands and concise results. No SQL in handlers.
- Web dashboard: local read-only FastAPI adapter serving a responsive static
  presentation layer. It binds to loopback by default and has no independent
  financial calculations.
- A future Telegram Mini App requires a separate authentication and threat-model
  decision; it must not be inferred from the local dashboard.

## Runtime decision: Raspberry Pi over Telegram Serverless

Telegram Serverless currently runs JavaScript ES modules in Telegram's V8 runtime with its own database interface. It is not a Python host. The Pi lets the application remain in Python and keep transaction storage local. The Bot API supports long polling; polling and webhooks are mutually exclusive, so this app must not run a webhook at the same time.

For the first release, long polling is preferable to a webhook: the Pi only needs outbound HTTPS connectivity and no public inbound listener. The service can run under systemd. A bot token and one allowlisted user ID are required.

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
- “Uncategorised” is a valid state.
- Every summary includes date bounds and inclusion/exclusion logic.

## Resilience and observability

- SQLite writes are short and transactional.
- Telegram retries must not duplicate imports or state changes.
- Keep structured logs to operational metadata only (startup, shutdown, errors, import batch ID and counts). Do not log rows.
- A crash during import must leave either the entire transaction batch committed or none of it.
- Database backup and restore must be tested before production deployment.
