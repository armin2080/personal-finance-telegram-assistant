# ADR-0004: No external AI in the MVP

- Status: Accepted
- Date: 2026-11-10

## Context

Financial transaction descriptions and counterparties are sensitive. A deterministic parsing/rules/correction layer is needed before any model-based classification. An external model would introduce data transfer, retention, provider, cost, and correctness questions.

## Decision

No external LLM or local LLM runtime in the MVP. First build deterministic merchant extraction, user corrections, analytics, and evaluation metrics. Any later AI capability requires maintainer approval, an ADR, data-minimisation design, provider review, cost estimate, and kill switch.
