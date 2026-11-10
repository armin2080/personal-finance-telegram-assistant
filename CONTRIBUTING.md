# Contributing

This repository handles private financial data. Contributions must comply with `AGENTS.md` and `docs/SECURITY_AND_PRIVACY.md`.

## Before opening a PR

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy src
pytest
```

The current validation environment is Python 3.14.4 on Ubuntu 26.04.1 LTS
(Linux 7.0.0-43-generic, x86_64). The supported minimum remains Python 3.11.

## Rules

- Use synthetic fixtures only.
- Never include bank exports, database files, screenshots, tokens, IBANs, BICs, names, or raw transaction references.
- Add tests for new parsing, financial, and privacy-sensitive behaviour.
- Money is integer minor units; no floats.
- Update the relevant docs, ADRs, and changelog.
- Keep Telegram handlers thin and local import as the default.
- Do not add an external service or runtime dependency without explaining operational and privacy impact.

## Pull request checklist

- [ ] Linked roadmap work order and acceptance criteria.
- [ ] Tests added/updated and all checks pass.
- [ ] No raw or identifying financial data added.
- [ ] No secret, token, database, or export added.
- [ ] Money/date/duplicate behaviour tested.
- [ ] Documentation and changelog updated.
- [ ] Migration and rollback plan included, if schema changed.
