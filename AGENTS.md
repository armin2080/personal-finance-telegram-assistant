# AGENTS.md — engineering contract

This file is the binding engineering contract for this repository. It records the
architecture decisions, the data-handling rules, and the standards a change must
meet. Read it before changing code, and update it when a decision changes.

## 1. Start here

Required reading before any change:

1. `README.md`
2. `docs/PROJECT_BRIEF.md`
3. `docs/PRODUCT_SPEC.md`
4. `docs/ARCHITECTURE.md`
5. `docs/IMPORT_SPEC_SPARKASSE.md`
6. `docs/SECURITY_AND_PRIVACY.md`
7. `docs/DATA_MODEL.md`
8. `docs/FINANCIAL_SEMANTICS.md`
9. `docs/CATEGORISATION_RULES.md`
10. `docs/ROADMAP.md`
11. Every relevant decision record in `docs/adr/`

Do not start with a broad refactor. Run the test suite and inspect the current
code first, and state the baseline you measured. Preserve working behaviour
unless a documented defect requires a change.

## 2. What this project is

A single-user, local-first personal finance assistant. It turns German bank
exports into a trustworthy transaction history, explains where money goes,
supports budgets, detects recurring expenses, and answers questions through a
Telegram bot, a CLI, and a loopback web cockpit. It must stay accurate,
auditable, private, low-cost, and maintainable on modest hardware.

It is **not** a multi-tenant fintech platform, a bank, a payment processor, an
investment adviser, a tax adviser, or an autonomous money manager.

## 3. Architecture decisions to preserve

- Python is the application language.
- SQLite is the only supported production database. Target modest hardware,
  including low-memory single-board computers.
- Interfaces are adapters. Business logic must not live in Telegram handlers,
  CLI parsing, HTTP route bodies, or frontend JavaScript.
- Use outbound Telegram long polling. Do not add a public inbound port or a
  webhook.
- The dashboard binds to `127.0.0.1` by default and has no authentication. Do not
  expose it publicly without a separate authentication and threat-model decision.
- Import bank exports locally. Telegram file uploads stay allowlisted and
  private-chat-only.
- The first supported source is the observed Sparkasse semicolon-delimited
  CSV-CAMT V8-style export. It is CSV, not CAMT XML.
- No external LLM, cloud database, analytics SaaS, bank aggregation API, or
  automatic bank login.
- Money is signed integer minor units. Never use binary floats for balances or
  calculations.
- Deterministic rules run before any probabilistic or AI-derived classification.
- Uncertain values stay uncertain. Never fabricate a merchant, category,
  subscription, or transfer classification.

To change one of these, stop and write an ADR in `docs/adr/` covering the reason,
the options considered, privacy implications, migration path, cost, operational
burden, and rollback strategy. Do not silently replace the architecture.

## 4. Data-handling rules — absolute

1. Never commit a real bank export, statement, screenshot, account identifier,
   transaction reference, or database.
2. Never copy a user's CSV into fixtures, examples, docs, logs, issue comments,
   test snapshots, or generated reports.
3. Fixtures must be synthetic and clearly labelled as synthetic.
4. Do not persist `Auftragskonto`, any IBAN, BIC, creditor ID, mandate reference,
   or collection reference. Do not use them as log fields.
5. Do not log transaction descriptions, counterparty names, merchant names,
   amounts, or Telegram message text at INFO level or above.
6. Do not send transaction rows, descriptions, counterparties, or account
   metadata to external APIs or AI systems.
7. Do not ask for, store, or process online-banking passwords, PINs, TANs, card
   PANs, or authentication secrets.
8. Any Telegram statement-upload feature needs a privacy and security review, and
   must stay private-chat-only and allowlisted.
9. Generate exports and backups locally with restrictive file permissions.
   Encrypt anything that leaves the device.
10. Keep a documented data deletion path working.

## 5. Engineering rules

- Keep layers separated: ingestion → application/domain → storage/analytics →
  interface adapters.
- Keep functions narrow, typed, deterministic, and testable.
- Prefer the Python standard library for parsing, date and time, decimal
  arithmetic, SQLite, and CLI work. Add a dependency only with a clear reason and
  a compatibility check against the target platform.
