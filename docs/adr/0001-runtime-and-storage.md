# ADR-0001: Python on Raspberry Pi with SQLite

- Status: Accepted
- Date: 2026-11-10

## Context

The owner prefers Python and can host the application on an existing Raspberry Pi. Telegram Serverless executes JavaScript modules in a V8 runtime and is not a Python host. The product initially has one user and modest transaction volume; it does not require a database server.

## Decision

Use Python, SQLite, and a single systemd-managed bot process on the Raspberry Pi. Use Telegram Bot API long polling for the interface. Keep bank ingestion and financial calculations local.

## Consequences

Positive:
- Keeps the preferred language and transaction data on owner-controlled hardware.
- Avoids a separate VPS/cloud database and recurring hosting costs.
- SQLite is adequate for a single user and simple backups.
- Long polling requires outbound HTTPS only.

Trade-offs:
- Owner is responsible for device uptime, updates, backups, and SD-card health.
- Raspberry Pi resources are constrained; dependencies and background jobs must stay lightweight.
- If the Pi is offline, the bot is unavailable.

## Revisit when

The project needs multi-user tenancy, high concurrency, a public dashboard, or a different deployment target. Any migration requires an ADR and data migration/rollback plan.
