import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from personal_finance_assistant.domain import ImportRowOverride, ParseResult
from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv
from personal_finance_assistant.storage.sqlite import Database

FIXTURE = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"


def test_import_is_idempotent_for_same_file(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    database = Database(tmp_path / "finance.sqlite3")
    first = database.import_file(parsed)
    second = database.import_file(parsed)
    assert first.inserted == 5
    assert second.already_imported_file is True
    assert second.inserted == 0


def test_import_row_overrides_are_applied_atomically(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    target = parsed.transactions[0]
    database_path = tmp_path / "finance.sqlite3"
    database = Database(database_path)

    result = database.import_file(
        parsed,
        overrides={
            target.row_number: ImportRowOverride(
                merchant="Ravi",
                classification="expense_candidate",
                category_key="food.restaurants",
                note="lunch",
            )
        },
    )

    assert result.inserted == 5
    with database.session() as connection:
        row = connection.execute(
            """SELECT merchant_candidate, merchant_source, classification,
                      classification_source, category_key, category_source,
                      category_confidence, review_status, note
               FROM transactions WHERE import_id = ? AND dedupe_key = ?""",
            (result.import_id, target.dedupe_key),
        ).fetchone()
        correction = connection.execute(
            "SELECT merchant FROM transaction_corrections WHERE transaction_id = "
            "(SELECT id FROM transactions WHERE import_id = ? AND dedupe_key = ?)",
            (result.import_id, target.dedupe_key),
        ).fetchone()
        user_rows = connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE category_source = 'user'"
        ).fetchone()[0]

    assert tuple(row) == (
        "Ravi",
        "user",
        "expense_candidate",
        "user",
        "food.restaurants",
        "user",
        1.0,
        "confirmed",
        "lunch",
    )
    assert correction["merchant"] == "Ravi"
    assert user_rows == 1


def test_invalid_import_override_rolls_back_the_whole_import(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    database = Database(tmp_path / "finance.sqlite3")

    with pytest.raises(ValueError, match="category override is not in the registry"):
        database.import_file(
            parsed,
            overrides={
                parsed.transactions[0].row_number: ImportRowOverride(category_key="not-a-category")
            },
        )

    assert database.list_imports() == ()
    assert database.health_status()["transactions"] == 0


def test_database_does_not_store_account_iban_or_bic(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    database_path = tmp_path / "finance.sqlite3"
    Database(database_path).import_file(parsed)
    with sqlite3.connect(database_path) as connection:
        records = connection.execute(
            "SELECT description, counterparty, merchant_candidate FROM transactions"
        ).fetchall()
    stored_text = repr(records)
    assert "DE00000000000000000000" not in stored_text
    assert "TESTDEFFXXX" not in stored_text
    assert "ENDTOEND-TEST-0001" not in stored_text
    assert "MANDATE-TEST-01" not in stored_text


def test_monthly_summary_excludes_transfer_candidates(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    database = Database(tmp_path / "finance.sqlite3")
    database.import_file(parsed)
    summary = database.monthly_summary("2026-03")
    assert summary["expenses_minor"] == 2823
    assert summary["income_minor"] == 0
    assert summary["transaction_count"] == 3


def test_content_only_duplicate_is_flagged_not_silently_merged(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    weak = replace(parsed.transactions[0], dedupe_basis="content", dedupe_key="weak-key")
    weak_result = ParseResult(
        source_format=parsed.source_format,
        file_sha256="different-file-hash",
        transactions=(weak, weak),
        encoding=parsed.encoding,
    )
    result = Database(tmp_path / "finance.sqlite3").import_file(weak_result)
    assert result.inserted == 1
    assert result.possible_duplicates == 1


def test_legitimate_identical_transactions_can_be_explicitly_accepted(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    weak = replace(parsed.transactions[0], dedupe_basis="content", dedupe_key="weak-key")
    weak_result = ParseResult(
        source_format=parsed.source_format,
        file_sha256="different-file-hash",
        transactions=(weak, replace(weak, row_number=3)),
        encoding=parsed.encoding,
    )

    result = Database(tmp_path / "finance.sqlite3").import_file(
        weak_result, accept_possible_duplicates=True
    )

    assert result.inserted == 2
    assert result.possible_duplicates == 1


def test_duplicate_review_reports_safe_reason_codes_and_row_numbers(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    database = Database(tmp_path / "finance.sqlite3")
    database.import_file(parsed)

    review = database.review_import(
        ParseResult(
            source_format=parsed.source_format,
            file_sha256="another-file",
            transactions=(
                replace(
                    parsed.transactions[0],
                    dedupe_basis="content",
                    dedupe_key=parsed.transactions[0].dedupe_key,
                ),
                replace(
                    parsed.transactions[0],
                    row_number=3,
                    dedupe_basis="content",
                    dedupe_key=parsed.transactions[0].dedupe_key,
                ),
                parsed.transactions[1],
            ),
            encoding=parsed.encoding,
        )
    )

    assert review.exact_file_match is False
    assert review.reference_matches == 1
    assert review.possible_duplicates == (
        (2, "content_match_existing"),
        (3, "content_duplicate_in_file"),
    )


def test_import_undo_is_transactional_and_requires_confirmation(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(parse_sparkasse_csv(FIXTURE))

    try:
        database.undo_import(result.import_id or "")
    except ValueError as exc:
        assert "explicit confirmation" in str(exc)
    else:
        raise AssertionError("undo without confirmation should fail")

    assert database.undo_import(result.import_id or "", confirm=True) == 5
    assert database.list_imports() == ()


def test_import_undo_refuses_batches_with_transaction_corrections(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(parse_sparkasse_csv(FIXTURE))
    with database.session() as connection:
        transaction_id = connection.execute(
            "SELECT id FROM transactions WHERE import_id = ? LIMIT 1", (result.import_id,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO audit_events (id, event_type, entity_type, entity_id, created_at) "
            "VALUES ('audit-id', 'correction', 'transaction', ?, '2026-03-01T00:00:00+00:00')",
            (transaction_id,),
        )

    try:
        database.undo_import(result.import_id or "", confirm=True)
    except ValueError as exc:
        assert "dependent transaction corrections" in str(exc)
    else:
        raise AssertionError("undo should refuse dependent corrections")


def test_merchant_alias_is_applied_with_provenance(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    parsed = parse_sparkasse_csv(FIXTURE)
    database.add_merchant_alias("Test Mobility GmbH", "Example Mobility", confidence=0.9)

    result = database.import_file(parsed)

    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        row = connection.execute(
            "SELECT merchant_candidate, merchant_source, merchant_confidence "
            "FROM transactions WHERE import_id = ? ORDER BY booking_date DESC LIMIT 1",
            (result.import_id,),
        ).fetchone()
    assert row == ("Example Mobility", "alias", 0.9)


def test_user_merchant_correction_survives_alias_changes(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(parse_sparkasse_csv(FIXTURE))
    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        transaction_id = connection.execute(
            "SELECT id FROM transactions WHERE import_id = ? LIMIT 1", (result.import_id,)
        ).fetchone()[0]

    database.correct_transaction_merchant(transaction_id, "Owner Confirmed Merchant")
    database.add_merchant_alias("Test Mobility GmbH", "Different Alias")

    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        row = connection.execute(
            "SELECT merchant_candidate, merchant_source, merchant_confidence "
            "FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
    assert row == ("Owner Confirmed Merchant", "user", 1.0)
    with pytest.raises(ValueError, match="dependent transaction corrections"):
        database.undo_import(result.import_id or "", confirm=True)


def test_classification_provenance_keeps_salary_and_generic_credit_distinct(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(parse_sparkasse_csv(FIXTURE))
    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        rows = connection.execute(
            """SELECT booking_text, classification, classification_source,
                      classification_confidence, category_key, category_source
               FROM transactions WHERE import_id = ? ORDER BY booking_date""",
            (result.import_id,),
        ).fetchall()

    salary = next(row for row in rows if row[0] == "LOHN GEHALT")
    assert salary[1:] == (
        "income_candidate",
        "deterministic",
        0.98,
        "income.salary",
        "deterministic",
    )
    assert all(row[4] != "income.salary" for row in rows if row[0] != "LOHN GEHALT")


def test_review_queue_lists_uncertain_transactions_without_raw_text(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    database.import_file(parse_sparkasse_csv(FIXTURE))

    candidates = database.list_review_candidates()

    assert candidates
    assert all(candidate.transaction_id for candidate in candidates)
    assert all(candidate.needs_merchant_review for candidate in candidates)
    assert not hasattr(candidates[0], "description")


def test_reprocessing_preserves_user_classification_correction(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(parse_sparkasse_csv(FIXTURE))
    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        transaction_id = connection.execute(
            "SELECT id FROM transactions WHERE import_id = ? LIMIT 1", (result.import_id,)
        ).fetchone()[0]

    database.correct_transaction_classification(transaction_id, "transfer_candidate", "transfers")
    database.add_classification_rule(
        "Test Mobility",
        "expense_candidate",
        "transport.other",
    )
    database.reprocess_classifications()

    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        row = connection.execute(
            "SELECT classification, category_key, classification_source "
            "FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
    assert row == ("transfer_candidate", "transfers", "user")


def test_refund_candidate_is_not_counted_as_salary_or_income(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    refund = replace(
        parsed.transactions[3],
        booking_text="GUTSCHRIFT",
        purpose="Refund from synthetic merchant",
    )
    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(
        ParseResult(
            source_format=parsed.source_format,
            file_sha256="refund-file",
            transactions=(refund,),
            encoding=parsed.encoding,
        )
    )

    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        row = connection.execute(
            "SELECT classification, category_key FROM transactions WHERE import_id = ?",
            (result.import_id,),
        ).fetchone()
    assert row == ("refund_candidate", "income.refund")
    assert database.monthly_summary("2026-02")["income_minor"] == 0


def test_user_classification_rule_overrides_deterministic_rule(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    database.add_classification_rule(
        "Example Streaming Ltd",
        "expense_candidate",
        "subscriptions.digital",
        confidence=0.99,
        rule_version="user-v2",
    )
    result = database.import_file(parse_sparkasse_csv(FIXTURE))

    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        row = connection.execute(
            """SELECT classification, classification_source, classification_confidence,
                      category_key, category_source
               FROM transactions
               WHERE import_id = ? AND counterparty = ?""",
            (result.import_id, "Example Streaming Ltd"),
        ).fetchone()
    assert row == (
        "expense_candidate",
        "user",
        0.99,
        "subscriptions.digital",
        "user",
    )


def test_user_classification_correction_is_audited_and_blocks_undo(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(parse_sparkasse_csv(FIXTURE))
    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        transaction_id = connection.execute(
            "SELECT id FROM transactions WHERE import_id = ? LIMIT 1", (result.import_id,)
        ).fetchone()[0]

    database.correct_transaction_classification(transaction_id, "transfer_candidate", "transfers")

    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        row = connection.execute(
            "SELECT classification, classification_source, category_key, category_source "
            "FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
    assert row == ("transfer_candidate", "user", "transfers", "user")
    with pytest.raises(ValueError, match="dependent transaction corrections"):
        database.undo_import(result.import_id or "", confirm=True)


def test_import_rolls_back_when_a_transaction_cannot_be_stored(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    invalid = replace(parsed.transactions[1], currency="USD")  # type: ignore[arg-type]
    invalid_result = ParseResult(
        source_format=parsed.source_format,
        file_sha256="invalid-import",
        transactions=(parsed.transactions[0], invalid),
        encoding=parsed.encoding,
    )
    database = Database(tmp_path / "finance.sqlite3")

    with pytest.raises(sqlite3.IntegrityError):
        database.import_file(invalid_result)

    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_reference_duplicates_across_overlapping_exports_are_skipped(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    database = Database(tmp_path / "finance.sqlite3")
    first = database.import_file(parsed)
    overlapping = ParseResult(
        source_format=parsed.source_format,
        file_sha256="another-export-with-overlap",
        transactions=parsed.transactions,
        encoding=parsed.encoding,
    )
    second = database.import_file(overlapping)
    assert first.inserted == 5
    assert second.inserted == 0
    assert second.exact_duplicates == 4
    assert second.possible_duplicates == 1


def test_backup_can_be_opened_and_integrity_checked(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    database = Database(tmp_path / "finance.sqlite3")
    database.import_file(parsed)
    backup_path = database.backup_to(tmp_path / "backups" / "finance-backup.sqlite3")
    with sqlite3.connect(backup_path) as backup:
        result = backup.execute("PRAGMA integrity_check").fetchone()[0]
    assert result == "ok"


def test_health_status_contains_no_financial_values(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    database.import_file(parse_sparkasse_csv(FIXTURE))

    status = database.health_status()

    assert status["schema_version"] == 6
    assert status["import_batches"] == 1
    assert status["transactions"] == 5


def test_financial_overview_is_exact_and_tracks_review_quality(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(parse_sparkasse_csv(FIXTURE))

    overview = database.financial_overview(
        __import__("datetime").date(2026, 3, 1),
        __import__("datetime").date(2026, 4, 1),
        baseline_start=__import__("datetime").date(2026, 2, 1),
        baseline_end=__import__("datetime").date(2026, 3, 1),
    )

    assert overview.expenses_minor == 2823
    assert overview.income_minor == 0
    assert overview.net_cash_flow_minor == -2823
    assert overview.savings_rate_percent is None
    assert overview.baseline_start_date == __import__("datetime").date(2026, 2, 1)
    assert overview.data_quality == "review_needed"

    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        transaction_id = connection.execute(
            "SELECT id FROM transactions WHERE import_id = ? LIMIT 1", (result.import_id,)
        ).fetchone()[0]
    database.correct_transaction_classification(
        transaction_id, "expense_candidate", "food.groceries"
    )
    assert (
        database.financial_overview(
            __import__("datetime").date(2026, 3, 1),
            __import__("datetime").date(2026, 4, 1),
        ).data_quality
        == "review_needed"
    )


def test_transaction_split_requires_exact_reconciliation(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(parse_sparkasse_csv(FIXTURE))
    with sqlite3.connect(tmp_path / "finance.sqlite3") as connection:
        transaction_id, amount = connection.execute(
            "SELECT id, amount_minor FROM transactions WHERE import_id = ? "
            "ORDER BY amount_minor LIMIT 1",
            (result.import_id,),
        ).fetchone()

    with pytest.raises(ValueError, match="reconcile exactly"):
        database.split_transaction(
            transaction_id,
            ((amount + 1, "food.groceries", ""), (-2, "food.restaurants", "")),
        )
    database.split_transaction(
        transaction_id,
        ((amount // 2, "food.groceries", ""), (amount - amount // 2, "food.restaurants", "")),
    )
    with pytest.raises(ValueError, match="already has a split"):
        database.split_transaction(
            transaction_id,
            ((amount, "food.groceries", ""),),
        )


def test_reconciliation_exposes_raw_and_classified_aggregate_totals(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    database.import_file(parse_sparkasse_csv(FIXTURE))

    result = database.reconcile_period(
        __import__("datetime").date(2026, 3, 1), __import__("datetime").date(2026, 4, 1)
    )

    assert result.transaction_count == 3
    assert result.debit_minor == 2823
    assert result.credit_minor == 0
    assert result.expense_minor == 2823
    assert result.transfer_minor == 0


def test_purge_requires_confirmation_and_removes_database(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    database.import_file(parse_sparkasse_csv(FIXTURE))
    with pytest.raises(ValueError, match="explicit confirmation"):
        database.purge()
    assert database.purge(confirm=True) == 1
    assert not database.path.exists()


def test_low_storage_refuses_writes_before_import(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3", minimum_free_bytes=10**18)

    with pytest.raises(RuntimeError, match="insufficient free storage"):
        database.import_file(parse_sparkasse_csv(FIXTURE))


def test_budget_alert_is_rate_limited_per_month_and_threshold(tmp_path: Path) -> None:
    database = Database(tmp_path / "finance.sqlite3")
    database.add_classification_rule(
        "Example Streaming Ltd", "expense_candidate", "subscriptions.digital"
    )
    database.import_file(parse_sparkasse_csv(FIXTURE))
    database.set_budget("2026-03", "subscriptions.digital", 900)
    database.set_budget_alert_preference("subscriptions.digital", 100)

    assert database.budget_alert_due("2026-03", "subscriptions.digital") is True
    assert database.budget_alert_due("2026-03", "subscriptions.digital") is False


def test_dismissed_recurring_candidate_is_not_returned(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    source = parsed.transactions[2]
    recurring = tuple(
        replace(
            source,
            booking_date=__import__("datetime").date(2026, 1 + index, 3),
            dedupe_key=f"decision-{index}",
        )
        for index in range(3)
    )
    database = Database(tmp_path / "finance.sqlite3")
    database.import_file(
        ParseResult(parsed.source_format, "decision-file", recurring, parsed.encoding)
    )
    merchant = database.recurring_candidates()[0].merchant
    database.set_recurring_decision(merchant, "dismissed")
    assert database.recurring_candidates() == ()


def test_database_refuses_a_newer_schema_version(tmp_path: Path) -> None:
    database_path = tmp_path / "future.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 99")
    database = Database(database_path)
    try:
        database.initialize()
    except RuntimeError as exc:
        assert "newer than this app supports" in str(exc)
    else:
        raise AssertionError("newer schema version should be rejected")


def test_identical_content_rows_can_have_distinct_overrides(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    first = replace(
        parsed.transactions[0],
        dedupe_basis="content",
        dedupe_key="same-content-key",
        row_number=2,
    )
    second = replace(first, row_number=3)
    database = Database(tmp_path / "finance.sqlite3")

    result = database.import_file(
        ParseResult(
            source_format=parsed.source_format,
            file_sha256="distinct-override-file",
            transactions=(first, second),
            encoding=parsed.encoding,
        ),
        accept_possible_duplicates=True,
        overrides={
            2: ImportRowOverride(merchant="First Merchant", category_key="food.coffee"),
            3: ImportRowOverride(merchant="Second Merchant", category_key="shopping.general"),
        },
    )

    assert result.inserted == 2
    with database.session() as connection:
        rows = connection.execute(
            "SELECT merchant_candidate, category_key FROM transactions ORDER BY merchant_candidate"
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("First Merchant", "food.coffee"),
        ("Second Merchant", "shopping.general"),
    ]


def test_stale_income_classification_on_a_transfer_category_is_not_income(
    tmp_path: Path,
) -> None:
    from datetime import date

    database = Database(tmp_path / "finance.sqlite3")
    result = database.import_file(parse_sparkasse_csv(FIXTURE))
    with database.session() as connection:
        transaction_id = connection.execute(
            """SELECT id FROM transactions
               WHERE import_id = ? AND amount_minor > 0 LIMIT 1""",
            (result.import_id,),
        ).fetchone()[0]
        connection.execute(
            """UPDATE transactions
               SET category_key = 'transfers.blocked_account',
                   category_source = 'user',
                   classification = 'income_candidate'
               WHERE id = ?""",
            (transaction_id,),
        )

    report = database.period_report(date(2026, 1, 1), date(2027, 1, 1))

    assert report.income_minor == 0
    assert report.transfers_minor >= 123456
    assert all(
        item.category_key != "transfers.blocked_account" for item in report.category_expenses
    )
