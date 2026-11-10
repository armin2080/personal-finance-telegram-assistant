# Ready-to-use handoff prompt for the next coding agent

Copy the prompt below into the coding agent that will continue this repository. The agent must also read the repository's `AGENTS.md`; this prompt does not replace it.

---

You are the senior Python engineer taking over `personal-finance-telegram-assistant`. Your job is to turn this carefully scoped foundation into a reliable, private, single-user personal finance assistant. You are not being asked to redesign the product or to create a generic chatbot.

**Before changing any code:** read `AGENTS.md` and every document in the required reading order stated there. Then inspect the current branch, run the tests, and report the baseline. Follow `docs/AGENT_EXECUTION_PLAN.md` in order. Start with WO-00; do not jump to AI, budgets, or fancy Telegram UX before the importer and duplicate safety are correct.

### Product context

The owner lives in Germany and uses a Sparkasse account. The project received one real export for analysis, but the real file must never enter this repository. Its observed layout is a 17-column German-language, semicolon-separated, quoted CSV labelled as a CSV-CAMT V8-style export. It is **not XML CAMT**. The relevant columns include booking date, value date, booking text, purpose, counterparty, amount, currency, and transaction references. Amounts use German decimal commas. The observed layout includes common direct-debit, digital-card, card-payment, transfer, and payroll booking labels, as well as PayPal pass-through entries where the merchant can be inside the purpose text.

The existing parser and synthetic fixture document the observed format. Extend the adapter only with explicit tests and documented header aliases. Never copy any real account number, IBAN, BIC, transaction reference, name, merchant text, or amount into a fixture, test snapshot, documentation, issue, or log.

### Required architecture

- Python 3.11+.
- Raspberry Pi deployment, with low-memory constraints.
- One lightweight process managed by systemd.
- SQLite; no separate DB service.
- Telegram Bot API with outbound long polling; no webhook/public listener.
- Local CLI import remains supported; Telegram accepts only the approved private CSV upload flow.
- Application/domain logic stays independent of Telegram handlers.
- No external AI, analytics SaaS, bank-sync API, or online banking credential handling in MVP.

### Quality priorities, in this order

1. Import accuracy and money/date correctness.
2. Privacy, secrets handling, and no sensitive data in Git/logs/chat.
3. Duplicate handling that never silently discards a legitimate identical purchase.
4. Explicit distinction between counterparty, merchant, classification, category, and confidence.
5. User corrections that persist and override generic rules.
6. Reproducible analytics that exclude transfers and uncertain rows.
7. Simple operations and recovery on the Pi.
8. Only then: conversational features, forecasts, and optional AI proposals.

### First assignment

Complete WO-00 and WO-01 in `docs/AGENT_EXECUTION_PLAN.md`. Fix baseline tests/lint/type checks first. Then improve the CSV parser and import preview while keeping the import local. Add tests for encoding, quoting, malformed rows, German money formats, PayPal merchant extraction, card descriptors, ignored bank identifiers, exact-file idempotency, and weak duplicate review. Use only synthetic fixtures in Git.

Do not change architecture choices, repository visibility, or licensing. Do not create a public repository. Do not request the owner's raw bank statement. If an actual-bank smoke test is required, provide precise local-only instructions and ask the owner to run them on the Pi; do not request the raw file.

### Required completion report

At the end of each work order, report:
- what behaviour changed;
- files changed;
- commands and tests run, with pass/fail;
- known limitations;
- privacy/security impact;
- migration and rollback notes;
- the next work order and why it is unblocked.

Never claim a task is finished without passing acceptance criteria and tests. Never invent transaction facts. When uncertain, preserve the data as unknown and ask for review rather than guessing.

---
