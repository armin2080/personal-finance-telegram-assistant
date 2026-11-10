# Product specification

## Primary user journeys

### A. Import a bank export

1. The owner exports booked transactions from online banking.
2. The owner transfers the file to the Pi using a local method (SSH/SFTP/USB).
3. `finance-assistant inspect FILE` validates layout, date coverage, currency, row count, and warnings without showing private rows.
4. `finance-assistant import FILE` previews the import and performs no write.
5. After review, the owner runs `finance-assistant import FILE --commit`.
6. The app creates an import batch and commits valid rows atomically.
7. Reference-backed duplicates are skipped; weak content matches are reported as possible duplicates.

### B. Review merchant/category suggestions

1. The app displays a small batch of unresolved or low-confidence transactions.
2. Each item shows date, amount, a safe merchant candidate, and a short scrubbed description.
3. The user selects/corrects merchant, transaction classification, and category separately.
4. The correction is stored as a user rule with provenance and takes precedence over generic rules.
5. Reprocessing must not overwrite an explicit user correction.

### C. Understand monthly spending

1. `/summary` displays the selected month and totals for classified candidate income/expenses.
2. Transfers and uncertain transactions are excluded and counted separately in a future expanded view.
3. The response states the period and classification caveat.
4. Full transaction histories are not pushed automatically into chat.

### D. Budget management

1. User defines monthly budgets by category.
2. Spend is calculated only from transactions confidently classified as expenses and assigned to the relevant category.
3. The app shows used, remaining, and percentage of budget.
4. Alerts are configurable and rate-limited; no alert should be sent for uncertain transactions.

### E. Recurring payments

1. The app groups candidates by stable merchant identity and payment direction.
2. It estimates an interval and amount range from multiple observations.
3. It labels a candidate subscription only after repeated evidence and shows why.
4. User confirms, dismisses, or edits it.

## Telegram command plan

MVP implemented now: `/start`, `/help`, `/summary`, `/privacy`.

Planned in roadmap order:

- `/review` — review unresolved merchant/category candidates.
- `/spending` — spending by category and period.
- `/income` — income breakdown.
- `/budget` — inspect and manage budgets.
- `/subscriptions` — recurring payment candidates.
- `/compare` — compare selected months.
- `/export` — create a local export; do not transmit files without explicit confirmation.
- `/settings` — privacy, currency, timezone, and alert preferences.

Every command must be private-chat-only and allowlisted. Do not expose transaction queries to groups or inline mode.

## UX and language

- Use understandable labels, not unexplained bookkeeping jargon.
- Distinguish confirmed facts, estimates, and unknowns.
- Default to compact summaries; ask for a time range when it materially changes the calculation.
- Use EUR formatting consistently; use German number punctuation where German UI is selected.
- Keep responses readable on mobile screens.

## Financial language and disclaimers

The assistant provides informational organisation and arithmetic, not regulated financial, tax, legal, investment, or credit advice. Do not tell the user to buy or sell financial assets. Avoid absolute claims such as “you waste money”; phrase observations neutrally and show supporting transactions/counts when appropriate.
