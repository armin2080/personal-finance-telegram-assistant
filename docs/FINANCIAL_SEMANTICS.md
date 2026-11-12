# Financial semantics

This document defines the arithmetic used by every interface. All amounts are
signed integer EUR minor units. No binary floating point is used for money.

## Signed flow

| Flow | Sign | Inclusion in spending | Inclusion in net cash flow |
|---|---|---|---|
| `expense_candidate` | negative | yes | yes (subtracted) |
| `income_candidate` | positive | no | yes (added) |
| `refund_candidate` | positive | no | yes (added), unless linked to an expense |
| `reversal_candidate` | usually positive | no | no when unlinked; offsets the original when linked |
| `fee_candidate` | negative | no (reported separately) | yes (subtracted) |
| `cash_withdrawal_candidate` | negative | no | no (cash movement, not consumption) |
| `savings_candidate` | either | no | no (own-account movement) |
| `transfer_candidate` | either | no | no (own-account movement) |
| `unknown` | either | no | reported in reconciliation only |

**Net cash flow**

```text
income + refunds - expenses - fees
```

Transfers, cash withdrawals, savings movements and unlinked reversals are
excluded. This is the formula used by the independent oracle.

## Reversals, refunds and links

- An **unlinked reversal** is kept outside income, expenses, refunds, fees and
  net cash flow. It is visible in reconciliation (`reversal_minor`) so the ledger
  still balances.
- An **unlinked refund** is added to net cash flow and reported separately from
  income. It is never called salary.
- A **linked refund or reversal** offsets the linked original expense:
  - total expenses decrease by the linked amount (capped at the original
    expense);
  - the original category expense decreases by the same amount;
  - the refund/reversal is not counted a second time in net cash flow.
- A reversal without an identifiable original remains unlinked and requires
  review. A duplicate reversal is a separate row and therefore requires a
  separate decision.
- Reversed transfers remain transfers and are excluded from consumption.

## Splits

A split is a set of signed allocations attached to one parent transaction.

- The sum of allocation amounts must equal the parent amount exactly.
- Reporting expands a split parent into its allocations. The parent amount is
  never counted again.
- Unsplit transactions behave exactly as before.
- Category reports, merchant reports, budgets, monthly reports, weekly reports,
  forecasts and reconciliation all read the split-aware
  `transaction_flows` view.
- Deleting a split restores the parent category and marks the row for review.
- Undo deletes split children before parent transactions inside one transaction
  and verifies SQLite foreign keys afterwards.

## Categories and confidence

Classification (expense/income/transfer/refund/reversal/fee/cash/savings) is
independent of category. A category is never inferred from the sign alone.

- High-confidence automatic confirmation requires category confidence ≥ 0.8 and
  classification confidence ≥ 0.8 with a named category.
- A user correction always wins and is marked confirmed.
- An ambiguous descriptor remains `needs_review`.
- Uncategorised spending is always included in total expenses. It is excluded
  only from category totals, and that exclusion is disclosed.

## Budgets

- A budget belongs to one calendar month and one category.
- Usage is the sum of negative `expense_candidate` flows in that category.
- Remaining = limit − used.
- Percentage used = `round(used × 100 / limit)`; a zero limit reports 0%.
- Projection = `round(used × total_days / elapsed_days)` when usage exists and
  at least one day has elapsed. It is a pace estimate, not a guarantee.
- If any expenditure in the month is uncategorised, `complete=False` and the
  report explicitly states that the category budget status is incomplete.
- A budget never reports a false zero merely because classification failed.

## Reconciliation

`reconcile_period` exposes:

- parent transaction count;
- total debits and credits;
- expenses, income, refunds, transfers, fees, cash, savings and reversals;
- transfer in/out split by sign;
- unexplained debit/credit after classified flows are subtracted.

The reconciliation is an audit aid; it does not replace the net cash-flow
definition above.
