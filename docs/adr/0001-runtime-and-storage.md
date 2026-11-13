# ADR-0001: Self-hosted Python with SQLite

- Status: Accepted
- Date: 2026-11-10

## Context

The application handles sensitive financial data and is intended for a single
user. Telegram Serverless executes JavaScript modules in a V8 runtime, is not a
Python host, and would place storage in a hosted service. Transaction volume for
one person is modest and does not require a database server.

## Decision

Use Python, SQLite, and a single systemd-managed process on a self-hosted Linux
machine. Use Telegram Bot API long polling for the bot interface. Keep bank
ingestion and financial calculations on the same host as the database.

The host may be any Linux machine, including a low-power single-board computer.
Nothing in the code depends on a specific board.

## Consequences

Positive:
- Transaction data stays on hardware the user controls.
- No separate database server, managed service, or recurring hosting cost.
- SQLite is adequate for one user, and its online backup API is simple to verify.
- Long polling requires outbound HTTPS only, so no inbound port is needed.

Trade-offs:
- The user is responsible for uptime, updates, backups, and storage health.
- Low-memory hosts constrain dependencies and background jobs.
- The bot is unavailable whenever the host is offline.

## Revisit when

The project needs multi-user tenancy, high concurrency, a publicly reachable
dashboard, or a managed hosting model. Any such migration requires a new ADR
with a data migration and rollback plan.
