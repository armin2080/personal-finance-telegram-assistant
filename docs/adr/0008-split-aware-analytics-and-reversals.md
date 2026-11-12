# ADR-0008: Split-aware analytics and explicit reversal arithmetic

- Status: Accepted
- Date: 2026-11-12

## Context

The QA recovery found that transaction splits were stored but ignored by every
reporting query, and that an unlinked reversal was treated as refund income. A
€12,50 reversal therefore changed net cash flow while also leaving the original
expense untouched. Import undo also failed when split children existed.

## Decision

1. Add a SQLite view `transaction_flows` that emits one row per split allocation
   for split parents and one row per parent otherwise. All analytics, budgets,
   forecasts, merchant rankings and reconciliation read this view.
2. Keep the parent transaction amount authoritative for the transaction count and
   for split reconciliation; never count the parent and its allocations together.
3. Define net cash flow as `income + refunds − expenses − fees`.
   - Unlinked reversals are excluded from net cash flow and reported in
     reconciliation (`reversal_minor`).
   - Linked refunds/reversals offset the linked original expense (capped at the
     original amount) and are not counted a second time.
   - Cash withdrawals, savings movements and own-account transfers are excluded
     from spending and net cash flow.
4. Delete split children before parent transactions during import undo and verify
   both `PRAGMA foreign_key_check` and `PRAGMA integrity_check`.
5. Run schema migrations inside one explicit SQLite transaction
   (`BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`) so a failure cannot leave an
   ambiguous schema version.

## Consequences

- Every reporting path must use the flow view; adding a new aggregate that reads
  `transactions` directly for expenses would reintroduce the split bug.
- Reports can explain unlinked reversals without counting them as income.
- Linked refunds/reversals require the owner to identify the original
  transaction; the system does not guess a link.
- Migration failure is retryable and leaves the previous schema intact.
- The independent oracle remains the authority for unlinked reversals.
