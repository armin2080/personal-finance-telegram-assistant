# Bank synchronisation proposal — investigation only

## Status

Automatic bank synchronisation is **disabled**. The supported workflow remains a
local Sparkasse CSV export imported through the CLI. The application does not
handle online-banking passwords, PINs, TANs, card PANs, browser login, or bank
webhooks.

## Options to compare

| Option | Data path | Benefits | Risks and open questions |
|---|---|---|---|
| Continue manual CSV | User export → local host | Lowest access and privacy risk; already supported | Manual work; export format changes |
| FinTS/HBCI library | Host → bank via FinTS | Direct access and local processing possible | Bank support, TAN flows, certificate handling, maintenance, lockouts |
| Licensed PSD2 aggregator | Host → aggregator → host | Provider handles bank compatibility | Third-party retention, regional terms, cost, consent, outage, token scope |

Examples such as `python-fints`, finAPI, Tink, and GoCardless Bank Account Data
are investigation subjects only, not dependencies or integrations. Current
Sparkasse compatibility, authentication/TAN behaviour, pricing, service terms,
data region, retention, deletion, and rate limits must be verified directly
before any selection.

## Approval and rollback

Any implementation requires a new ADR, maintainer approval, a privacy/security
review, an explicit kill switch, and a migration/rollback plan. Credentials
must remain outside the application database and source control. The default
must remain manual local import; disabling synchronisation must never delete the
local ledger.
