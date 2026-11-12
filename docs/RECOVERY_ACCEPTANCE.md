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

## Defect-by-defect recovery record

| Defect | Reproduced | Root cause | Code change | Regression test | Actual result |
|---|---|---|---|---|---|
| DEF-01 coffee/fee | yes | substring `"fee"` matched `"coffee"` | token-aware fee evidence, consumer context, compound German fee terms | `test_coffee_purchases_are_never_bank_fees`, `test_explicit_bank_fees_are_recognised` | coffee is `food.coffee`; fees remain `financial.fees` |
| DEF-02 uncategorised | yes | empty consumer rule baseline | deterministic merchant/descriptor rules and merchant normalisation | `test_consumer_categories_are_assigned_conservatively` | 100% category accuracy on QA fixture |
| DEF-02A totals | yes | budgets ignored unallocated spending | split-aware totals + `BudgetStatus.complete` + disclosure | `test_uncategorised_spending_remains_in_total_and_budget_is_incomplete` | totals include it; budget marked incomplete |
| DEF-03 duplicate lockout | yes (identical-row case) | file hash recorded as permanently completed while possible duplicates were skipped | `pending`/`incomplete`/`completed` batch lifecycle and append-on-accept | `test_possible_duplicate_import_can_be_resumed_and_accepted` | first run inserts 1/possible 1; accept appends the second row |
| DEF-04 v4 migration | yes | v4 excluded from allowed versions; implicit DDL commit | allowed set includes 4; explicit `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` | `test_schema_v4_database_upgrades_to_current`, `test_failed_migration_rolls_back_and_can_be_retried`, `test_schema_v4_upgrade_preserves_existing_rows` | v4→v6 and retry succeed; failure leaves v5 intact |
| DEF-05 splits/undo | yes | reports ignored split table; undo deleted parent first | `transaction_flows` view; delete splits before parents; FK check | `test_splits_are_used_by_period_reports_and_budgets`, `test_import_undo_handles_splits_and_foreign_keys`, `test_import_undo_preserves_other_import_batches` | split totals exact; FK/integrity clean |
| DEF-06 missing controls | yes | no management endpoints/commands | review, merchant, rule, budget, split, link, note, undo across web/CLI/bot | `test_dashboard_management_endpoints`, `test_user_correction_outranks_rules_and_notes_persist`, `test_merchant_alias_default_category_and_merge`, `test_rule_conditions_are_structured_and_safe` | owner can correct and manage data |
| DEF-07 `/ask` | yes | exact substring checks | structured intent/entity parser and deterministic answers | `test_questions_are_structured_and_helpful` | all 17 QA questions answer or clarify usefully |
| DEF-08 timezone | yes | `toISOString()` local→UTC shift | local date components + latest-data default | `test_dashboard_date_defaults_do_not_use_utc_conversion` | date inputs keep selected month |
| DEF-09 health | yes | no `/api/health` call | health fetch renders transaction count/schema | dashboard browser smoke test | header resolves |
| DEF-10 raw JSON | yes | error text printed raw | JSON `detail` extraction and clean banner | browser error-state smoke test | "Start date must be before end date." |
| DEF-11 mobile table | yes | fixed six-column table | mobile card layout with amounts/categories/confidence | mobile browser smoke test | amount visible at 390 px |
| DEF-12 static charts | yes | no values/axes/handlers | interactive SVG bar/column charts with tooltips, legends, keyboard and drill-down | browser interaction smoke test | category click filters transactions; month click changes period |
| DEF-13 reconciliation | yes | fees/reversals/cash absent | expanded reconciliation fields | `test_unlinked_reversal_is_excluded_from_net_flow_but_reconciled` | debits/credits reconcile to zero unexplained |
| DEF-14 empty badge | yes | quality computed as reviewed with zero rows | `no_data` quality state | dashboard browser smoke test | empty period shows "No data" |
| DEF-15 recurrence noise | yes | no cadence/category limits | monthly-to-quarterly cadence, gap handling, amount regimes, relevant categories | `test_recurring_candidates_require_three_stable_observations` + QA output | 122–182 day sporadics excluded; subscriptions and price change found |
