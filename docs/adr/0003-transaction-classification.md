# ADR-0003: Classification, merchant and category are separate

- Status: Accepted
- Date: 2026-11-10

## Context

Bank exports may name an intermediary (for example, PayPal) rather than the actual merchant. Bank transaction type, merchant identity, spending direction, and spending category are different dimensions. A positive credit may be a refund or transfer rather than income.

## Decision

Store transaction direction/classification separately from merchant identity and category. Store confidence and provenance for every derived label. Ambiguous cases remain unclassified until reviewed. User corrections outrank generic rules.

## Consequences

- The model and UI are more explicit and require slightly more code.
- Analytics can exclude transfers and refunds rather than counting all credits/debits as consumption/income.
- Rule changes can be audited and tested.
