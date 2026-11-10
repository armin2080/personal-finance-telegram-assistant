# Project brief

## Objective

Deliver a private personal finance assistant for one owner. It ingests bank exports from a German Sparkasse account, converts transactions into a clean canonical ledger, learns corrections, analyses spending and income, manages budgets, detects recurring payments, and exposes a convenient Telegram interface.

## Users and operating context

- Initial user: one account owner.
- Main data source: manual Sparkasse account-export files.
- Hosting target: an already-owned Raspberry Pi, initially the low-memory Zero 2 W class.
- User interface: private Telegram chat; local CLI remains available for import, backup, recovery, and maintenance.
- Primary language for data: German bank-export labels; presentation can support English first and German later.
- Currency/timezone defaults: EUR and `Europe/Berlin`.

## Product outcomes

1. A trustworthy ledger where imported transactions are not silently lost or duplicated.
2. Merchant names that resolve the real merchant where possible, including PayPal pass-through transactions.
3. Categories that are explainable, editable, and progressively more accurate through user corrections.
4. Month-over-month spending and income summaries with transfers/refunds handled explicitly.
5. **Budget control is a first-class outcome:** monthly/category limits, amount spent, remaining allowance, configurable early-warning thresholds, and conservative month-end estimates when enough history exists. The app monitors and explains budgets; it cannot block card payments or bank debits.
6. Recurring-payment visibility and useful insights based on evidence, not generic motivational or financial-advice language.

## Product success measures

Measure quality before engagement:

- Import correctness: all valid supported rows parsed, amount/date fidelity 100% on fixtures and verified local smoke tests.
- Duplicate safety: same source file re-import is a no-op; reference-backed duplicates are skipped; uncertain content matches are surfaced rather than silently discarded.
- Privacy: zero real transaction data in Git, CI logs, or external analytics.
- Classification: report precision/coverage separately; uncertain rows remain uncategorised rather than being forced into a category.
- Explainability: every automatic merchant/category assignment has a rule/source and confidence.
- Reliability: service restarts after crashes/reboots; successful backup and restore are tested.

## Explicit non-goals for MVP

- Automatic bank connectivity or login (FinTS/PSD2 is a later investigation).
- Multi-user accounts or public deployment.
- Investment, tax, credit, or legal advice.
- Executing transfers, purchases, cancellations, or any bank action.
- External AI access to transaction-level information.
- Full web dashboard or Telegram Mini App.
- Receipt OCR, email scraping, or location tracking.
