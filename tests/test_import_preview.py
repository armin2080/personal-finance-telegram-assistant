from pathlib import Path

from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv
from personal_finance_assistant.services import build_import_preview

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
