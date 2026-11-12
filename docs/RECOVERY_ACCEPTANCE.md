# Recovery acceptance evidence

This is the engineer's evidence package for the independent QA repeat. It is not
a self-issued acceptance verdict. The independent QA agent must still assess the
release against the original report and its own tests.

## Financial correctness

Measured against `artifacts/qa/20261110-1727/test-data/independent_oracle.json`
using the corrected row-alignment harness:

| Metric | Oracle | Recovery | Result |
|---|---:|---:|---|
| Transactions | 182 | 182 | exact |
| Gross debits | 1.914.754 | 1.914.754 | exact |
| Gross credits | 3.782.247 | 3.782.247 | exact |
| Classified income | 3.735.000 | 3.735.000 | exact |
| Classified expenses | 1.869.364 | 1.869.364 | exact |
| Refunds | 5.997 | 5.997 | exact |
| Transfers | 80.000 | 80.000 | exact |
| Fees | 5.390 | 5.390 | exact |
| Net cash flow | 1.866.243 | 1.866.243 | exact |
| Savings rate | 50% | 50% | exact |
| Category totals | 15 categories | 15 categories | exact per category |
| Monthly totals | 11 active months | 11 active months | exact per month |

Reversals: the oracle excludes the unlinked +12,50 € reversal from net cash
flow. The recovery does the same and reports it in reconciliation. A linked
reversal offsets the original expense instead (covered by regression test).

Splits: `transaction_flows` expands split parents. The sum of allocations must
equal the parent exactly; reports, budgets and merchant rankings never count the
parent twice.

## Categorisation

With stable row alignment:

| Metric | Threshold | Result |
|---|---:|---:|
| Classification accuracy | — | 100.00% (182/182) |
| Category accuracy | ≥ 90% target | 100.00% (182/182) |
| Merchant accuracy | ≥ 85% target | 99.45% (181/182) |
| Payment-channel accuracy | ≥ 90% target | 100.00% (182/182) |
| High-confidence precision | ≥ 95% | 100.00% (161/161) |
| Transactions requiring review | ≤ 25% | 11.54% (21/182) |

The single merchant miss is a digital-wallet row whose counterparty is
`ANDROID DIGITAL CARD` and whose purpose contains no merchant identity. The
recovery deliberately does not fabricate `Supermarkt Mitte`; the category is
still correct (`food.groceries`) from the purpose text.

The original harness's row-alignment defect and the contradictory duplicate
fixtures are documented in `docs/RECOVERY_BASELINE.md`. The original script is
preserved; the active script joins by stable fields and keeps every threshold
unchanged.

## Reliability

- Schema v4 → v6 upgrade passes.
- Fresh install passes.
- A deliberately conflicting v5 upgrade fails atomically: `user_version` stays
  at 5 and no later column is applied; the upgrade succeeds after the conflict is
  removed.
- Import undo with split children passes `PRAGMA foreign_key_check` and
  `PRAGMA integrity_check`.
- Possible-duplicate imports are resumable: the first run inserts the first row,
  marks the batch `incomplete`, and the same file with
  `--accept-possible-duplicates` appends the skipped row to the same batch.
- Exact-file imports remain a no-op.
- Failed import batches roll back completely.

## User controls

Implemented and covered by tests:

- transaction review queue, search/filter/sort/pagination;
- category, classification, merchant and note corrections;
- undo correction (recompute deterministic labels);
- split, remove split, link refund/reversal;
- merchant entities, aliases, default categories, history, confirmed merges;
- structured rules with priority and conditions;
- learn-from-correction ("apply to future transactions from this merchant");
- budget create/edit/delete, alert thresholds, pace and projection;
- uncategorised-spending disclosure in budget reports.

All of these are available through the loopback web cockpit and the CLI, with
thin Telegram actions for review, corrections, budgets, rules and merchants.

## Questions

The structured parser supports spending, income, categories, merchants, date
ranges, comparisons, budgets, projections, savings, recurring payments, price
changes, largest expenses and uncategorised review. Unsupported or advice-seeking
questions return a clarification rather than a generic error. Answers include the
period, currency, calculation context and confidence/uncertainty where relevant.

## Dashboard

- Nine navigable sections with URL state and direct loading.
- Interactive SVG charts: category/merchant bars and monthly/weekly columns with
  value labels, axes, legends, tooltips, keyboard focus and click drill-down.
- Category/merchant clicks filter transactions; month/week clicks change the
  period; insight clicks open supporting transaction IDs.
- Responsive mobile card layout; amounts are never pushed off-screen.
- Health status resolves to the local database state; errors are cleaned;
  empty/loading states are explicit; date defaults use local components and the
  latest data month.

## Remaining limitations

- The QA fixture's `scenario_near_duplicates.CSV` and
  `scenario_overlap_weak_accept_duplicate.CSV` expectations conflict with the
  financial oracle and exact-file protection. See `RECOVERY_BASELINE.md`.
- The dashboard is authenticated only by loopback binding. Do not expose it
  without a separate authentication/threat-model decision.
- Recurring detection is intentionally conservative; a merchant needs at least
  three observations with plausible monthly-to-quarterly cadence, stable amounts
  (or one detected price change), and a relevant category.
- Forecasts remain daily-rate estimates and are suppressed when data is sparse.
- External AI, bank sync, public webhooks and Telegram group access remain
  disabled.

## Commands used for validation

```bash
ruff check .
ruff format --check .
mypy src
pytest
python artifacts/qa/20261110-1727/scripts/test_financial_accuracy_and_categorisation.py
python artifacts/qa/20261110-1727/scripts/test_import_experience.py
python artifacts/qa/20261110-1727/scripts/test_telegram_simulation.py
```
