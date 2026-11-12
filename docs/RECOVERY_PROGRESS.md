# Recovery progress

Status values: `DONE`, `IN PROGRESS`, `BLOCKED`.

| Priority | Work | Status | Evidence |
|---|---|---|---|
| 1 | DEF-01 safe fee recognition | DONE | token-aware fee rules; coffee/fee regression suite |
| 1 | DEF-02 consumer categorisation | DONE | 100% category accuracy on QA fixture |
| 1 | DEF-02A uncategorised spending in totals | DONE | budget disclosure + regression test |
| 2 | Reversal/refund arithmetic | DONE | oracle-exact net flow; linked-offset test |
| 2 | Split-aware reporting and undo | DONE | `transaction_flows`; FK/integrity tests |
| 3 | DEF-03 resumable duplicate imports | DONE | `incomplete` batch + append-on-accept test |
| 3 | DEF-04 atomic migrations | DONE | v4→v6, failed-upgrade rollback/retry tests |
| 3 | DEF-05 split-safe import undo | DONE | FK + integrity tests |
| 4 | Transaction review/correction/split/link | DONE | web, CLI, Telegram; API tests |
| 4 | Merchant management | DONE | entities, aliases, defaults, merge, history |
| 4 | Categorisation rules | DONE | structured conditions, priority, provenance |
| 4 | Learn from correction | DONE | "apply to future" creates an explicit rule |
| 5 | Budget management | DONE | CRUD, pace, projection, disclosure, alerts |
| 6 | Intent-based questions | DONE | structured parser + deterministic answers |
| 7 | Dashboard navigation/charts/mobile | DONE | nine sections, interactive SVG, mobile cards |
| 8 | Insights and recurrence | DONE | concentration, one-offs, fixed/discretionary, price changes |
| 9 | Regression coverage | DONE | 125 tests including 43 recovery tests |

## Commit plan

The recovery is structured as small logical commits:

1. `fix: restore deterministic financial classification`
2. `fix: correct reversals and split aggregation`
3. `fix: repair import lifecycle and database migrations`
4. `feat: add transaction review and merchant management`
5. `feat: implement budget management and safe reporting`
6. `feat: add intent-based financial questions`
7. `feat: implement interactive dashboard navigation and charts`
8. `feat: improve financial insights`
9. `test: add regression coverage for recovery defects`

## Not claimed

The project is not claimed as independently accepted. The independent QA agent
must repeat the original journeys and calculate the final score. The QA harness
alignment defect and conflicting duplicate fixtures are documented rather than
hidden.
