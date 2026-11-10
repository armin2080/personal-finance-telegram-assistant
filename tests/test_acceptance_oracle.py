"""Independent expected-results oracle for the cockpit's 12-month journey."""

from datetime import date
from pathlib import Path

from personal_finance_assistant.domain import ParsedTransaction, ParseResult
from personal_finance_assistant.services.analytics import get_financial_overview
from personal_finance_assistant.services.insights import monthly_trend
from personal_finance_assistant.storage.sqlite import Database


def _year_of_synthetic_transactions() -> ParseResult:
    rows: list[ParsedTransaction] = []
    row_number = 1
    for month in range(1, 13):
        for day, amount, text, classification in (
            (1, 2_000_00, "Synthetic salary", "income_candidate"),
            (2, -800_00, "Synthetic rent", "expense_candidate"),
            (3, -300_00, "Synthetic groceries", "expense_candidate"),
            (4, -10_00, "Synthetic subscription", "expense_candidate"),
        ):
            rows.append(
                ParsedTransaction(
                    booking_date=date(2025, month, day),
                    value_date=date(2025, month, day),
                    booking_text=text,
                    purpose=text,
                    counterparty="Synthetic counterparty",
                    merchant_candidate=text,
                    amount_minor=amount,
                    currency="EUR",
                    info="synthetic fixture",
                    classification=classification,
                    dedupe_key=f"synthetic-{row_number}",
                    dedupe_basis="content",
                    row_number=row_number,
                )
            )
            row_number += 1
    return ParseResult(
        source_format="synthetic_12_month_oracle",
        file_sha256="synthetic-12-month-oracle",
        transactions=tuple(rows),
        encoding="synthetic",
    )


def test_twelve_month_oracle_is_independent_from_analytics_implementation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(_year_of_synthetic_transactions())

    overview = get_financial_overview(
        database_path,
        date(2025, 1, 1),
        date(2026, 1, 1),
    )
    trend = monthly_trend(database_path, "2025-12", months=12)

    # Oracle values are hand-calculated from 12 months x (income 2,000,
    # expenses 1,110), not by calling production aggregation code.
    assert overview.income_minor == 2_400_000
    assert overview.expenses_minor == 1_332_000
    assert overview.net_cash_flow_minor == 1_068_000
    assert overview.savings_rate_percent == 44
    assert len(trend) == 12
    assert all(item.income_minor == 200_000 for item in trend)
    assert all(item.expenses_minor == 111_000 for item in trend)
