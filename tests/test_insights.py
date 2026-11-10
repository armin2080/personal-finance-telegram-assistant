from datetime import date
from pathlib import Path

from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv
from personal_finance_assistant.services.insights import (
    budget_recommendations,
    cash_flow_forecast,
    forecast_budget,
    local_question,
    monthly_trend,
)
from personal_finance_assistant.storage.sqlite import Database

FIXTURE = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"


def test_budget_forecast_is_sparse_until_minimum_observations(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    database = Database(database_path)
    database.import_file(parse_sparkasse_csv(FIXTURE))
    database.set_budget("2026-03", "uncategorized", 10_000)

    forecast = forecast_budget(
        database_path,
        "2026-03",
        "uncategorized",
        as_of=date(2026, 3, 5),
    )

    assert forecast.sparse_data is True
    assert forecast.projected_minor is None
    assert forecast.confidence == "sparse"


def test_trend_and_cashflow_forecast_are_local_and_reproducible(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))

    trend = monthly_trend(database_path, "2026-03", months=2)
    cashflow = cash_flow_forecast(
        database_path,
        "2026-03",
        as_of=date(2026, 3, 31),
    )

    assert tuple(item.month for item in trend) == ("2026-02", "2026-03")
    assert cashflow.net_observed_minor == -2823
    assert cashflow.projected_net_minor is not None


def test_local_question_has_allowlisted_aggregate_intents(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))

    assert "2823 cents" in local_question(database_path, "How much spending?", "2026-03")
    assert "income" in local_question(database_path, "What is my income?", "2026-03")
    assert "aggregate spending or income" in local_question(
        database_path, "Tell me a merchant", "2026-03"
    )


def test_budget_recommendations_are_explainable_review_prompts(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    database = Database(database_path)
    database.import_file(parse_sparkasse_csv(FIXTURE))
    database.set_budget("2026-03", "uncategorized", 1000)

    recommendations = budget_recommendations(database_path, "2026-03", as_of=date(2026, 3, 10))

    assert recommendations == (
        "Review uncategorized: projected classified spend exceeds the configured budget "
        "under the current daily-rate assumption.",
    )
