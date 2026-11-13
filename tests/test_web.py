from dataclasses import replace
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from personal_finance_assistant.domain import ParseResult
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


def test_import_preview_and_commit_from_upload(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    client = TestClient(create_app(database_path))

    preview = client.post(
        "/api/imports/preview",
        files={"file": ("statement.csv", FIXTURE.read_bytes(), "text/csv")},
    )

    assert preview.status_code == 200
    body = preview.json()
    assert body["transaction_count"] == 5
    assert len(body["rows"]) == 5
    assert body["rows"][0]["category"] == "transport.other"
    assert body["existing_import"] is None
    row = body["rows"][0]

    commit = client.post(
        "/api/imports/commit",
        json={
            "preview_id": body["preview_id"],
            "overrides": [
                {
                    "row_number": row["row_number"],
                    "merchant": "Ravi",
                    "classification": "expense_candidate",
                    "category_key": "food.restaurants",
                    "note": "lunch",
                }
            ],
        },
    )

    assert commit.status_code == 200
    assert commit.json()["inserted"] == 5
    transactions = client.get(
        "/api/transactions",
        params={
            "start": "1900-01-01",
            "end": "2100-01-01",
            "merchant": "Ravi",
        },
    ).json()
    assert transactions["total"] == 1
    assert transactions["transactions"][0]["category"] == "food.restaurants"
    assert transactions["transactions"][0]["merchant_source"] == "user"
    assert transactions["transactions"][0]["review_status"] == "confirmed"


def test_import_preview_reports_exact_file_match_without_reimporting(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    client = TestClient(create_app(database_path))
    payload = {"file": ("statement.csv", FIXTURE.read_bytes(), "text/csv")}

    first = client.post("/api/imports/preview", files=payload).json()
    client.post(
        "/api/imports/commit",
        json={"preview_id": first["preview_id"]},
    )
    second = client.post("/api/imports/preview", files=payload)

    assert second.status_code == 200
    assert second.json()["exact_file_match"] is True
    assert second.json()["existing_import"]["inserted_count"] == 5
    assert second.json()["existing_import"]["status"] == "completed"


def test_import_upload_rejects_unsupported_csv_and_unknown_rows(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "finance.sqlite3"))

    bad = client.post(
        "/api/imports/preview",
        files={"file": ("bad.csv", b"not,a,bank,export\n", "text/csv")},
    )
    assert bad.status_code == 400
    assert "required column" in bad.json()["detail"]

    preview = client.post(
        "/api/imports/preview",
        files={"file": ("statement.csv", FIXTURE.read_bytes(), "text/csv")},
    ).json()
    unknown = client.post(
        "/api/imports/commit",
        json={
            "preview_id": preview["preview_id"],
            "overrides": [{"row_number": 999, "category_key": "food.groceries"}],
        },
    )
    assert unknown.status_code == 400
    assert "not part of this import" in unknown.json()["detail"]


def test_possible_duplicates_can_be_resumed_from_web_preview(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "finance.sqlite3"))
    original = FIXTURE.read_bytes()
    first = client.post(
        "/api/imports/preview",
        files={"file": ("statement.csv", original, "text/csv")},
    ).json()
    client.post("/api/imports/commit", json={"preview_id": first["preview_id"]})

    modified = original.replace(b'"DE00000000000000000000"', b'"DE11111111111111111111"')
    second = client.post(
        "/api/imports/preview",
        files={"file": ("statement-again.csv", modified, "text/csv")},
    ).json()

    assert second["exact_file_match"] is False
    assert second["reference_matches"] == 4
    assert second["possible_duplicate_count"] == 1

    skipped = client.post(
        "/api/imports/commit",
        json={"preview_id": second["preview_id"]},
    ).json()
    assert skipped["inserted"] == 0
    assert skipped["possible_duplicates"] == 1
    assert skipped["status"] == "incomplete"

    resumed = client.post(
        "/api/imports/commit",
        json={
            "preview_id": second["preview_id"],
            "accept_possible_duplicates": True,
        },
    ).json()
    assert resumed["inserted"] == 1
    assert resumed["possible_duplicates"] == 0
    assert resumed["status"] == "completed"


