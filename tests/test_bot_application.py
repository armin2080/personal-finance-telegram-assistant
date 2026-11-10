from pathlib import Path
from types import SimpleNamespace

import pytest

from personal_finance_assistant.bot.application import (
    _format_eur,
    _is_authorized,
    _report_text,
    _settings,
)
from personal_finance_assistant.domain import CategoryTotal, PeriodReport
from personal_finance_assistant.settings import Settings


def _settings_for(user_ids: frozenset[int]) -> Settings:
    return Settings(None, user_ids, Path("finance.sqlite3"), "Europe/Berlin", "INFO")


def test_authorization_requires_allowlisted_private_chat() -> None:
    settings = _settings_for(frozenset({123}))
    allowed = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
    )
    group = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="group"),
    )
    unknown = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_chat=SimpleNamespace(type="private"),
    )

    assert _is_authorized(allowed, settings)
    assert not _is_authorized(group, settings)
    assert not _is_authorized(unknown, settings)


def test_report_text_is_aggregate_and_explains_inclusions() -> None:
    report = PeriodReport(
        start_date=__import__("datetime").date(2026, 3, 1),
        end_date=__import__("datetime").date(2026, 4, 1),
        expenses_minor=1200,
        income_minor=5000,
        refunds_minor=300,
        transfers_minor=900,
        uncategorized_expenses_minor=1200,
        category_expenses=(CategoryTotal("uncategorized", 1200),),
        transaction_count=3,
    )

    text = _report_text(report, "Spending report")

    assert "Spending report" in text
    assert "Transfers excluded from totals" in text
    assert "booking dates" in text
    assert "1200" not in text
    assert "12,00 €" in text


def test_settings_helper_rejects_missing_context_key() -> None:
    with pytest.raises(KeyError):
        _settings(SimpleNamespace(application=SimpleNamespace(bot_data={})))


def test_currency_formatting_is_minor_unit_safe() -> None:
    assert _format_eur(123456) == "1.234,56 €"
    assert _format_eur(-9) == "-0,09 €"
