# ADR 0005: Optional AI and bank-sync investigation boundaries

## Decision

AI and automatic bank synchronisation remain disabled. They are documented as
separate proposals and may not be enabled by adding a dependency or environment
variable alone.

## Reasons

The application handles sensitive financial data on a self-hosted, often
low-memory machine. Deterministic local processing satisfies the core import,
correction, reporting, and budget needs without external data egress or
credential storage.

## Required future decision

A future implementation needs separate maintainer approval, a privacy/security review,
provider or model verification, a default-off kill switch, synthetic evaluation,
rate limits, and a tested rollback path. See
`docs/AI_PROPOSAL.md` and `docs/BANK_SYNC_PROPOSAL.md`.
