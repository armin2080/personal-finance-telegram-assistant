# Optional AI proposal — investigation only

## Status

AI is **disabled**. The current product uses deterministic parsing,
classification, analytics, and a local allowlisted aggregate query surface.
No transaction rows, descriptions, merchant names, identifiers, or database
files are sent to an AI provider.

## Possible options

| Option | Data sent | Main trade-off | Required verification |
|---|---|---|---|
| No external AI | None | Less natural language flexibility | Keep deterministic commands and local `/ask` sufficient |
| Hosted API provider | Explicitly minimised aggregates or synthetic data only | Network disclosure, retention, cost, outage, token management | Provider retention/deletion, region, DPA, pricing, rate limits, and logging |
| Local model on the same host | Local prompts and outputs | Memory, CPU, disk, model supply-chain risk | Host resource measurements, model license, prompt isolation, update process |

No provider has been selected or tested. Any future evaluation must use synthetic
or aggregated data, never a real statement or credential.

## Approval and kill switch

Implementation requires:

1. Maintainer approval and a new ADR.
2. A feature flag defaulting to off and failing closed.
3. Explicit field-level data minimisation and a provider deletion/retention review.
4. Request timeouts, rate limits, redacted operational logs, and a local fallback.
5. Tests proving the disabled path makes no network request.

AI must not classify transactions before deterministic corrections and review
controls. It must not produce guaranteed financial advice or autonomous actions.
