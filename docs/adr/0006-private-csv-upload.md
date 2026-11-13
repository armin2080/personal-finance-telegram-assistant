# ADR-0006: Approved private CSV upload through Telegram

- Status: Accepted
- Date: 2026-11-10

## Context

The user needs a way to submit a statement from Telegram using the observed Sparkasse
CSV export. A CLI-only workflow prevents end-to-end testing of the bot. Sending
the file through Telegram exposes it to Telegram infrastructure, so the feature
must remain narrowly scoped and explicitly documented.

## Decision

Allow CSV document uploads only from the configured numeric allowlist in a
private chat. Reject other extensions, enforce a configurable size limit, use a
`0700` temporary directory, parse and import locally, return aggregate results
only, and delete temporary source storage after processing. Group chats,
inline mode, external APIs, and credential uploads remain disabled.

## Consequences

- Telegram infrastructure receives the uploaded CSV and must be included in the
  privacy model.
- The database retains canonicalised imported transactions, not the source
  file.
- The local CLI remains available for detailed validation and recovery.
- The feature can be disabled by removing the handler or rejecting uploads
  without changing stored data.
