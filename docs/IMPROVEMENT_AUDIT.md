# Personal Finance Cockpit Improvement Audit

**Audit date:** 2026-11-10  
**Baseline revision:** `8176659`  
**Baseline test result:** 70 tests passed locally  
**Scope:** verify the implemented repository against the cockpit assignment before
making changes.

## Executive finding

The repository has a reliable local import foundation and a working private
Telegram adapter, but it is not yet a personal finance cockpit. The completion
report accurately describes the existing MVP direction but overstates the
product experience if interpreted as a complete dashboard or intelligent
financial analysis system. The highest-value work is to preserve the import
and privacy guarantees while adding a richer domain model, deterministic
analytics/insights services, and a local read-only web interface.

The assignment changes the product scope from Telegram-first MVP to three
connected interfaces. This audit treats that as an approved product extension,
not as permission to remove the existing Python/SQLite/Telegram architecture.

## Evidence-based findings

| ID | Severity | Area | Evidence | Finding | Recommendation |
|---|---|---|---|---|---|
| A-01 | Critical | Product surface | No web or API package exists under `src/`; `README.md` documents Telegram/CLI only | There is no responsive dashboard, API, transactions view, budgets view, insights view, or Ask interface | Add a local FastAPI read-only API and a TypeScript dashboard that calls application services |
| A-02 | High | Classification | `ingestion/classification.py` only emits expense, income, transfer, refund, or unknown | Reversal, fee, cash withdrawal, savings/investment movement, and explicit unresolved types are not represented | Expand classification literals, rules, storage constraints, migration, and analytics treatment |
| A-03 | High | Classification precedence | `storage/sqlite.py` resolves rules by `updated_at DESC` and returns the first matching pattern | Rule priority is implicit and overlapping user rules are not deterministically ordered by explicit precedence | Add rule priority/source/version and test correction > user rule > alias > deterministic rule |
| A-04 | High | Review workflow | `domain.py` review candidate contains only IDs, date, amount, merchant, classification, category, and boolean flags | No application operation exists for correction of category/flow, dismissal, bulk review, or transaction splitting | Add review commands/services, correction provenance, and safe bulk/split operations |
| A-05 | High | Category model | `categories.py` is a static dictionary | Users cannot create, rename, merge, or reassign categories without code changes; no hierarchy/subcategory persistence exists | Add versioned user category metadata while retaining stable historical keys |
| A-06 | High | Analytics | `PeriodReport` and `monthly_summary` expose expenses, income, refunds, transfers and category expenses only | No independent net cash flow, savings rate, merchant ranking, weekly trends, rolling comparisons, data coverage, or quality metrics | Build reusable analytics result objects with explicit period/baseline metadata |
| A-07 | High | Insights | `insights.py` returns tuples/strings for trends, anomalies, forecasts, and budget prompts | Insights have no title, severity, evidence, contributing transactions, confidence, or next action | Add structured evidence-backed insight objects and sparse/incomplete-history warnings |
| A-08 | High | Telegram boundary | `document_upload` directly invokes parser, `Database`, and report methods in the bot module | The upload handler bypasses an application service, violating the thin-adapter boundary and making web reuse difficult | Move upload orchestration into an import application service; keep Telegram rendering only in handler |
| A-09 | Medium | Telegram UX | `application.py` contains command handlers with plain text responses and no callback/menu flow | No preview confirmation, review actions, dashboard links, inline navigation, or notification settings | Add safe callback payloads and concise navigation after shared services exist |
| A-10 | Medium | Import semantics | Upload immediately calls `import_file` rather than presenting a confirmation preview | Telegram upload cannot review import counts or possible duplicates before persistence | Add upload preview state with owner-bound, short-lived confirmation and explicit commit |
| A-11 | Medium | Financial semantics | `PeriodReport.transfers_minor` uses `abs(amount)` and `income` excludes refunds, but no reversal/fee/cash semantics exist | Several required financial treatments cannot be explained or reconciled in the current model | Document signed flow treatment and add independent oracle tests |
| A-12 | Medium | Data coverage | Forecasts infer from observed rows but there is no coverage model for partial months or missing historical periods | A sparse or incomplete import can look like a complete financial trend | Add coverage intervals, completeness warnings, and period metadata to every dashboard response |
| A-13 | Medium | Testing | Existing fixtures contain five rows and tests focus on current MVP paths | No 12-month synthetic oracle, split transactions, unusual spending, incomplete months, API tests, or frontend interaction tests | Add synthetic 12-month dataset and independently calculated expected results |
| A-14 | Low | Documentation drift | `PRODUCT_SPEC.md` still says document upload is disabled while the approved upload ADR enables it; README status says foundation/M0–M5 in progress | Product documentation is internally inconsistent | Update architecture/product/roadmap docs as each new capability is implemented |

## What is already reliable

- Baseline suite passes: 70 tests.
- Sparkasse semicolon CSV parsing, EUR minor-unit arithmetic, encoding fallback,
  safe identifier handling, and atomic import behavior are covered.
- Exact file idempotency and weak duplicate review exist.
- SQLite schema migration and online backup mechanisms exist.
- Merchant aliases and transaction-level merchant correction precedence exist.
- Private numeric Telegram allowlist and temporary CSV cleanup are implemented.
- External AI, automatic bank sync, public webhooks, and financial actions remain
  disabled.

## Prioritized implementation plan

1. **Transaction intelligence:** extend the model and migration without changing
   existing imported rows or correction precedence.
2. **Analytics engine:** expose independent deterministic use cases and result
   objects; add coverage and quality metadata.
3. **Insights engine:** generate structured evidence from analytics, never from
   arbitrary SQL or model guesses.
4. **Dashboard:** add a local read-only API and responsive TypeScript frontend.
5. **Telegram:** reuse services, add safe preview/review/navigation, and keep
   output concise.
6. **Acceptance:** add 12-month synthetic fixtures, oracle calculations, API and
   frontend tests, documentation, and release evidence.

## Architecture decision

The new dashboard is a local interface extension. Python remains the financial
application language, SQLite remains the production database, and the domain
and application services remain frontend- and Telegram-independent. FastAPI is
an additional local adapter; React/TypeScript is a presentation layer and
must not contain authoritative financial calculations.

Because a web server is new runtime surface, it will be bound to loopback by
default, use no public webhook, expose no secrets, and be documented as a
local owner-only interface. Any later Telegram Mini App deployment requires a
separate authentication and threat-model decision.

## Not yet verified at audit start

- Any web API or dashboard behavior: not implemented.
- Visual accessibility and responsive behavior: not implemented.
- Structured evidence-backed insights: not implemented.
- Full correction/split workflow: not implemented.
- 12-month financial oracle and complete data-quality semantics: not implemented.
- Production Pi deployment of the future web adapter: not attempted.
