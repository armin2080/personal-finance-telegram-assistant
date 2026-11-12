"""Regression coverage for the independent QA recovery defects."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from personal_finance_assistant.domain import ParsedTransaction, ParseResult
from personal_finance_assistant.ingestion.classification import classify_transaction
from personal_finance_assistant.ingestion.merchant_resolution import (
    canonical_merchant,
    extract_merchant_candidate,
    normalize_merchant_display,
)
from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv
from personal_finance_assistant.services.analytics import (
    get_financial_overview,
    get_period_report,
    reconcile_period,
)
from personal_finance_assistant.services.budgets import (
    get_budget_month_summary,
    get_budget_status,
    set_budget,
)
from personal_finance_assistant.services.insights import local_question
from personal_finance_assistant.storage.sqlite import (
    _MIGRATION_0,
    _MIGRATION_4,
    Database,
    _split_sql,
)
from personal_finance_assistant.web.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"


def _tx(
    *,
    purpose: str,
    counterparty: str,
    amount: int,
    booking_text: str = "KARTENZAHLUNG",
    day: date = date(2026, 5, 4),
    merchant: str | None = None,
    channel: str = "card",
    key: str = "key",
) -> ParsedTransaction:
    return ParsedTransaction(
        booking_date=day,
        value_date=day,
        booking_text=booking_text,
        purpose=purpose,
        counterparty=counterparty,
        merchant_candidate=merchant or counterparty,
        amount_minor=amount,
        currency="EUR",
        info="synthetic",
        classification="unknown",
        dedupe_key=key,
        dedupe_basis="content",
        row_number=1,
        payment_channel=channel,
    )


def _parse(*transactions: ParsedTransaction, name: str = "synthetic") -> ParseResult:
    return ParseResult("sparkasse_csv_camt_v8", name, tuple(transactions), "utf-8")


# ---------------------------------------------------------------------------
# DEF-01: safe bank-fee recognition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("purpose", "counterparty", "booking_text", "channel"),
    [
        ("Coffee and pastry", "COFFEE HOUSE NORD", "KARTENZAHLUNG", "card"),
        ("Coffee Shop purchase", "COFFEE SHOP", "KARTENZAHLUNG", "card"),
        ("Cafe Coffee", "CAFE COFFEE", "KARTENZAHLUNG", "digital_wallet"),
    ],
)
def test_coffee_purchases_are_never_bank_fees(
    purpose: str, counterparty: str, booking_text: str, channel: str
) -> None:
    result = classify_transaction(
        _tx(
            purpose=purpose,
            counterparty=counterparty,
            amount=-450,
            booking_text=booking_text,
            channel=channel,
        )
    )

    assert result.classification == "expense_candidate"
    assert result.category_key == "food.coffee"


@pytest.mark.parametrize(
    ("purpose", "counterparty", "booking_text"),
    [
        ("Monthly service fee", "Synthetic Service Ltd", "SEPA LASTSCHRIFT"),
        ("Account maintenance fee", "Synthetic Bank", "ENTGELTABSCHLUSS"),
        ("Kontoführungsgebühr", "Synthetic Bank", "SEPA LASTSCHRIFT"),
        ("Card fee", "Synthetic Bank", "KARTENZAHLUNG"),
        ("Foreign currency fee", "Synthetic Bank", "KARTENZAHLUNG"),
    ],
)
def test_explicit_bank_fees_are_recognised(
    purpose: str, counterparty: str, booking_text: str
) -> None:
    result = classify_transaction(
        _tx(purpose=purpose, counterparty=counterparty, amount=-500, booking_text=booking_text)
    )

    assert result.classification == "fee_candidate"
    assert result.category_key == "financial.fees"


def test_restaurant_with_service_charge_is_not_a_bank_fee() -> None:
    result = classify_transaction(
        _tx(
            purpose="Restaurant meal with service fee",
            counterparty="BISTRO ALEX",
            amount=-4200,
        )
    )

    assert result.classification == "expense_candidate"
    assert result.category_key == "food.restaurants"


# ---------------------------------------------------------------------------
# DEF-02: deterministic consumer categories and merchant identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("counterparty", "purpose", "expected"),
    [
        ("Synthetic Rent GmbH", "Monthly housing payment", "housing.rent"),
        ("Synthetic Utilities GmbH", "Monthly utilities", "housing.utilities"),
        ("Synthetic Insurance AG", "Monthly cover", "insurance"),
        ("SUPERMARKT MITTE", "Grocery purchase", "food.groceries"),
        ("RESTAURANT AM MARKT", "Restaurant meal", "food.restaurants"),
        ("COFFEE HOUSE NORD", "Coffee and pastry", "food.coffee"),
        ("Synthetic Gym e.V.", "Monthly gym membership", "health.fitness"),
        ("CloudBox Services GmbH", "Cloud storage monthly plan", "subscriptions.digital"),
        ("Synthetic Transit BV", "Public transport pass", "transport.public_transit"),
        ("Synthetic Apotheke", "Pharmacy purchase", "health.pharmacy"),
        ("Cinema Nord", "Purchase at synthetic cinema", "leisure"),
        (
            "Synthetic Electronics House",
            "One-off large electronics purchase",
            "shopping.electronics",
        ),
    ],
)
def test_consumer_categories_are_assigned_conservatively(
    counterparty: str, purpose: str, expected: str
) -> None:
    result = classify_transaction(_tx(purpose=purpose, counterparty=counterparty, amount=-1000))

    assert result.category_key == expected
    assert result.category_confidence >= 0.7


def test_merchant_normalisation_merges_explicit_variants_only() -> None:
    assert normalize_merchant_display("SUPERMARKT MITTE 03") == "Supermarkt Mitte"
    assert canonical_merchant("BISTRO-ALEX") == "Bistro Alex"
    assert canonical_merchant("Bistro Alex Dortmund") is None
    assert (
        extract_merchant_candidate(
            "PAYPAL *ONLINE SHOP", "Merchant omitted from payment text", "FOLGELASTSCHRIFT"
        )
        == "PayPal (merchant unclear)"
    )


# ---------------------------------------------------------------------------
# DEF-02A: uncategorised spending remains in totals and budget disclosures
# ---------------------------------------------------------------------------


def test_uncategorised_spending_remains_in_total_and_budget_is_incomplete(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(
        _parse(
            _tx(
                purpose="Grocery purchase",
                counterparty="SUPERMARKT MITTE",
                amount=-500,
                key="grocery",
            ),
            _tx(
                purpose="Mystery purchase",
                counterparty="Unknown Merchant",
                amount=-1000,
                key="mystery",
            ),
        )
    )
    set_budget(database_path, "2026-05", "food.groceries", 1000)

    report = get_period_report(database_path, date(2026, 5, 1), date(2026, 6, 1))
    status = get_budget_status(database_path, "2026-05", "food.groceries")
    summary = get_budget_month_summary(database_path, "2026-05")

    assert report.expenses_minor == 1500
    assert report.uncategorized_expenses_minor == 1000
    assert status.used_minor == 500
    assert status.uncategorized_expenses_minor == 1000
    assert status.complete is False
    assert summary.total_expenses_minor == 1500
    assert summary.uncategorized_expenses_minor == 1000
    assert "not yet categorised" in summary.disclosure


# ---------------------------------------------------------------------------
# Reversal, refund and split semantics
# ---------------------------------------------------------------------------


def _ledger_parse() -> ParseResult:
    return _parse(
        _tx(
            purpose="Payroll credit",
            counterparty="Synthetic Employer GmbH",
            amount=50000,
            booking_text="LOHN / GEHALT",
            channel="bank_transfer",
            key="salary",
        ),
        _tx(purpose="Restaurant meal", counterparty="BISTRO ALEX", amount=-10000, key="expense"),
        _tx(
            purpose="Refund for a previous purchase",
            counterparty="Synthetic Online Shop",
            amount=2000,
            key="refund",
        ),
        _tx(
            purpose="Storno Kartenzahlung",
            counterparty="Synthetic Retailer",
            amount=1250,
            booking_text="STORNO KARTENZAHLUNG",
            key="reversal",
        ),
        _tx(
            purpose="Account maintenance fee",
            counterparty="Synthetic Bank",
            amount=-500,
            booking_text="ENTGELTABSCHLUSS",
            channel="bank_transfer",
            key="fee",
        ),
        _tx(
            purpose="Own-account transfer",
            counterparty="Synthetic Owner Savings Account",
            amount=-20000,
            booking_text="ONLINE-UEBERWEISUNG",
            channel="bank_transfer",
            key="transfer",
        ),
    )


def test_unlinked_reversal_is_excluded_from_net_flow_but_reconciled(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(_ledger_parse())

    overview = get_financial_overview(database_path, date(2026, 5, 1), date(2026, 6, 1))
    reconciliation = reconcile_period(database_path, date(2026, 5, 1), date(2026, 6, 1))

    assert overview.expenses_minor == 10000
    assert overview.income_minor == 50000
    assert overview.refunds_minor == 2000
    assert overview.fees_minor == 500
    assert overview.transfers_minor == 20000
    assert overview.reversals_minor == 1250
    assert overview.net_cash_flow_minor == 41500
    assert reconciliation.reversal_minor == 1250
    assert reconciliation.fee_minor == 500
    assert reconciliation.transfer_out_minor == 20000
    assert reconciliation.unexplained_debit_minor == 0
    assert reconciliation.unexplained_credit_minor == 0


def test_splits_are_used_by_period_reports_and_budgets(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    result = Database(database_path).import_file(
        _parse(
            _tx(
                purpose="Groceries and cleaning supplies",
                counterparty="SUPERMARKT MITTE",
                amount=-3675,
                key="split",
            ),
        )
    )
    database = Database(database_path)
    with database.session() as connection:
        transaction_id = connection.execute(
            "SELECT id FROM transactions WHERE import_id = ?", (result.import_id,)
        ).fetchone()[0]
    database.split_transaction(
        transaction_id,
        ((-2000, "food.groceries", "food"), (-1675, "housing.household", "cleaning")),
    )
    set_budget(database_path, "2026-05", "food.groceries", 5000)

    report = get_period_report(database_path, date(2026, 5, 1), date(2026, 6, 1))
    categories = {item.category_key: item.amount_minor for item in report.category_expenses}
    status = get_budget_status(database_path, "2026-05", "food.groceries")
    report_total = sum(item.amount_minor for item in report.category_expenses)

    assert report.expenses_minor == 3675
    assert categories == {"food.groceries": 2000, "housing.household": 1675}
    assert report_total == report.expenses_minor
    assert report.transaction_count == 1
    assert status.used_minor == 2000


def test_import_undo_handles_splits_and_foreign_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    database = Database(database_path)
    result = database.import_file(
        _parse(
            _tx(purpose="Groceries", counterparty="SUPERMARKT MITTE", amount=-2000, key="undo"),
        )
    )
    with database.session() as connection:
        transaction_id = connection.execute("SELECT id FROM transactions").fetchone()[0]
    database.split_transaction(transaction_id, ((-2000, "food.groceries", ""),))

    deleted = database.undo_import(result.import_id or "", confirm=True)
    integrity = database.integrity_report()

    assert deleted == 1
    assert integrity["integrity"] == "ok"
    assert integrity["foreign_key_violations"] == []
    assert integrity["split_violations"] == []


# ---------------------------------------------------------------------------
# DEF-03: resumable possible-duplicate imports
# ---------------------------------------------------------------------------


def test_possible_duplicate_import_can_be_resumed_and_accepted(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    parsed = _parse(
        _tx(
            purpose="Identical purchase",
            counterparty="SUPERMARKT MITTE",
            amount=-2450,
            key="identical",
            day=date(2026, 10, 15),
        ),
        _tx(
            purpose="Identical purchase",
            counterparty="SUPERMARKT MITTE",
            amount=-2450,
            key="identical",
            day=date(2026, 10, 15),
        ),
        name="identical-file",
    )

    first = database.import_file(parsed)
    assert first.inserted == 1
    assert first.possible_duplicates == 1
    assert first.status == "incomplete"

    # The exact file may be re-run with explicit acceptance; the skipped row is
    # appended to the existing batch instead of being locked out forever.
    second = database.import_file(parsed, accept_possible_duplicates=True)
    assert second.inserted == 1
    assert second.status == "completed"
    batches = database.list_imports()
    assert len(batches) == 1
    assert batches[0].status == "completed"
    with database.session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# DEF-04: migrations from legacy schemas and atomic failure
# ---------------------------------------------------------------------------


def _legacy_v4(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        for statement in _split_sql(_MIGRATION_0):
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 4")


def test_schema_v4_database_upgrades_to_current(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    _legacy_v4(database_path)

    Database(database_path).initialize()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        columns = {row[1] for row in connection.execute("PRAGMA table_info(transactions)")}
    assert {"payment_channel", "review_status", "note", "evidence"} <= columns


def test_failed_migration_rolls_back_and_can_be_retried(tmp_path: Path) -> None:
    database_path = tmp_path / "retry.sqlite3"
    _legacy_v4(database_path)
    with sqlite3.connect(database_path) as connection:
        for statement in _split_sql(_MIGRATION_4):
            connection.execute(statement)
        # Simulate a conflicting partial upgrade: a note column exists before
        # the version-5 migration tries to add it again.
        connection.execute("ALTER TABLE transactions ADD COLUMN note TEXT NOT NULL DEFAULT ''")
        connection.commit()

    with pytest.raises(sqlite3.OperationalError):
        Database(database_path).initialize()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        columns = {row[1] for row in connection.execute("PRAGMA table_info(transactions)")}
        assert "evidence" not in columns
        connection.execute("ALTER TABLE transactions DROP COLUMN note")
        connection.commit()

    Database(database_path).initialize()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6


# ---------------------------------------------------------------------------
# User controls
# ---------------------------------------------------------------------------


def test_user_correction_outranks_rules_and_notes_persist(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    database = Database(database_path)
    result = database.import_file(parse_sparkasse_csv(FIXTURE))
    with database.session() as connection:
        transaction_id = connection.execute(
            "SELECT id FROM transactions WHERE import_id = ? LIMIT 1", (result.import_id,)
        ).fetchone()[0]

    database.correct_transaction_classification(
        transaction_id, "expense_candidate", "food.groceries", note="owner note"
    )
    database.add_classification_rule(
        "Example", "expense_candidate", "shopping.online", priority=900
    )
    database.reprocess_classifications()

    with database.session() as connection:
        row = connection.execute(
            "SELECT category_key, category_source, review_status, note "
            "FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
    assert tuple(row) == ("food.groceries", "user", "confirmed", "owner note")


def test_merchant_alias_default_category_and_merge(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    database = Database(database_path)
    database.add_merchant_alias(
        "SUPERMARKT-MITTE", "Supermarkt Mitte", default_category_key="food.groceries"
    )
    database.add_merchant_alias("SUPERMARKT MITTE 03", "Supermarkt Mitte")
    database.import_file(
        _parse(_tx(purpose="Purchase", counterparty="SUPERMARKT-MITTE", amount=-1000))
    )
    with database.session() as connection:
        row = connection.execute(
            "SELECT merchant_candidate, merchant_source, category_key FROM transactions"
        ).fetchone()
    assert tuple(row) == ("Supermarkt Mitte", "alias", "food.groceries")

    database.add_merchant_alias("SUPERMARKT MITTE ALT", "Supermarkt Mitte Alt")
    moved = database.merge_merchants("Supermarkt Mitte Alt", "Supermarkt Mitte", confirm=True)
    assert moved >= 0
    entities = database.list_merchant_entities()
    assert any(entity.canonical_name == "Supermarkt Mitte" for entity in entities)
    assert all(entity.canonical_name != "Supermarkt Mitte Alt" for entity in entities)


def test_rule_conditions_are_structured_and_safe(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    database = Database(database_path)
    database.add_classification_rule(
        "",
        "expense_candidate",
        "food.groceries",
        merchant_pattern="Supermarkt Mitte",
        payment_channel="card",
        direction="debit",
        priority=250,
    )
    database.import_file(
        _parse(
            _tx(
                purpose="Purchase",
                counterparty="SUPERMARKT MITTE",
                amount=-1200,
                channel="card",
                key="card",
            ),
            _tx(
                purpose="Purchase",
                counterparty="SUPERMARKT MITTE",
                amount=-1200,
                channel="paypal",
                key="paypal",
            ),
        )
    )
    with database.session() as connection:
        rows = connection.execute(
            "SELECT payment_channel, category_key, category_source FROM transactions ORDER BY payment_channel"
        ).fetchall()
    by_channel = {row[0]: (row[1], row[2]) for row in rows}
    assert by_channel["card"] == ("food.groceries", "user")
    assert by_channel["paypal"] != ("food.groceries", "user")

    with pytest.raises(ValueError):
        database.add_classification_rule("x", "expense_candidate", "food.groceries")


# ---------------------------------------------------------------------------
# Natural-language questions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected_fragment"),
    [
        ("How much did I spend this month?", "spent"),
        ("Where did most of my money go?", "Where your money went"),
        ("How much budget do I have left?", "No budgets are configured"),
        ("What are my largest unusual expenses?", "Largest individual expenses"),
        ("Did any subscriptions increase in price?", "price change"),
        ("Show transactions that have not been categorised.", "not yet categorised"),
        ("Compare my grocery spending over the last six months.", "Monthly breakdown"),
        ("Is my money good?", "cannot give purchase"),
    ],
)
def test_questions_are_structured_and_helpful(
    tmp_path: Path, question: str, expected_fragment: str
) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))
    Database(database_path).import_file(
        _parse(
            _tx(
                purpose="Grocery purchase",
                counterparty="SUPERMARKT MITTE",
                amount=-500,
                key="question-grocery",
                day=date(2026, 3, 12),
            ),
            _tx(
                purpose="Mystery purchase",
                counterparty="Unknown Merchant",
                amount=-1000,
                key="question-mystery",
                day=date(2026, 3, 13),
            ),
            name="question-extra",
        )
    )

    answer = local_question(database_path, question, "2026-03")

    assert expected_fragment.casefold() in answer.casefold()


# ---------------------------------------------------------------------------
# Dashboard API management surface and date handling
# ---------------------------------------------------------------------------


def test_dashboard_management_endpoints(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parse_sparkasse_csv(FIXTURE))
    client = TestClient(create_app(database_path))

    coverage = client.get("/api/coverage")
    assert coverage.status_code == 200
    assert coverage.json()["transaction_count"] == 5

    budget = client.post(
        "/api/budgets",
        json={"month": "2026-03", "category_key": "shopping.online", "limit_minor": 1000},
    )
    assert budget.status_code == 200
    budgets = client.get("/api/budgets", params={"month": "2026-03"}).json()
    assert budgets["budgets"][0]["category"] == "shopping.online"

    transactions = client.get(
        "/api/transactions",
        params={"start": "2026-03-01", "end": "2026-04-01", "sort": "amount", "direction": "asc"},
    ).json()
    transaction_id = transactions["transactions"][0]["id"]

    corrected = client.post(
        f"/api/transactions/{transaction_id}/correct",
        json={
            "classification": "expense_candidate",
            "category_key": "food.groceries",
            "merchant": "Owner Merchant",
            "note": "checked",
            "apply_to_future": True,
        },
    )
    assert corrected.status_code == 200
    splits = client.post(
        f"/api/transactions/{transaction_id}/split",
        json={
            "allocations": [
                {"amount_minor": -852, "category_key": "food.groceries", "note": "part"},
                {"amount_minor": -852, "category_key": "housing.household", "note": "part"},
            ]
        },
    )
    assert splits.status_code == 200

    rules = client.get("/api/rules").json()["rules"]
    assert any(rule["merchant_pattern"] == "Owner Merchant" for rule in rules)

    merchants = client.get("/api/merchant-entities").json()["merchants"]
    assert merchants

    answer = client.post(
        "/api/ask",
        json={"question": "How much did I spend this month?", "month": "2026-03"},
    )
    assert answer.status_code == 200
    assert "spent" in answer.json()["text"]

    reprocess = client.post("/api/reprocess")
    assert reprocess.status_code == 200
    assert reprocess.json()["updated"] >= 0

    imports = client.get("/api/imports").json()["imports"]
    assert imports[0]["status"] == "completed"
    integrity = client.get("/api/integrity").json()
    assert integrity["integrity"] == "ok"


def test_dashboard_date_defaults_do_not_use_utc_conversion() -> None:
    static = Path(__file__).parents[1] / "src/personal_finance_assistant/web/static"
    script = (static / "app.js").read_text()
    html = (static / "index.html").read_text()

    assert "toISOString" not in script
    assert 'api("/api/health")' in script
    for section in (
        "overview",
        "analytics",
        "budgets",
        "transactions",
        "review",
        "merchants",
        "insights",
        "ask",
        "settings",
    ):
        assert f'data-section="{section}"' in html
    assert "tx-cards" in html or "tx-cards" in (static / "styles.css").read_text()
    assert "Start date must be before end date." in script


def test_linked_reversal_offsets_the_original_expense(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.sqlite3"
    database = Database(database_path)
    result = database.import_file(
        _parse(
            _tx(
                purpose="Restaurant meal",
                counterparty="BISTRO ALEX",
                amount=-10000,
                key="original",
                day=date(2026, 5, 4),
            ),
            _tx(
                purpose="Storno Kartenzahlung",
                counterparty="BISTRO ALEX",
                amount=1000,
                booking_text="STORNO KARTENZAHLUNG",
                key="reversal",
                day=date(2026, 5, 6),
            ),
        )
    )
    with database.session() as connection:
        rows = connection.execute(
            "SELECT id, amount_minor FROM transactions ORDER BY booking_date"
        ).fetchall()
    original_id = rows[0]["id"]
    reversal_id = rows[1]["id"]

    unlinked = get_period_report(database_path, date(2026, 5, 1), date(2026, 6, 1))
    assert unlinked.expenses_minor == 10000
    assert unlinked.reversals_minor == 1000

    database.link_transactions(reversal_id, original_id, link_type="reversal")
    linked = get_period_report(database_path, date(2026, 5, 1), date(2026, 6, 1))

    assert linked.expenses_minor == 9000
    assert linked.reversals_minor == 0
    assert {item.category_key: item.amount_minor for item in linked.category_expenses} == {
        "food.restaurants": 9000
    }
    assert result.inserted == 2


def test_import_undo_preserves_other_import_batches(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    first = database.import_file(
        _parse(
            _tx(
                purpose="Groceries",
                counterparty="SUPERMARKT MITTE",
                amount=-1000,
                key="first",
                day=date(2026, 5, 1),
            ),
            name="first-file",
        )
    )
    database.import_file(
        _parse(
            _tx(
                purpose="Restaurant meal",
                counterparty="BISTRO ALEX",
                amount=-2000,
                key="second",
                day=date(2026, 5, 2),
            ),
            name="second-file",
        )
    )

    database.undo_import(first.import_id or "", confirm=True)

    with database.session() as connection:
        remaining = connection.execute(
            "SELECT merchant_candidate, amount_minor FROM transactions"
        ).fetchall()
    assert [tuple(row) for row in remaining] == [("Bistro Alex", -2000)]
    assert len(database.list_imports()) == 1


def test_schema_v4_upgrade_preserves_existing_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-data.sqlite3"
    _legacy_v4(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """INSERT INTO imports
               (id, file_sha256, source_format, encoding, transaction_count, created_at)
               VALUES ('imp', 'hash', 'synthetic', 'utf-8', 1, '2026-01-01T00:00:00+00:00')"""
        )
        connection.execute(
            """INSERT INTO transactions
               (id, import_id, booking_date, booking_text, description, counterparty,
                merchant_candidate, amount_minor, currency, classification, category_key,
                dedupe_key, dedupe_basis, created_at)
               VALUES ('txn', 'imp', '2026-05-01', 'KARTENZAHLUNG', 'Groceries',
                       'SUPERMARKT MITTE', 'Supermarkt Mitte', -1000, 'EUR',
                       'expense_candidate', 'food.groceries', 'key', 'content',
                       '2026-01-01T00:00:00+00:00')"""
        )
        connection.execute(
            "INSERT INTO budgets (id, month, category_key, limit_minor, created_at) "
            "VALUES ('budget', '2026-05', 'food.groceries', 5000, '2026-01-01T00:00:00+00:00')"
        )
        connection.commit()

    Database(database_path).initialize()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert connection.execute(
            "SELECT category_key, amount_minor FROM transaction_flows"
        ).fetchone() == ("food.groceries", -1000)
