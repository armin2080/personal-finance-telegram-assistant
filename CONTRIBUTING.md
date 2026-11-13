# Contributing

This project handles private financial data. Contributions must comply with `AGENTS.md` and `docs/SECURITY_AND_PRIVACY.md`.

## Before opening a PR

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy src
pytest
```

CI runs the same checks on Python 3.11. The supported minimum is Python 3.11;
later 3.x releases are expected to work and are welcome as CI matrix additions.

## Rules

- Use synthetic fixtures only.
- Never include bank exports, database files, screenshots, tokens, IBANs, BICs, names, or raw transaction references.
- Add tests for new parsing, financial, and privacy-sensitive behaviour.
- Money is integer minor units; no floats.
- Update the relevant docs, ADRs, and changelog.
- Keep Telegram handlers thin and local import as the default.
- Do not add an external service or runtime dependency without explaining operational and privacy impact.

## Pull request checklist

- [ ] Linked issue or roadmap item describing the acceptance criteria.
- [ ] Tests added/updated and all checks pass.
- [ ] No raw or identifying financial data added.
- [ ] No secret, token, database, or export added.
- [ ] Money/date/duplicate behaviour tested.
- [ ] Documentation and changelog updated.
- [ ] Software remains distributed under the MIT license; keep the copyright notice intact.
- [ ] Migration and rollback plan included, if schema changed.