- Do not add pandas, NumPy, Jupyter, Redis, PostgreSQL, Docker, Kubernetes, or an
  LLM runtime.
- Avoid broad exception catches. Errors shown to the user must be safe and
  actionable, and logs must not include the raw input row.
- Use timezone-aware timestamps for events. Use `Europe/Berlin` for user-facing
  month and date boundaries.
- Render formatted currency only at the presentation boundary.
- Database changes require a versioned migration and tests. Never edit an
  already-released migration.
- Do not add a destructive migration without a backup and rollback procedure.
- Every user-facing analytic must state the period used and which
  classifications were included or excluded.
- Keep adapters thin. They call application services and render results; they do
  not contain SQL or categorisation logic.
- Do not print raw transaction details by default. Detailed output must be
  explicitly requested.

## 6. Required workflow

1. Identify the issue or roadmap item and its acceptance criteria.
2. Read the affected modules and tests before editing.
3. State your assumptions rather than inventing missing product decisions.
4. Implement the smallest complete vertical slice.
5. Add tests for normal, boundary, malformed, duplicate, and privacy-sensitive
   cases.
6. Run `ruff check .`, `ruff format --check .`, `mypy src`, and `pytest`.
7. Inspect `git diff` for secrets, sample data, logs, and scope creep.
8. Update the relevant docs, the roadmap status, and the changelog.
9. Report concisely: files changed, behaviour delivered, tests run, known
   limitations, and migration or rollback notes.

Do not treat a task as complete because it compiles. Acceptance criteria and
tests must pass.

## 7. Financial correctness

- No float arithmetic for money.
- Preserve sign: negative booked amounts are debits, positive amounts are
  credits, subject to transfer and refund classification.
- Never count movement between the user's own accounts as spending or income.
  The exclusion is keyed on the category so a stale classification cannot change
  the total.
- Do not treat every incoming credit as salary or every debit as consumption.
- Link refunds to the original merchant or category when evidence exists.
  Otherwise keep them separate and uncertain.
- Categories are separate from transaction direction and classification.
- Recurrence needs repeated evidence and a confidence level. One transaction is
  not a subscription.
- Forecasts must disclose assumptions, the observation window, and uncertainty.
  Do not extrapolate from sparse data.
- A user's correction outranks generic rules. Record the source and effective
  date of the correction.
- Every total must be reproducible from stored transactions and versioned rules.

## 8. Telegram safety

- Enforce the allowlist with numeric Telegram user IDs, not usernames.
- Accept private chats only. Ignore all other users and group chats without
  revealing configuration.
- Fail closed when the allowlist is empty or malformed.
- Never echo arbitrary user text or raw file content into chat.
- Do not enable inline mode, group access, public commands, or file upload
  without an explicit decision and a privacy review.
- Keep output concise. Avoid dumping full transaction lists or references.
- Keep the bot token out of source control and rotate it immediately if exposed.

## 9. Operational constraints

- Be conservative with memory, CPU, disk writes, and background jobs.
- One Python process, one SQLite file, systemd units. Do not require Docker.
- Long polling means outbound HTTPS only. Do not open inbound firewall ports.
- Run under a dedicated unprivileged OS account.
- Keep the database directory at `0700` and the database and environment file at
  `0600`.
- Use SQLite's online backup API. Never copy a live WAL database with a file copy.
- Verify restore, not just backup creation.
- Log operational events only. Never log financial content.

## 10. What not to do

- Do not replace the chosen architecture with a serverless platform without an
  ADR.
- Do not put a generic AI prompt in front of the deterministic correction and
  rules layer.
- Do not scrape online banking pages or automate browser login.
- Do not claim a merchant or transaction is identified with certainty when it is
  only a candidate.
- Do not make real bank data a test requirement. Build synthetic fixtures and, if
  needed, describe an optional local-only manual smoke test.
- Do not describe financial output as guaranteed, personalised, or professional
  advice.

## 11. Definition of done

A change is done only when:

- its acceptance criteria are met and stated;
- unit and integration tests cover success and failure cases;
- financial arithmetic is integer-minor-unit safe;
- privacy requirements are satisfied and tested where practical;
- errors are actionable without leaking personal data;
- docs and changelog are updated;
- CI passes; and
- a contributor can run the documented command or workflow from a clean checkout.
