# Agent execution plan — ordered work orders

This is the execution queue for the engineer/AI agent. Complete work orders in order unless a dependency requires a documented adjustment. Do not claim a later stage is complete while an earlier blocking acceptance criterion is unmet.

## WO-00 — Validate the scaffold

**Goal:** establish a known-good baseline before feature work.

Tasks:
1. Inspect all files and confirm no real user statement data is present.
2. Create a clean Python 3.11+ environment.
3. Install the package and dev dependencies.
4. Run Ruff, mypy, and pytest.
5. Fix all baseline issues without weakening tests or lint rules.
6. Document actual Python and OS versions tested.

Acceptance:
- Clean environment installation succeeds.
- Every test passes.
- CI workflow is valid.
- No secrets or user data in tracked files.

## WO-01 — Finish the Sparkasse CSV adapter

**Goal:** make the importer reliable for the exact observed layout and robust to minor export variations.

Tasks:
1. Add header canonicalisation for documented spelling/accent variants only.
2. Test delimiter, quoting, encoding, BOM, escaped quotes, and multiline field behaviour.
3. Improve row validation so error messages identify row/column without printing the value.
4. Add a dry-run report with transaction count, date range, currency counts, positive/negative counts, payment-type counts, and duplicate-strength counts. Do not print individual transaction values by default.
5. Keep non-EUR unsupported until currency exponent handling is designed and tested.
6. Ensure the parser does not read or persist ignored account/IBAN/BIC/mandate/creditor fields.
7. Add an import batch preview object and export it from the application layer.

Acceptance:
- All synthetic fixtures pass.
- A local-only test using an anonymised copy of a real file can be reconciled manually by the owner; never commit that file or its output.
- Invalid rows fail the entire import before any write.
- No private row content appears in logs or default CLI output.

## WO-02 — Complete duplicate review and import transaction safety

**Goal:** no transaction is silently lost due to a weak duplicate heuristic.

Tasks:
1. Make duplicate handling explicit in the preview: exact file, strong reference match, weak content match.
2. Add a CLI review/export of possible duplicate row numbers and safe reason codes only.
3. Require explicit `--accept-possible-duplicates` to store weak matches.
4. Add a command to inspect and undo an import batch. Undo must be transactional, owner-confirmed, and refuse if later user corrections depend on the batch unless they are handled explicitly.
5. Add tests for overlapping date-range exports, same file under another filename, duplicate source references, and two legitimate identical transactions.
6. Verify a database error rolls back the entire transaction batch.

Acceptance:
- Re-importing identical file bytes is a no-op.
- Reference duplicates are skipped with a count.
- Content-only matches are presented as uncertain.
- A rollback test proves no partial batch remains.

## WO-03 — Merchant identity and review memory

**Goal:** turn raw bank descriptions into reliable merchant identities without guessing.

Tasks:
1. Add canonical merchant entity and alias mapping.
2. Preserve original scrubbed counterparty and purpose for local review.
3. Build deterministic extraction rules for PayPal pass-through and card-payment descriptors.
4. Introduce confidence/provenance fields and rule versioning.
5. Implement a review queue and correction action.
6. Ensure corrections outrank later generic rule updates.

Acceptance:
- Test cases include direct merchant, PayPal merchant identified, PayPal merchant unknown, domain descriptor, personal payer/payee, and malformed description.
- Uncertain merchant is never auto-promoted to a confirmed identity.
- User correction remains stable through re-import and reclassification.

## WO-04 — Classification and categories

**Goal:** distinguish flow type from spending category.

Tasks:
1. Implement the category registry in `DATA_MODEL.md`.
2. Keep classification (`expense`, `income`, `transfer`, `refund`, `unknown`) distinct from category.
3. Add conservative deterministic rules with confidence and provenance.
4. Add user-created rule priority and versioning.
5. Add review controls for transfers/refunds.
6. Do not use an LLM in this work order.

Acceptance:
- Transfers do not enter expense totals without explicit review.
- Positive credits are not all called salary.
- Refunds are not counted as salary/income.
- Every auto-label can be traced to a rule.

## WO-05 — Telegram application services and commands

**Goal:** expose application functionality safely through a private Telegram interface.

Tasks:
1. Move command business logic into application services where required.
2. Add `/review`, `/spending`, `/income`, `/compare` only after underlying use cases are complete.
3. Add callback buttons with short-lived, owner-bound callback payloads; validate every callback.
4. Add pagination and conservative result limits.
5. Add user-friendly error handling with safe error IDs; detailed stack traces remain local only.
6. Keep group chats, inline mode, and document upload disabled.

Acceptance:
- Tests cover authorized user, unknown user, malformed user ID, group chat, callback replay, and command error.
- Handler files contain no SQL or classification rules.
- Bot does not echo incoming text or print raw transaction rows.

## WO-06 — Analytics

**Goal:** make monthly reports correct and explainable.

Tasks:
1. Define calendar month boundaries in `Europe/Berlin`.
2. Add category-level expenses/income, uncategorised totals, transfers, and refunds separately.
3. Add month-over-month comparison with absolute and percentage changes.
4. Add test ledgers with expected totals hand-calculated independently.
5. Display the exact period and inclusion/exclusion rules in every response.

Acceptance:
- All totals reconcile with hand-calculated fixture results.
- No float arithmetic.
- Unknown/transfer/refund rows do not silently pollute spend totals.

## WO-07 — Budgets and recurring payments

**Goal:** add practical control features only after classification is trustworthy.

Tasks:
1. Implement monthly category budgets.
2. Calculate used/remaining and threshold states.
3. Add alert preferences and rate limits.
4. Detect recurrence from multiple observations using configurable tolerance windows.
5. Require user confirmation for subscription status.

Acceptance:
- Budgets use classified expenses only.
- Subscription detection explains interval and supporting observations.
- No alert spam on restart or duplicate imports.

## WO-08 — Deploy and recover on the Pi

**Goal:** operate the app reliably on the owner's actual board.

Tasks:
1. Confirm board model, OS, architecture, Python version, free disk space, and memory constraints.
2. Install using a virtual environment; do not use Docker.
3. Create dedicated OS account and private data/config directories.
4. Install/harden the systemd service.
5. Verify outbound Telegram connectivity and no inbound port is open.
6. Verify restart after reboot, graceful shutdown, logs, backup, restore, and rollback.
7. Measure idle and peak memory during import and summary generation.

Acceptance:
- Service starts after reboot and recovers from network interruptions.
- Data is readable only by the service owner/root.
- Backup restoration to a separate database passes integrity checks.
- The board has sufficient disk and memory headroom.

## WO-09 — Optional AI / bank sync decisions

**Goal:** investigate, not assume, whether external capabilities are worth their privacy/cost trade-offs.

Tasks:
1. Write separate proposals for AI and bank sync.
2. List provider, data sent, retention, region, cost, rate limits, and deletion controls.
3. Use synthetic/aggregated data for provider tests.
4. Require explicit owner approval and ADR before implementation.
5. Provide a global feature kill switch.

Acceptance:
- AI and bank sync remain disabled unless separately approved.
- No raw statement or credential is sent to a provider.

## Required report after each work order

- Summary of user-visible behaviour.
- Files changed.
- Tests added and commands run.
- Security/privacy impact.
- Data migration and rollback notes.
- Remaining limitations and next recommended work order.
