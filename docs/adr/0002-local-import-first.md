# ADR-0002: Local bank-file import first; no Telegram statement uploads

- Status: Accepted
- Date: 2026-11-10

## Context

The first data source is a Sparkasse export. Uploading bank statements to a Telegram bot would send sensitive files through Telegram's Bot API infrastructure. The product can achieve the initial import goal with a local CLI on the Pi.

## Decision

The MVP imports files through a local CLI after SSH/SFTP/USB transfer. The Telegram bot does not accept statement uploads. This remains disabled unless the owner explicitly approves a separate privacy review.

## Consequences

- Raw statements do not need to transit the Telegram bot.
- The CLI is a first-class interface and must have a clear preview/confirmation workflow.
- Import is slightly less convenient than sending a document to the bot.
