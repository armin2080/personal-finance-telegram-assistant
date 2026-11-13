# Personal Finance Telegram Assistant

**A local-first, single-user finance assistant with a Telegram bot, a CLI, and an installable mobile web cockpit.**

It imports German bank exports, turns them into a trustworthy transaction history,
learns your merchant and category corrections, explains where the money went,
tracks budgets, detects recurring payments, and answers plain-language questions —
all on a machine you control, with no cloud dependency.

> **Status: beta.** Working end to end and covered by 150+ tests. The core
> import, classification, reporting, budget, and cockpit flows are stable; the
> roadmap lists what is still missing. **This is not financial advice**, and it
> never touches your bank account.

## Principles

1. **Private by default.** Real statements, databases, backups, identifiers, and
   secrets never belong in Git, issue trackers, logs, or test fixtures.
2. **Local-first.** Your machine stores transactions in SQLite. The Telegram bot
   and the web cockpit are thin interfaces over the same services, not separate
   data processors.
3. **Deterministic before AI.** Parsing, money arithmetic, duplicate detection,
   corrections, and recurrence detection are explainable and testable. There is
   no LLM in the data path.
4. **Never guess silently.** Ambiguous merchants, categories, transfers, and
   duplicate candidates stay uncertain and are surfaced for review.
5. **No banking credentials.** It never asks for or stores online-banking
   passwords, PINs, TANs, card numbers, or full account identifiers.
6. **No automatic financial actions.** The system is read-only. It never
   initiates a transfer, purchase, cancellation, or investment.

## Why this stack

- **Python** for the whole application, with the standard library doing the
  parsing, decimal arithmetic, and date handling.
- **SQLite** for storage. One file, one user, no database server, and the online
  backup API for consistent copies.
- **Telegram long polling** via `python-telegram-bot`, so only outbound HTTPS is
  required. No webhook, no inbound port.
- **FastAPI with a dependency-free frontend** for the cockpit, so there is no
  Node build pipeline and no duplicated financial logic.
- **No Docker, no message queue, no cloud services.** One process, one file.

## Quick start

Python 3.11 or newer is required.

```bash
git clone https://github.com/<your-account>/personal-finance-telegram-assistant.git
cd personal-finance-telegram-assistant

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

install -m 0600 .env.example .env     # then edit .env
finance-assistant init-db
finance-assistant status
```

Point `FPA_DATABASE_PATH` at a location outside the repository. The Telegram
variables can stay empty while you use the CLI and the cockpit.

Preview an export without writing anything:

```bash
finance-assistant inspect path/to/export.CSV
finance-assistant import path/to/export.CSV            # dry run by default
finance-assistant import path/to/export.CSV --commit   # after reviewing
```

The same file imported twice is a no-op. When a commit skips possible
duplicates, the batch is marked `incomplete`; re-run the same file with
`--accept-possible-duplicates` to append exactly the skipped rows.

### Review and correct

```bash
finance-assistant review --details
finance-assistant correct TRANSACTION_ID --category food.groceries \
  --classification expense_candidate --merchant "Supermarkt Mitte" --note "checked"
finance-assistant correct TRANSACTION_ID --undo
finance-assistant split TRANSACTION_ID -2000:food.groceries -1675:housing.household
finance-assistant link REVERSAL_ID --to ORIGINAL_ID --type reversal

finance-assistant budget set food.groceries 15000 --month 2026-10
finance-assistant rule add --merchant-pattern "Supermarkt Mitte" \
  --category food.groceries --classification expense_candidate --priority 200
finance-assistant merchant alias --alias "SUPERMARKT-MITTE" --canonical "Supermarkt Mitte"

finance-assistant ask "How much did I spend on groceries last month?" --month 2026-10
finance-assistant integrity
```

`finance-assistant purge --yes` permanently deletes the local database and its
SQLite sidecars. Create and verify a backup first.

### Run the cockpit

```bash
finance-assistant web
```

Open `http://127.0.0.1:8000/`. Nine sections: Overview, Import, Analytics,
Budgets, Transactions, Review, Merchants & rules, Insights, Ask, and Settings.
Charts are interactive — clicking a category, merchant, or month opens the
matching transactions.

The cockpit is an installable PWA. On a phone it switches to a bottom tab bar
with safe-area handling and card-based transactions; on desktop it keeps the
horizontal navigation. Installing it requires a secure context, so serve it over
HTTPS or from the device's own `localhost`. The service worker caches only the
app shell and never caches `/api/` responses.

The dashboard binds to `127.0.0.1` and has no authentication of its own. Reach it
from another device through an SSH port forward or a private VPN rather than by
exposing the port. See `docs/SELF_HOSTING.md`.

