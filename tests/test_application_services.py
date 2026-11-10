from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv
from personal_finance_assistant.services.analytics import (
    get_current_month_summary,
    get_month_report,
)
from personal_finance_assistant.storage.sqlite import Database

FIXTURE = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"


def test_current_month_summary_uses_configured_timezone(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))
    now = datetime(2026, 3, 31, 23, 30, tzinfo=ZoneInfo("UTC"))

    summary = get_current_month_summary(database_path, "Europe/Berlin", now=now)

    assert summary.month == "2026-04"
    assert summary.month_label == "April 2026"
    assert summary.expenses_minor == 0
    assert summary.income_minor == 0
    assert summary.transaction_count == 0


def test_current_month_summary_includes_fixture_month(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))
    now = datetime(2026, 3, 20, 12, 0, tzinfo=ZoneInfo("Europe/Berlin"))

    summary = get_current_month_summary(database_path, "Europe/Berlin", now=now)

    assert summary.month == "2026-03"
    assert summary.expenses_minor == 2823
    assert summary.income_minor == 0
    assert summary.transaction_count == 3


def test_current_month_summary_rejects_naive_datetime(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        get_current_month_summary(
            tmp_path / "finance.sqlite3",
            "Europe/Berlin",
            now=datetime(2026, 3, 20, 12, 0),
        )


def test_month_report_reconciles_categories_and_exclusions(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))

    report = get_month_report(database_path, 2026, 3)

    assert report.expenses_minor == 2823
    assert report.income_minor == 0
    assert report.refunds_minor == 0
    assert report.transfers_minor == 0
    assert report.uncategorized_expenses_minor == 2823
    assert report.category_expenses[0].category_key == "uncategorized"
    assert report.category_expenses[0].amount_minor == 2823
    assert report.transaction_count == 3
