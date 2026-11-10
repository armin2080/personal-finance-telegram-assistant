# Personal Finance Telegram Assistant

**Working title · Private repository recommended · Python · SQLite · Telegram**

A local-first personal finance assistant that imports German bank transactions, learns merchant/category corrections, explains spending patterns, and provides a private Telegram interface. The intended home for the first deployment is a Raspberry Pi; the initial design deliberately avoids separate cloud compute, a hosted database, Docker, or external AI services. Telegram still processes bot updates and replies through its Bot API.

> **Status: foundation / Milestones 0–5 in progress.** This repository contains the project contract, architecture, security rules, a working parser for the observed Sparkasse CSV-CAMT V8-style export, a duplicate-aware SQLite import path, deterministic classification, explainable reports, budget status, recurring-payment candidates, a restricted Telegram bot, synthetic test data, and CI. It is not yet a complete budgeting or financial-advice product. Follow `AGENTS.md` and `docs/AGENT_EXECUTION_PLAN.md` before extending it.

## Non-negotiable principles

1. **Private by default.** Real statements, databases, backups, identifiers, and secrets never belong in Git, issue trackers, logs, or test fixtures.
2. **Local-first.** The Pi stores transaction data in SQLite. The Telegram bot is a thin interface, not the data-processing engine.
3. **Deterministic before AI.** Parsing, money arithmetic, duplicate detection, user corrections, and recurring-payment detection must be explainable and testable. External AI is out of scope until the user explicitly opts in.
4. **Never guess silently.** Ambiguous merchants, categories, transfers, and duplicate candidates stay uncertain and are presented for review.
5. **No banking credentials.** Never request or store online-banking passwords, PINs, TANs, card numbers, or full account identifiers.
6. **No automatic financial actions.** The system is read-only. It never initiates transfers, purchases, cancellations, or investment transactions.

## Why this stack

- Python is the preferred implementation language and is supported by the local Raspberry Pi host.
- SQLite is sufficient for one user and avoids an always-on database service.
- `python-telegram-bot` handles Bot API updates using outbound long polling. No inbound public port or webhook is needed for the first release.
- Telegram Serverless is not the selected runtime because its bot backend uses JavaScript modules in a V8 runtime, not Python. It remains a possible alternative only if the project is deliberately ported to JavaScript.

The initial deployment target is a Raspberry Pi Zero 2 W-class device. Keep dependencies and memory use modest: no local LLM, pandas, Jupyter, Redis, PostgreSQL, or container orchestration in production.

## What the uploaded bank export taught us

The inspected example was named like a CAMT V8 export but its actual content is a **semicolon-separated CSV**, not CAMT XML. It has 17 German-language columns, quoted fields, dates in `DD.MM.YY` form, and EUR amounts using decimal commas. The layout covers direct debits, digital-card payments, card payments, transfers, and payroll-like credits. Some PayPal rows expose the actual merchant only inside the payment-purpose text. Only the format specification and synthetic test data are retained; no statement rows or personal metadata are included.

The supported parser is therefore named `sparkasse_csv_camt_v8`. It validates the column layout and intentionally ignores account IBAN, counterparty IBAN, BIC, creditor ID, mandate reference, and batch identifiers. Only synthetic fixture data is checked into this repository. See `docs/IMPORT_SPEC_SPARKASSE.md`.

## Quick start (development machine)

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
```

Set `FPA_DATABASE_PATH` in `.env` to a location outside this repository. Create a local database:

```bash
finance-assistant init-db
```

Inspect a bank export without importing it:

```bash
finance-assistant inspect /path/to/anonymised-export.CSV
```

Preview an import (the default is a dry run):

```bash
finance-assistant import /path/to/anonymised-export.CSV
```

Commit only after reviewing the preview:

```bash
finance-assistant import /path/to/anonymised-export.CSV --commit
```

Use `--accept-possible-duplicates` only after understanding the warning in the importer documentation. The same exact file is a no-op on subsequent imports.

Inspect persisted import batches or undo one after review:

```bash
finance-assistant imports
finance-assistant review
finance-assistant status
finance-assistant undo-import IMPORT_ID --yes
```

Undo is transactional and refuses batches with recorded transaction corrections.
`finance-assistant purge --yes` permanently deletes the local SQLite database and
its SQLite sidecars; create and verify a backup first.

Run the automated checks:

```bash
ruff check .
ruff format --check .
pytest
```

## Telegram commands

The private bot supports `/summary`, `/spending`, `/income`, `/compare`, `/review`,
`/budget CATEGORY`, and `/subscriptions`. Budget and recurring-payment output
is aggregate-only; repeated payments remain unconfirmed candidates.

## Telegram setup

1. Create a bot using `@BotFather`.
2. Put the bot token in the private `.env` file.
3. Set `TELEGRAM_ALLOWED_USER_IDS` to your numeric Telegram user ID. Never leave it empty.
4. Start with `finance-assistant bot`.

The bot accepts private chats from the allowlisted user ID only. It does not accept statement uploads in the MVP. Import files locally through the CLI. Telegram messages and replies are processed by Telegram, so do not send passwords, PINs, TANs, full IBANs, or raw bank exports to the bot.

## Creating the private GitHub repository

The ZIP is a Git-ready scaffold, not a published remote repository. After extraction, follow `docs/OWNER_SETUP_CHECKLIST.md` to create the private GitHub repository and push the first commit.

## Repository map

```text
AGENTS.md                         Mandatory instructions for coding agents
README.md                         Human-facing overview and quick start
src/personal_finance_assistant/   Application code
  ingestion/                      Sparkasse CSV parser and merchant extraction
  storage/                        SQLite persistence
  bot/                            Telegram transport adapter
  cli.py                          Local import / inspect / backup commands
tests/                            Synthetic fixtures and automated tests
docs/                             Product, architecture, privacy, import, and ops specs
.github/                          CI, Dependabot, issue and pull-request templates
systemd/                          Example hardened service unit
```

## The first user-visible milestones

1. Reliable imports from the exact Sparkasse CSV format, with safe previews and duplicate review.
2. A transaction review workflow that lets the user correct merchant and category labels.
3. Monthly spending/income summaries that explicitly exclude transfers and unresolved entries.
4. Budgets, recurring-payment detection, and alerts.
5. Trends, forecasts, and optional, consent-based financial intelligence.

Read `docs/ROADMAP.md` for scope, `docs/AGENT_EXECUTION_PLAN.md` for the ordered work queue, and `docs/OWNER_SETUP_CHECKLIST.md` for initial setup. A developer/AI agent must read `AGENTS.md` first.

## License and repository visibility

Keep this repository **private** until the owner deliberately chooses a licensing model. No open-source license is granted by this scaffold. Do not publish real financial data, secrets, or screenshots containing personal information.