### Import from the cockpit

Open **Import**, choose a CSV, and review one card per transaction before
committing. Each row shows the merchant, description, counterparty, suggested
type and category, confidence, and any duplicate warning. Edit any row, then
commit once. The whole import is one transaction: it either applies completely or
not at all.

Learning is opt-in per row:

- **Remember this merchant** — stores an exact alias and default category.
- **Remember this description** — stores a conservative descriptor rule, which is
  the safe option for ambiguous PayPal rows.
- **This transaction only** — the default, no rule created.

**Remember edited rows** picks the correct mode per edited row. Learned aliases
and rules are visible and removable under **Merchants & rules**, and no global
rule is ever created without you choosing it.

### Telegram

Create a bot with `@BotFather`, put the token in `.env`, set
`TELEGRAM_ALLOWED_USER_IDS` to your numeric user ID, then run:

```bash
finance-assistant bot
```

Commands: `/summary`, `/spending`, `/income`, `/compare`, `/review` (with inline
confirm and dismiss buttons), `/budget`, `/subscriptions`, `/trend`, `/forecast`,
`/ask`, `/correct`, `/rules`, `/merchants`, and `/privacy`.

The bot accepts private chats from allowlisted numeric user IDs only, and refuses
to start with an empty allowlist. It ignores every other user and every group
chat without revealing configuration. `/ask` uses a deterministic intent and
entity parser over local analytics, not an external model.

## How it decides things

The interesting part is not the parsing but the accounting rules, and they are
written down so you can check them:

- [`docs/FINANCIAL_SEMANTICS.md`](docs/FINANCIAL_SEMANTICS.md) — signed flows,
  the net-cash-flow formula, reversal and refund arithmetic, split invariants,
  budget formulas.
- [`docs/CATEGORISATION_RULES.md`](docs/CATEGORISATION_RULES.md) — the precedence
  order, token-aware fee detection, merchant normalisation, the category
  baseline, and how learning works.
- [`docs/IMPORT_SPEC_SPARKASSE.md`](docs/IMPORT_SPEC_SPARKASSE.md) — the exact
  source layout and what is deliberately discarded.

Money is always signed integer EUR minor units. Never a float. Unlinked
reversals are excluded from net cash flow but stay visible in reconciliation.
Uncategorised spending is always included in total expenditure, and a budget
report says so explicitly instead of pretending the month is fine.

## Supported input

The first supported source is the observed Sparkasse semicolon-delimited
CSV-CAMT V8-style export: 17 German-language columns, quoted fields, `DD.MM.YY`
dates, and EUR amounts with decimal commas. Despite the name, it is **CSV, not
CAMT XML**.

The parser validates the header, ignores account IBAN, counterparty IBAN, BIC,
creditor ID, mandate reference, and collection reference, and scrubs obvious
IBAN and card patterns out of stored memo text. Only synthetic fixtures are
committed; see `tests/fixtures/README.md`.

Other formats are on the roadmap.

## Development

```bash
make check     # ruff check, ruff format --check, mypy src, pytest
```

Or individually:

```bash
ruff check .
ruff format --check .
mypy src
pytest
```

Read [`AGENTS.md`](AGENTS.md) before changing code: it records the architecture
decisions, the data-handling rules that are not negotiable, the financial
correctness requirements, and the definition of done.

## Self-hosting

[`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md) covers installation, environment
configuration, systemd units, exploring the cockpit from another device,
installing it on a phone, backup and restore, upgrades with migration and
rollback, permissions, and deletion.

## Repository layout

```text
AGENTS.md                         Engineering contract and data-handling rules
src/personal_finance_assistant/
  ingestion/                      Sparkasse CSV parser, classification, merchants
  storage/                        SQLite schema, migrations, queries
  services/                       Analytics, budgets, insights, questions, management
  bot/                            Telegram transport adapter
  web/                            Loopback cockpit API and static PWA
  cli.py                          Command-line interface
docs/                             Architecture, data model, semantics, rules, ADRs
tests/                            Synthetic fixtures and automated tests
systemd/                          Example hardened service units
.github/workflows/ci.yml          Lint, type-check, and test on Python 3.11
```

## Contributing

Issues and pull requests are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md)
and [`AGENTS.md`](AGENTS.md). The two hard rules for any contribution: never add
real financial data, and never add float arithmetic for money.

## License

MIT — see [LICENSE](LICENSE).

Copyright (c) 2026 Armin Maddah. You may use, modify, and redistribute this
software, including commercially, provided the copyright notice and permission
notice are retained in all copies or substantial portions. The software is
provided without warranty.
