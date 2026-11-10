# Data model and financial semantics

## Money

- Persist EUR values as signed integer cents (`amount_minor`).
- Negative amount: bank debit/outflow. Positive amount: bank credit/inflow.
- Do not use floats anywhere in financial calculations.
- Currency must be explicit, even though MVP accepts EUR only.
- Presentation converts integer cents to formatted text; presentation formatting must never feed back into calculations.

## Transaction entity

| Field | Meaning |
|---|---|
| `id` | Internal random identifier. |
| `import_id` | Import batch that introduced the row. |
| `account_alias` | Owner-defined non-sensitive alias such as `primary`; never an IBAN. |
| `booking_date` | Date the bank booked the transaction. |
| `value_date` | Value date, nullable. |
| `booking_text` | Bank's transaction type/label. |
| `description` | Scrubbed purpose text. |
| `counterparty` | Scrubbed payee/payer label. |
| `merchant_candidate` | Best-effort extracted merchant name/domain. |
| `merchant_source` | `unreviewed`, `deterministic`, `alias`, or `user`. |
| `merchant_confidence` | 0.0–1.0 confidence for the merchant label. |
| `amount_minor` | Signed integer EUR cents. |
| `currency` | `EUR` in MVP. |
| `classification` | `expense_candidate`, `income_candidate`, `transfer_candidate`, `refund_candidate`, or `unknown`. |
| `classification_source` | `deterministic`, `user`, or `unreviewed`. |
| `classification_confidence` | 0.0–1.0 confidence for the flow classification. |
| `category_key` | Independent category, initially `uncategorized`. |
| `category_source` | `unreviewed`, `rule`, or `user`. |
| `category_confidence` | 0.0–1.0; no confidence is implied for unreviewed rows. |
| `dedupe_key` | Digest used to compare imports; not source reference itself. |
| `dedupe_basis` | `reference` or `content`. |
| `created_at` | UTC timestamp. |

## Separate concepts

- **Counterparty:** the bank's beneficiary/payer field.
- **Merchant:** the actual business the user interacted with; may be hidden behind an intermediary such as PayPal.
- **Classification:** whether the flow is expense, income, transfer, refund, or unknown.
- **Category:** what the transaction is for (groceries, rent, transport, etc.).
- **Confidence:** how reliable the system's suggestion is.
- **Provenance:** why the system chose a label (user correction, merchant rule, deterministic heuristic, or AI in a future opt-in release).

Never collapse these concepts into one free-text `category` field.

## Classification policy

Initial rules are deliberately cautious:

- Payroll label (`LOHN`, `GEHALT`, `SALARY`) can be an income candidate.
- Transfer-labelled booking text becomes `transfer_candidate` and is excluded from ordinary spend/income totals until reviewed.
- Other negative rows are expense candidates, but category remains unreviewed.
- Other positive rows are income candidates, but could be refunds or transfers; a later review step must resolve ambiguous cases.

Refund markers such as `refund`, `Rückerstattung`, `Retoure`, or `Erstattung`
may produce `refund_candidate` only for positive credits. Generic positive
credits remain income candidates with an uncategorised category; they are never
automatically labelled salary.

## Suggested category taxonomy

Use stable machine keys and localised display labels. Suggested initial keys:

- `housing.rent`, `housing.utilities`, `housing.household`
- `food.groceries`, `food.restaurants`, `food.delivery`, `food.coffee`
- `transport.public_transit`, `transport.taxi`, `transport.fuel`, `transport.other`
- `shopping.online`, `shopping.clothing`, `shopping.electronics`, `shopping.general`
- `subscriptions.digital`, `subscriptions.memberships`
- `health.pharmacy`, `health.medical`, `health.fitness`
- `education`, `insurance`, `fees`, `leisure`, `travel`
- `income.salary`, `income.refund`, `income.other`
- `transfers`, `uncategorized`

Do not assume these are exhaustive. The user must be able to add or rename display labels without changing historical transaction meaning.

The code-level registry is maintained in
`src/personal_finance_assistant/categories.py`; keys are stable historical
identifiers and labels are presentation values.

## Rules and correction priority

1. Explicit transaction-level user correction.
2. Explicit user-created merchant/category rule.
3. High-confidence deterministic mapping.
4. Low-confidence candidate, requiring review.
5. Uncategorised/unknown.

A re-import or rules update must not overwrite a user correction. Record correction provenance and time.

User classification rules are versioned and take precedence over deterministic
rules. Every persisted automatic label stores its source, confidence, and rule
version so summaries remain auditable.

Merchant aliases are stored separately from transaction candidates and resolve
only exact normalised candidates. A transaction-level user correction is stored
with its provenance and always outranks later alias changes. The original
scrubbed counterparty and description remain available for local review.

Budgets use only `expense_candidate` transactions with negative amounts and an
exact category key in the selected booking month. Recurring candidates require
at least three observations with stable merchant and amount evidence; they are
not subscriptions until the owner confirms them.
