# AGENTS.md — mandatory execution contract

You are the senior engineer responsible for completing this repository. Treat this document as a binding project instruction, not optional advice. The product owner is the decision-maker for product scope, privacy trade-offs, and any change to the decisions below.

## 1. Start here — required reading order

Before writing code, read these files in order:

1. `README.md`
2. `docs/PROJECT_BRIEF.md`
3. `docs/PRODUCT_SPEC.md`
4. `docs/ARCHITECTURE.md`
5. `docs/IMPORT_SPEC_SPARKASSE.md`
6. `docs/SECURITY_AND_PRIVACY.md`
7. `docs/DATA_MODEL.md`
8. `docs/ROADMAP.md`
9. `docs/AGENT_EXECUTION_PLAN.md`
10. Every relevant decision record in `docs/adr/`

Do not start with a broad refactor. First run the existing test suite and inspect the current code. Preserve working behaviour unless a documented defect requires a change.

## 2. Product mission

Build a personal, single-owner finance assistant that turns German bank exports into a trustworthy transaction history, explains where money goes, supports budgets, detects recurring expenses, and answers concise questions through Telegram. It must be accurate, auditable, private, low-cost, and maintainable on a small Raspberry Pi.

The product is **not** a multi-tenant fintech platform, bank, payment processor, investment adviser, tax adviser, or autonomous money manager.

## 3. Architecture decisions you must preserve

- Python is the application language.
- The first production target is a Raspberry Pi-class single-board computer.
- SQLite is the only production database for the MVP.
- The Telegram bot is a transport/interface adapter; business logic must not live inside Telegram handlers.
- Use outbound Telegram long polling. Do not expose a public inbound port or configure a webhook for the initial release.
- Import bank exports locally using the CLI. Do not enable Telegram file uploads by default.
- The first supported bank source is the observed Sparkasse semicolon-delimited CSV-CAMT V8-style export. It is CSV, not CAMT XML.
- No external LLM, cloud database, analytics SaaS, bank aggregation API, or automatic bank login in the MVP.
- Use integer minor units for money. Never use binary floats for balances or calculations.
- Use deterministic rules before probabilistic or AI-derived classification.
- Uncertain values must remain uncertain. Never fabricate a merchant, category, subscription, or transfer classification.

If you believe one of these decisions must change, stop and write an ADR in `docs/adr/` describing the reason, options, privacy implications, migration path, cost, operational burden, and rollback strategy. Do not silently replace the architecture.

## 4. Data-handling rules — absolute

1. Never add a real bank export, bank statement, screenshot, account identifier, transaction reference, or database to Git.
2. Never copy the user's uploaded CSV into fixtures, examples, docs, logs, issue comments, test snapshots, or generated reports.
3. Fixtures must be synthetic and clearly labelled as synthetic.
4. Do not persist `Auftragskonto`, any IBAN, BIC, creditor ID, mandate reference, or batch reference. Do not use them as log fields.
5. Do not log transaction descriptions, counterparty names, merchant names, amounts, or Telegram message text at INFO level or above.
6. Do not send transaction rows, descriptions, counterparties, or account metadata to external APIs or AI systems.
7. Do not ask for, store, or process online-banking passwords, PINs, TANs, card PANs, or authentication secrets.
8. Any Telegram statement-upload feature requires explicit product-owner approval and a new privacy/security review. It must remain disabled until then.
9. All data exports and backups must be generated locally and written with restrictive file permissions. Off-device backups must be encrypted before leaving the device.
10. Provide a documented data deletion path before the product is considered production-ready.

## 5. Engineering rules

- Follow the existing `src/` package layout and keep layers separated: ingestion → application/domain → storage/analytics → bot interface.
- Keep functions narrow, typed, deterministic, and testable.
- Prefer Python standard library for parsing, date/time, decimal arithmetic, SQLite, and CLI work. Add a dependency only with a clear reason and Raspberry Pi compatibility check.
- Do not add pandas, NumPy, Jupyter, Redis, PostgreSQL, Docker, Kubernetes, or an LLM runtime to the Pi deployment.
- Avoid broad exception catches. Errors shown to the user must be safe and actionable; logs must not include the raw input row.
- Use timezone-aware timestamps for events. Use `Europe/Berlin` for user-facing month/date boundaries.
- Store money as integer minor units. Render formatted currency only at the presentation boundary.
- Database changes require a versioned migration and tests. Do not edit an already-released migration.
- Do not add a destructive database migration without a backup and rollback procedure.
- All user-facing analytics must explain included/excluded classifications and the period used.
- Keep bot handlers thin. Handlers call application services and render their results; they do not contain SQL or categorisation logic.
- Avoid commands that print raw transaction details by default. Detailed output must be explicitly requested and limited to the private chat.

