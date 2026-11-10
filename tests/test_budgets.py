from dataclasses import replace
from datetime import date
from pathlib import Path

from personal_finance_assistant.domain import ParseResult
from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv
from personal_finance_assistant.services.budgets import (
    find_recurring_candidates,
    get_budget_status,
    set_budget,
)
from personal_finance_assistant.storage.sqlite import Database

FIXTURE = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"


def test_budget_counts_only_classified_category_expenses(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    database = Database(database_path)
    database.add_classification_rule(
        "Example Streaming Ltd",
        "expense_candidate",
        "subscriptions.digital",
    )
    database.import_file(parse_sparkasse_csv(FIXTURE))
    set_budget(database_path, "2026-03", "subscriptions.digital", 900)

    status = get_budget_status(database_path, "2026-03", "subscriptions.digital")

    assert status.used_minor == 999
    assert status.remaining_minor == -99
    assert status.exceeded is True


def test_recurring_candidates_require_three_stable_observations(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    source = parsed.transactions[2]
    recurring = tuple(
        replace(
            source,
            booking_date=date(2026, 1 + index, 3),
            dedupe_key=f"recurring-{index}",
        )
        for index in range(3)
    )
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(
        ParseResult(
            source_format=parsed.source_format,
            file_sha256="recurring-file",
            transactions=recurring,
            encoding=parsed.encoding,
        )
    )

    candidates = find_recurring_candidates(database_path)

    assert len(candidates) == 1
    assert candidates[0].observations == 3
    assert candidates[0].average_interval_days == 30
    assert candidates[0].confidence == "high"
    assert candidates[0].confirmed is False