def test_import_commit_can_learn_a_merchant_for_future_imports(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    client = TestClient(create_app(database_path))
    parsed = parse_sparkasse_csv(FIXTURE)
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("statement.csv", FIXTURE.read_bytes(), "text/csv")},
    ).json()
    target = preview["rows"][0]

    commit = client.post(
        "/api/imports/commit",
        json={
            "preview_id": preview["preview_id"],
            "overrides": [
                {
                    "row_number": target["row_number"],
                    "category_key": "transport.public_transit",
                    "classification": "expense_candidate",
                    "remember": "merchant",
                }
            ],
        },
    )

    assert commit.status_code == 200
    assert commit.json()["learned"] == ["merchant: Test Mobility GmbH"]
    assert commit.json()["learning_errors"] == []

    original = parsed.transactions[0]
    future = replace(
        original,
        booking_date=date(2026, 4, 1),
        value_date=date(2026, 4, 1),
        amount_minor=-777,
        dedupe_key="future-mobility-key",
        row_number=2,
    )
    rows, _ = Database(database_path).preview_import_rows(
        ParseResult(
            source_format=parsed.source_format,
            file_sha256="future-file",
            transactions=(future,),
            encoding=parsed.encoding,
        )
    )

    assert rows[0].merchant == "Test Mobility GmbH"
    assert rows[0].category_key == "transport.public_transit"
    assert rows[0].classification == "expense_candidate"
    assert rows[0].review_required is False


def test_import_commit_can_learn_a_descriptor_for_future_imports(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    client = TestClient(create_app(database_path))
    header = (
        '"Buchungstag";"Buchungstext";"Verwendungszweck";'
        '"Beguenstigter/Zahlungspflichtiger";"Betrag";"Waehrung";"Info"\n'
    )
    first_csv = (
        header
        + '"10.03.26";"KARTENZAHLUNG";"PAYPAL *MERCHANT UNCLEAR STEAM GAMES";'
        + '"PayPal";"-9,99";"EUR";"Umsatz gebucht"\n'
    ).encode("utf-8")
    first = client.post(
        "/api/imports/preview",
        files={"file": ("first.csv", first_csv, "text/csv")},
    ).json()
    row = first["rows"][0]
    assert row["merchant"] == "PayPal (merchant unclear)"
    assert row["merchant_learnable"] is False
    assert row["descriptor_pattern"] == "steam games"

    commit = client.post(
        "/api/imports/commit",
        json={
            "preview_id": first["preview_id"],
            "overrides": [
                {
                    "row_number": row["row_number"],
                    "category_key": "subscriptions.digital",
                    "classification": "expense_candidate",
                    "remember": "descriptor",
                }
            ],
        },
    )
    assert commit.status_code == 200
    assert commit.json()["learned"] == ["description: steam games"]

    second_csv = (
        header
        + '"11.03.26";"KARTENZAHLUNG";"PAYPAL *MERCHANT UNCLEAR STEAM-GAMES 5678";'
        + '"PayPal";"-19,99";"EUR";"Umsatz gebucht"\n'
    ).encode("utf-8")
    second = client.post(
        "/api/imports/preview",
        files={"file": ("second.csv", second_csv, "text/csv")},
    ).json()

    assert second["rows"][0]["category"] == "subscriptions.digital"
    assert second["rows"][0]["classification_source"] == "user"
    assert second["rows"][0]["review_required"] is False


def test_import_learning_rejects_ambiguous_merchant_choice(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "finance.sqlite3"))
    header = (
        '"Buchungstag";"Buchungstext";"Verwendungszweck";'
        '"Beguenstigter/Zahlungspflichtiger";"Betrag";"Waehrung";"Info"\n'
    )
    csv = (
        header
        + '"10.03.26";"KARTENZAHLUNG";"PAYPAL *MERCHANT UNCLEAR STEAM GAMES";'
        + '"PayPal";"-9,99";"EUR";"Umsatz gebucht"\n'
    ).encode("utf-8")
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("statement.csv", csv, "text/csv")},
    ).json()

    commit = client.post(
        "/api/imports/commit",
        json={
            "preview_id": preview["preview_id"],
            "overrides": [
                {
                    "row_number": preview["rows"][0]["row_number"],
                    "category_key": "subscriptions.digital",
                    "remember": "merchant",
                }
            ],
        },
    )

    assert commit.status_code == 200
    assert commit.json()["inserted"] == 1
    assert commit.json()["learned"] == []
    assert "ambiguous" in commit.json()["learning_errors"][0]


def test_apply_to_future_rule_matches_a_future_transaction(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    client = TestClient(create_app(database_path))
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("statement.csv", FIXTURE.read_bytes(), "text/csv")},
    ).json()
    client.post("/api/imports/commit", json={"preview_id": preview["preview_id"]})
    transactions = client.get(
        "/api/transactions",
        params={"start": "1900-01-01", "end": "2100-01-01", "limit": 1},
    ).json()["transactions"]
    transaction_id = transactions[0]["id"]

    corrected = client.post(
        f"/api/transactions/{transaction_id}/correct",
        json={
            "merchant": "Owner Merchant",
            "classification": "expense_candidate",
            "category_key": "food.groceries",
            "apply_to_future": True,
        },
    )
    assert corrected.status_code == 200

    header = (
        '"Buchungstag";"Buchungstext";"Verwendungszweck";'
        '"Beguenstigter/Zahlungspflichtiger";"Betrag";"Waehrung";"Info"\n'
    )
    future_csv = (
        header
        + '"12.03.26";"KARTENZAHLUNG";"Owner Merchant purchase";'
        + '"Owner Merchant";"-5,00";"EUR";"Umsatz gebucht"\n'
    ).encode("utf-8")
    future = client.post(
        "/api/imports/preview",
        files={"file": ("future.csv", future_csv, "text/csv")},
    ).json()

    assert future["rows"][0]["category"] == "food.groceries"
    assert future["rows"][0]["classification_source"] == "user"