## 6. Required workflow for every task

1. Identify the relevant roadmap task and its acceptance criteria.
2. Read affected modules and tests before editing.
3. State assumptions in the PR description; do not invent missing product decisions.
4. Implement the smallest complete vertical slice.
5. Add tests for normal, boundary, malformed, duplicate, and privacy-sensitive cases.
6. Run `ruff check .`, `ruff format --check .`, `mypy src`, and `pytest`.
7. Inspect `git diff` for secrets, sample data, logs, and accidental scope creep.
8. Update relevant docs, the roadmap status, and the changelog.
9. Provide a concise completion report: files changed, behaviour delivered, tests run, known limitations, migration/rollback notes.

Do not mark a task complete merely because its code compiles. Acceptance criteria and tests must pass.

## 7. Financial correctness requirements

- No float calculations for money.
- Preserve sign: negative booked amounts are debits/outflows; positive amounts are credits/inflows, subject to transfer/refund classification.
- Do not automatically count transfers between the user's own accounts as spending or income.
- Do not automatically treat every incoming credit as salary or every debit as consumption.
- Refunds must be linked to their original merchant/category where evidence exists; otherwise keep them separate and uncertain.
- Categories are separate from transaction direction/classification.
- Subscription detection needs repeated evidence and a confidence level; one transaction is not a subscription.
- Forecasts must disclose assumptions, observation window, and uncertainty. Do not extrapolate when the data is too sparse.
- A user's correction outranks generic rules. Record the source and effective date of a correction.
- All totals must be reproducible from stored transactions and versioned classification rules.

## 8. Telegram safety requirements

- Enforce the allowlist using numeric Telegram user IDs, not usernames.
- Accept private chats only. Ignore all other users and group chats without revealing configuration.
- Fail closed if the allowlist is empty or malformed.
- Never echo arbitrary user text or raw file content into chat.
- Do not enable inline mode, group access, public commands, or file upload without explicit approval.
- Keep bot output concise; avoid dumping full transaction lists or references.
- Keep the bot token outside source control. Rotate it immediately if exposed.

## 9. Raspberry Pi operational constraints

- Target a small-memory device. Be conservative with memory, CPU, disk writes, and background jobs.
- Use one Python process, one SQLite file, and systemd. Do not require Docker.
- Long polling means only outbound HTTPS connectivity is required; do not open inbound firewall ports.
- Run under a dedicated unprivileged OS account.
- Keep the database directory and environment file private (`0700` directory / `0600` file where supported).
- Use SQLite's online backup API. Never copy a live WAL database with a naive file copy.
- Verify backup restoration as well as backup creation.
- Log operational events only; do not log financial content.

## 10. What not to do

- Do not replace the chosen architecture with AWS Lambda or Telegram Serverless without an ADR and product-owner approval.
- Do not use a generic AI prompt to categorise transactions before a deterministic correction/rules layer exists.
- Do not scrape online banking pages or automate browser login.
- Do not claim that a merchant or transaction is identified with certainty when it is only a candidate.
- Do not create a public GitHub repository or select an open-source license on behalf of the owner.
- Do not make real bank data a test requirement. Build synthetic fixtures and offer an optional local-only manual smoke-test procedure.
- Do not claim financial recommendations are guaranteed, personalised professional advice.

## 11. Definition of done

A feature is done only when:

- its acceptance criteria in `docs/AGENT_EXECUTION_PLAN.md` pass;
- unit and integration tests cover success and failure cases;
- financial arithmetic is decimal/minor-unit safe;
- privacy requirements are satisfied and tested where practical;
- errors are actionable without leaking personal data;
- docs and changelog are updated;
- CI passes; and
- the product owner can run the documented command or workflow from a clean checkout.
