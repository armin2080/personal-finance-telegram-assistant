# ADR-0007: Local dashboard as an application-service adapter

- Status: Accepted
- Date: 2026-11-10

## Context

The owner needs a richer visual cockpit than concise Telegram messages, while
the product must remain a single-owner Python/SQLite application on a
Raspberry Pi. A frontend must not duplicate financial calculations or create a
second data access path.

## Decision

Add a local FastAPI adapter and a responsive static dashboard over the existing
application and storage services. The server binds to `127.0.0.1` by default,
returns exact integer-minor-unit money objects, serves bounded transaction data
for the local owner, and performs no financial calculations in JavaScript.
Telegram and CLI remain separate adapters over the same services.

The initial presentation uses dependency-light HTML, CSS, and JavaScript rather
than a Node/React build pipeline because Node is not available in the current
Pi-oriented development environment and the target device should remain
conservative with runtime dependencies. The interface contract is intentionally
simple so it can later be replaced by a React/TypeScript or Telegram Mini App
presentation without changing domain services.

## Consequences

- The dashboard is useful locally without opening an inbound firewall port.
- A local browser can view transaction descriptions, so the owner must protect
  the device and browser session.
- API endpoints are not suitable for public exposure without authentication,
  CSRF/session design, and a new threat-model review.
- The static presentation can be replaced later without changing calculations.
