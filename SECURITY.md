# Security policy

This project handles sensitive personal financial data. Security and privacy
reports are taken seriously and are the most valuable kind of contribution you
can send.

## Reporting a vulnerability

Report privately through GitHub's **Report a vulnerability** button on the
Security tab of this repository. Do not open a public issue for a vulnerability.

Please include:

- what an attacker can do, and under which assumptions;
- the affected version, commit, or file;
- reproduction steps that use synthetic data only;
- whether the issue requires the local operator, a network position, or
  third-party access.

**Never include real financial data** — no statements, screenshots, IBANs,
identifiers, tokens, or database files. Reproduce with synthetic fixtures. If a
report cannot be demonstrated without real data, describe the mechanism instead
and we will work it out together.

## What is in scope

- Authentication or authorisation weaknesses in the loopback cockpit. Note that
  the cockpit intentionally has **no authentication** and binds to `127.0.0.1`;
  reaching it by tunnelling or a private network is the documented design, while
  exposing it publicly is a misconfiguration.
- Weaknesses in the Telegram allowlist, so that a non-allowlisted user or a group
  chat can reach data or commands.
- Secret leakage: bot tokens, credentials, or personal data in Git, logs,
  responses, or error messages.
- Persistence of data that must not be stored: account identifiers, IBANs, BICs,
  creditor IDs, mandate references, or collection references.
- Financial-correctness bugs where a plausible input produces a wrong total,
  double-counts a split, or loses a transaction.
- Injection of any kind, including SQL construction from user text.
- Denial of service against a modest self-hosted host, for example through an
  unbounded response, upload, or query.

## What is out of scope

- The absence of authentication on the cockpit when it is correctly bound to
  loopback and reached only through a private channel.
- The operator's own host, OS, or network hardening, which is documented in
  `docs/SELF_HOSTING.md`.
- Telegram's own infrastructure and its handling of message content.
- Findings that require an already-compromised host account or physical access to
  unencrypted storage.
- Missing features. Those belong in the issue tracker.

## Design context

Read `docs/SECURITY_AND_PRIVACY.md` for the threat model, trust boundaries, and
mandatory controls, and `docs/adr/0007-local-dashboard-adapter.md` for why the
cockpit is loopback-only.

## Supported versions

The `main` branch is supported. Fixes are applied there and released in the next
version. There are no long-term support branches.

## Hardening checklist for operators

- Keep `TELEGRAM_ALLOWED_USER_IDS` correct and non-empty. The bot refuses to start
  otherwise.
- Keep the database directory at `0700` and the database and `.env` at `0600`.
- Never bind the cockpit to anything other than `127.0.0.1` unless you have added
  authentication and reviewed the threat model.
- Use SSH keys with a documented recovery path before disabling password login.
- Encrypt any backup before it leaves the host.
- Rotate the bot token immediately with `@BotFather` if it is ever exposed, and
  remove it from Git history rather than only deleting the current line.
