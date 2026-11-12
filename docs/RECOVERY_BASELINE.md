# Recovery baseline

**Baseline commit:** `13e40b6` (`Expose merchant analytics in dashboard`)
**QA run:** `artifacts/qa/20261110-1727/`
**Previous verdict:** REJECTED — 45/100
**Recovery branch:** `recovery/20261110-qa-fixes`

This document records what was reproduced before any recovery change. It is the
evidence trail for the defect register in the original QA artifacts.

## Baseline test and tool state

| Check | Baseline result |
|---|---|
| `pytest` | 82 passed |
| `mypy src` | success |
| `ruff check .` | failed only on untracked QA artifacts (they are now excluded from product linting) |
| Financial oracle | failed: expenses `-49,50 €`, fees `+49,50 €`, net cash flow `+12,50 €` |
| Categorisation | 10.44% category accuracy; 43.90% high-confidence precision; 100% review burden |

## Reproduced defects

### DEF-01 — Coffee classified as a bank fee

**Reproduction.** Import `synthetic_sparkasse_12_months.CSV`; inspect
`merchant_candidate LIKE '%Coffee%'`.

**Observed.** `fee_candidate` / `financial.fees` for ordinary coffee purchases.

**Root cause.** `_FEE_MARKERS` contained `"fee"` and the classifier used plain
substring matching. `"fee"` is a substring of `"coffee"`.

**Code location.** `src/personal_finance_assistant/ingestion/classification.py`.

### DEF-02 — Consumer expenses defaulted to `uncategorized`

**Reproduction.** Import the 12-month QA export and group by `category_key`.

**Observed.**

```text
uncategorized     141
financial.fees     22
income.salary      11
income.refund       4
transfers           4
```

Rent, utilities, insurance, groceries, restaurants, coffee, fitness,
subscriptions, fuel, transit and pharmacy were all uncategorised.

**Root cause.** The classifier only had rules for salary, refund, fees, cash,
transfers and savings. No deterministic consumer category baseline existed.

**Code location.** `src/personal_finance_assistant/ingestion/classification.py`.

### DEF-02A — Uncategorised spending could disappear from budget reporting

**Observed.** A category budget reported `0,00 € used` when the same spending was
merely uncategorised. The budget service counted only exact category matches and
did not disclose the unallocated remainder.

**Code location.** `src/personal_finance_assistant/storage/sqlite.py`
(`budget_status`, `list_budget_statuses`).

### DEF-03 — Possible-duplicate import lockout

**Reproduction.** Create a content-only CSV where the same row appears twice.
Commit it without accepting possible duplicates, then re-run the same file with
`--accept-possible-duplicates`.

**Observed.** The second run returned `already_imported_file=True` and inserted
nothing because the file hash had already been recorded.

**Root cause.** The import row was written with a permanent `completed` meaning
even when possible duplicates were deliberately skipped.

**Code location.** `src/personal_finance_assistant/storage/sqlite.py`
(`import_file`), `src/personal_finance_assistant/cli.py`.

### DEF-04 — Schema v4 migration crash

**Reproduction.**

```python
connection.execute("PRAGMA user_version = 4")
Database(path).initialize()
```

**Observed.** `RuntimeError: No migration path exists from database schema 4.`

**Root cause.** The guard allowed `{0, 1, 2, 3}` while the v4→v5 block existed.
Additionally, DDL could be committed implicitly, so a failed upgrade could leave
a partially applied schema.

**Code location.** `src/personal_finance_assistant/storage/sqlite.py`
(`initialize`).

### DEF-05 — Splits ignored and import undo violated foreign keys

**Reproduction.** Split a transaction, run a period report, then `undo_import`.

**Observed.** Reports ignored `transaction_splits`; undo raised
`FOREIGN KEY constraint failed`.

**Root cause.** No reporting query read the split table, and undo deleted the
parent transaction before its split children.

**Code location.** `src/personal_finance_assistant/storage/sqlite.py`.

### DEF-06 — Management operations missing

**Observed.** No CLI, web or Telegram path to correct a transaction, manage
budgets, create rules, split a transaction or manage merchant aliases.

**Code location.** `cli.py`, `web/app.py`, `bot/application.py`.

### DEF-07 — `/ask` failed on normal phrasing

**Observed.** `"How much did I spend this month?"` returned the generic fallback
because the implementation checked for the exact substring `"spending"`.

**Code location.** `src/personal_finance_assistant/services/insights.py`
(`local_question`).

### DEF-08 to DEF-15 — UI, reconciliation and recurrence defects

| Defect | Baseline observation | Code location |
|---|---|---|
| DEF-08 | `toISOString()` shifted date inputs to the previous day/month | `web/static/app.js` |
| DEF-09 | header stayed on `Checking local database…` | `web/static/app.js` |
| DEF-10 | error banner displayed raw JSON | `web/static/app.js` |
| DEF-11 | mobile table clipped category and hid amount | `web/static/styles.css` |
| DEF-12 | charts were static divs with no axes, values or click handlers | `web/static/app.js` |
| DEF-13 | reconciliation omitted fees/reversals/cash | `storage/sqlite.py` |
| DEF-14 | empty period claimed `Reviewed data` | `storage/sqlite.py` |
| DEF-15 | recurrence flagged 122–182 day sporadic purchases | `storage/sqlite.py` |

## QA harness defects found during recovery

Two issues in the original harness affect how results must be interpreted. They
are recorded here rather than hidden.

1. **Row alignment.** `test_financial_accuracy_and_categorisation.py` sorted
   stored rows by `(booking_date, id)` and zipped them against ground truth in
   generation order. Ground truth is not date-sorted, so correct rows were
   compared to different rows. The original script is preserved as
   `test_financial_accuracy_and_categorisation_original.py`; the active script
   now joins each ground-truth row to its stored row by stable transaction
   fields. No threshold was changed.
2. **Contradictory duplicate fixtures.** `scenario_near_duplicates.CSV` contains
   two distinct purchases with different purposes; the financial oracle requires
   both to be inserted, while the import suite expected one to be skipped.
   `scenario_overlap_weak_accept_duplicate.CSV` is byte-identical to its
   predecessor, so exact-file protection correctly returns a no-op, while the
   import suite expected an insertion. Financial correctness takes precedence:
   distinct purpose-bearing rows are inserted, and identical file bytes remain a
   no-op. DEF-03 is verified with a separate identical-row regression test.

## Baseline reproduction commands

```bash
.venv/bin/python -m pytest -q
.venv/bin/python artifacts/qa/20261110-1727/scripts/test_financial_accuracy_and_categorisation.py
.venv/bin/python artifacts/qa/20261110-1727/scripts/test_import_experience.py
.venv/bin/python artifacts/qa/20261110-1727/scripts/test_telegram_simulation.py
```

The original financial script produced `18.644,14 €` classified expenses against
the oracle's `18.693,64 €`; the recovery implementation matches the oracle
exactly. See `docs/RECOVERY_ACCEPTANCE.md` for the measured recovery results.
