from pathlib import Path

from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv
from personal_finance_assistant.services import build_import_preview
from personal_finance_assistant.storage.sqlite import Database

FIXTURE = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"


def test_import_preview_contains_aggregates_only() -> None:
    preview = build_import_preview(parse_sparkasse_csv(FIXTURE))

    assert preview.transaction_count == 5
    assert preview.first_booking_date.isoformat() == "2026-02-27"
    assert preview.last_booking_date.isoformat() == "2026-03-05"
    assert preview.currency_counts == (("EUR", 5),)
    assert preview.negative_count == 4
    assert preview.positive_count == 1
    assert preview.reference_dedupe_count == 4
    assert preview.content_dedupe_count == 1
    assert dict(preview.payment_type_counts)["KARTENZAHLUNG"] == 1


def test_row_preview_exposes_suggestions_and_duplicate_markers(tmp_path: Path) -> None:
    parsed = parse_sparkasse_csv(FIXTURE)
    database = Database(tmp_path / "finance.sqlite3")

    rows, review = database.preview_import_rows(parsed)

    assert len(rows) == 5
    assert review.exact_file_match is False
    assert rows[0].merchant == "Test Mobility GmbH"
    assert rows[0].category_key == "transport.other"
    assert rows[0].review_required is True
    assert rows[0].duplicate_reason is None
    assert rows[3].classification == "income_candidate"
    assert rows[3].category_key == "income.salary"

    database.import_file(parsed)
    _, repeated = database.preview_import_rows(parsed)

    assert repeated.exact_file_match is True
