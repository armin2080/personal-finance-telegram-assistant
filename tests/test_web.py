from pathlib import Path

from fastapi.testclient import TestClient

from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv
from personal_finance_assistant.storage.sqlite import Database
from personal_finance_assistant.web.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"


def test_dashboard_overview_returns_exact_money_objects(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))
    client = TestClient(create_app(database_path))

    response = client.get(
        "/api/overview",
        params={"start": "2026-03-01", "end": "2026-04-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["expenses"] == {"minor": 2823, "currency": "EUR"}
    assert body["net_cash_flow"] == {"minor": -2823, "currency": "EUR"}
    assert body["data_quality"] == "review_needed"


def test_dashboard_transactions_are_bounded_and_filterable(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))
    client = TestClient(create_app(database_path))

    response = client.get(
        "/api/transactions",
        params={
            "start": "2026-03-01",
            "end": "2026-04-01",
            "search": "PayPal",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    assert len(response.json()["transactions"]) == 1


def test_dashboard_rejects_invalid_date_range(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "finance.sqlite3"))

    response = client.get(
        "/api/overview",
        params={"start": "not-a-date", "end": "2026-04-01"},
    )

    assert response.status_code == 400


def test_dashboard_serves_static_root_and_assets(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "finance.sqlite3"))

    root = client.get("/")
    asset = client.get("/assets/styles.css")

    assert root.status_code == 200
    assert "Personal Finance Cockpit" in root.text
    assert asset.status_code == 200
    assert "text/css" in asset.headers["content-type"]


def test_dashboard_supporting_sections_return_safe_empty_shapes(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "finance.sqlite3"))

    insights = client.get(
        "/api/insights",
        params={"start": "2026-03-01", "end": "2026-04-01"},
    )
    trends = client.get("/api/trends", params={"end_month": "2026-03", "months": 6})
    budgets = client.get("/api/budgets", params={"month": "2026-03"})
    recurring = client.get("/api/recurring")

    assert insights.status_code == 200
    assert insights.json()["insights"][0]["id"] == "no-data"
    assert trends.status_code == 200
    assert len(trends.json()["months"]) == 6
    assert budgets.status_code == 200
    assert budgets.json()["budgets"] == []
    assert recurring.status_code == 200
    assert recurring.json()["candidates"] == []


def test_dashboard_exposes_merchant_and_weekly_analytics(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))
    client = TestClient(create_app(database_path))

    merchants = client.get(
        "/api/merchants",
        params={"start": "2026-03-01", "end": "2026-04-01"},
    )
    weeks = client.get(
        "/api/weekly-trends",
        params={"start": "2026-03-01", "end": "2026-04-01"},
    )

    assert merchants.status_code == 200
    assert merchants.json()["merchants"][0]["amount"] == {
        "minor": 1704,
        "currency": "EUR",
    }
    assert weeks.status_code == 200
    assert weeks.json()["weeks"][0]["expenses"] == {
        "minor": 2823,
        "currency": "EUR",
    }
