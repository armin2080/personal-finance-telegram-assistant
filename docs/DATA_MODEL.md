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
| `payment_channel` | `paypal`, `card`, `digital_wallet`, `direct_debit`, `bank_transfer`, `cash`, or `unknown`. |
| `classification` | `expense_candidate`, `income_candidate`, `transfer_candidate`, `refund_candidate`, `reversal`, `fee`, `cash_withdrawal`, `savings_investment`, or `unknown`. |
| `classification_source` | `deterministic`, `rule`, `user`, or `unreviewed`. |
| `classification_confidence` | 0.0–1.0 confidence for the flow classification. |
| `category_key` | Independent category, initially `uncategorized`. |
| `subcategory_key` | Optional stable subcategory key. |
| `category_source` | `unreviewed`, `rule`, or `user`. |
| `category_confidence` | 0.0–1.0; no confidence is implied for unreviewed rows. |
| `review_status` | `needs_review`, `confirmed`, or `dismissed`. |
| `note` | Optional owner note, stored locally. |
| `evidence` | Human-readable rule/evidence marker for the current label. |
| `dedupe_key` | Digest used to compare imports; not source reference itself. |
| `dedupe_basis` | `reference` or `content`. |
| `created_at` | UTC timestamp. |

Split allocations are stored separately and must reconcile exactly to the
original signed amount. A split is never accepted when its allocations do not
sum to the source transaction. The `transaction_flows` view expands split
parents for reporting; all analytics read it.

Linked refunds/reversals are stored in `transaction_links`. An unlinked reversal
is excluded from net cash flow and shown in reconciliation. A linked
refund/reversal offsets the linked original expense (capped at the original
amount) and is not counted a second time.

`imports.status` records `pending`, `incomplete` (possible duplicates awaiting a
decision), or `completed`. Re-running the same file with
`--accept-possible-duplicates` appends the skipped rows to the same batch;
byte-identical files remain a no-op.

Merchant entities carry an optional `default_category_key`. Classification rules
optionally carry `merchant_pattern`, `descriptor_pattern`, `payment_channel`,
`direction`, `payment_type`, `enabled` and `label` in addition to the primary
pattern, confidence, priority and version.

## Separate concepts

- **Counterparty:** the bank's beneficiary/payer field.
- **Merchant:** the actual business the user interacted with; may be hidden behind an intermediary such as PayPal.
- **Classification:** whether the flow is expense, income, transfer, refund, or unknown.
- **Category:** what the transaction is for (groceries, rent, transport, etc.).
- **Confidence:** how reliable the system's suggestion is.
- **Provenance:** why the system chose a label (user correction, merchant rule, deterministic heuristic, or AI in a future opt-in release).

Never collapse these concepts into one free-text `category` field.

Payment channel is descriptive metadata, not merchant identity. For example,
PayPal may be the channel while the extracted merchant remains the actual
counterparty described in the payment purpose.

## Classification policy

Rules are deliberately cautious:

- Payroll label (`LOHN`, `GEHALT`, `SALARY`) can be an income candidate.
- Own-account transfer evidence becomes `transfer_candidate` and is excluded from ordinary spend/income totals.
- A bank transfer to a known merchant category remains ordinary expense/income.
- Other negative rows are expense candidates. A deterministic merchant or
  descriptor rule may assign a category; otherwise the row stays uncategorised
  and needs review.
- Other positive rows are income candidates. Generic credits become
  `income.other` with low confidence and need review; they are never labelled
  salary.
- Fee detection is token-aware and consumer-context-aware; `coffee` is not a fee.
- Reversal markers are checked before refunds, so a reversal is not counted as a
  refund.

Refund markers such as `refund`, `Rückerstattung`, `Retoure`, or `Erstattung`
may produce `refund_candidate` only for positive credits.

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
3. Confirmed merchant alias / alias default category.
4. High-confidence deterministic merchant mapping.
5. Conservative descriptor rule.
6. Weak evidence or domain-only candidate, requiring review.
7. Uncategorised/unknown.

Confirmed corrections are marked `review_status = confirmed`; automatic or
ambiguous suggestions remain reviewable. Dismissal is explicit and does not
silently convert a movement into an expense.

A re-import or rules update must not overwrite a user correction. Record correction provenance and time.

User classification rules are versioned and take precedence over deterministic
rules. Every persisted automatic label stores its source, confidence, and rule
version so summaries remain auditable.

Merchant aliases are stored separately from transaction candidates and resolve
only exact normalised candidates. A transaction-level user correction is stored
with its provenance and always outranks later alias changes. The original
scrubbed counterparty and description remain available for local review.

Budgets use only split-aware negative `expense_candidate` flows with an exact
category key in the selected booking month. A budget report discloses
uncategorised expenditure in the month and marks the category status incomplete;
it must never show a false zero simply because classification failed. Recurring
candidates require at least three observations with plausible monthly-to-quarterly
cadence, stable amounts (or one detected price change), and a relevant category;
they are not subscriptions until the owner confirms them. Sporadic multi-month
purchases and grocery/restaurant shopping are rejected.