def test_import_preview_exposes_a_submit_control_after_the_rows(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "finance.sqlite3"))

    html = client.get("/").text

    rows_index = html.index('id="import-rows"')
    actions_index = html.index('id="import-actions"')
    assert rows_index < actions_index
    assert 'id="import-commit-bottom"' in html
    assert 'id="import-edit-status"' in html
    assert 'id="import-remember-edits"' in html
    assert html.count('id="import-commit"') == 1


def test_blocked_account_payout_is_excluded_from_income_and_expenses(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    client = TestClient(create_app(database_path))
    header = (
        '"Buchungstag";"Buchungstext";"Verwendungszweck";'
        '"Beguenstigter/Zahlungspflichtiger";"Betrag";"Waehrung";"Info"\n'
    )
    csv = (
        header
        + '"01.03.26";"GUTSCHRIFT";"MONATLICHE AUSZAHLUNG SPERRKONTO";'
        + '"Blocked Account Service";"992,00";"EUR";"Umsatz gebucht"\n'
        + '"02.03.26";"KARTENZAHLUNG";"REWE SAGT DANKE";'
        + '"REWE";"-50,00";"EUR";"Umsatz gebucht"\n'
    ).encode("utf-8")
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("statement.csv", csv, "text/csv")},
    ).json()
    blocked = next(row for row in preview["rows"] if row["amount"]["minor"] > 0)
    assert blocked["category"] == "transfers.blocked_account"
    assert blocked["classification"] == "transfer_candidate"

    client.post("/api/imports/commit", json={"preview_id": preview["preview_id"]})
    overview = client.get(
        "/api/overview",
        params={"start": "2026-03-01", "end": "2026-04-01"},
    ).json()

    assert overview["income"] == {"minor": 0, "currency": "EUR"}
    assert overview["expenses"] == {"minor": 5000, "currency": "EUR"}
    assert overview["transfers"] == {"minor": 99200, "currency": "EUR"}
    assert overview["net_cash_flow"] == {"minor": -5000, "currency": "EUR"}

    budgets = client.get("/api/budgets", params={"month": "2026-03"}).json()
    assert budgets["total_expenses"] == {"minor": 5000, "currency": "EUR"}


def test_imported_transaction_can_be_recategorised_after_submission(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    client = TestClient(create_app(database_path))
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("statement.csv", FIXTURE.read_bytes(), "text/csv")},
    ).json()
    client.post("/api/imports/commit", json={"preview_id": preview["preview_id"]})
    committed = client.get(
        "/api/transactions",
        params={"start": "1900-01-01", "end": "2100-01-01", "limit": 1},
    ).json()["transactions"][0]
    assert committed["category"] != "food.coffee"

    updated = client.post(
        f"/api/transactions/{committed['id']}/correct",
        json={
            "classification": "expense_candidate",
            "category_key": "food.coffee",
            "note": "corrected after import",
        },
    )

    assert updated.status_code == 200
    reloaded = client.get(
        "/api/transactions",
        params={"start": "1900-01-01", "end": "2100-01-01", "ids": committed["id"]},
    ).json()["transactions"][0]
    assert reloaded["category"] == "food.coffee"
    assert reloaded["category_source"] == "user"
    assert reloaded["review_status"] == "confirmed"
    assert reloaded["note"] == "corrected after import"

    overview = client.get(
        "/api/overview",
        params={"start": "2026-03-01", "end": "2026-04-01"},
    ).json()
    assert overview["expenses"]["minor"] > 0


def test_edit_controls_are_rendered_in_the_transaction_views(tmp_path: Path) -> None:
    html = TestClient(create_app(tmp_path / "finance.sqlite3")).get("/").text
    script = TestClient(create_app(tmp_path / "finance.sqlite3")).get("/assets/app.js?v=20261113-1")

    assert 'data-action="edit-tx"' not in html
    assert script.status_code == 200
    assert 'data-action="edit-tx"' in script.text
    assert "transfers.blocked_account" in script.text
