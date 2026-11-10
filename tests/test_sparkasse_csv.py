from pathlib import Path

import pytest

from personal_finance_assistant.ingestion.sparkasse_csv import (
    ImportValidationError,
    parse_amount_minor,
    parse_sparkasse_csv,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"


def test_parses_observed_csv_layout() -> None:
    result = parse_sparkasse_csv(FIXTURE)
    assert result.source_format == "sparkasse_csv_camt_v8"
    assert len(result.transactions) == 5
    assert result.transactions[0].amount_minor == -120
    assert result.transactions[3].amount_minor == 123456
    assert result.transactions[0].classification == "expense_candidate"
    assert result.transactions[3].classification == "income_candidate"


def test_german_and_international_decimal_formats() -> None:
    assert parse_amount_minor("-1,20", "EUR") == -120
    assert parse_amount_minor("1.234,56", "EUR") == 123456
    assert parse_amount_minor("1,234.56", "EUR") == 123456
    assert parse_amount_minor("-17.04", "EUR") == -1704


def test_unsupported_currency_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported currency"):
        parse_amount_minor("10,00", "USD")


def test_missing_required_header_is_rejected(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.csv"
    bad_file.write_text('"Buchungstag";"Buchungstext"\n"10.11.26";"CARD"\n', encoding="utf-8")
    with pytest.raises(ImportValidationError, match="required column"):
        parse_sparkasse_csv(bad_file)


def test_obvious_identifiers_are_not_kept_in_description() -> None:
    result = parse_sparkasse_csv(FIXTURE)
    transaction = result.transactions[0]
    assert "DE00000000000000000000" not in transaction.purpose


def test_pending_transaction_status_is_rejected(tmp_path: Path) -> None:
    content = FIXTURE.read_text(encoding="utf-8")
    pending = content.replace("Umsatz gebucht", "Umsatz vorgemerkt", 1)
    pending_file = tmp_path / "pending.csv"
    pending_file.write_text(pending, encoding="utf-8")
    with pytest.raises(ImportValidationError, match="only booked transactions"):
        parse_sparkasse_csv(pending_file)


def test_malformed_quoted_csv_returns_safe_validation_error(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.csv"
    malformed.write_text(
        '"Buchungstag";"Buchungstext";"Betrag";"Waehrung"\n"10.03.26;"CARD";"-1,00";"EUR"\n',
        encoding="utf-8",
    )
    with pytest.raises(ImportValidationError, match="CSV parsing failed"):
        parse_sparkasse_csv(malformed)


def test_duplicate_headers_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text(
        '"Buchungstag";"Buchungstag";"Buchungstext";"Betrag";"Waehrung"\n',
        encoding="utf-8",
    )
    with pytest.raises(ImportValidationError, match="duplicate column headers"):
        parse_sparkasse_csv(duplicate)


def test_documented_accented_header_aliases_are_supported(tmp_path: Path) -> None:
    content = FIXTURE.read_text(encoding="utf-8").replace('"Waehrung"', '"Währung"')
    aliased_file = tmp_path / "aliased.csv"
    aliased_file.write_text(content, encoding="utf-8")

    result = parse_sparkasse_csv(aliased_file)

    assert len(result.transactions) == 5


def test_cp1252_bom_escaped_quotes_and_multiline_fields_are_supported(
    tmp_path: Path,
) -> None:
    content = (
        '"Buchungstag";"Buchungstext";"Verwendungszweck";"Betrag";"Währung"\n'
        '"10.03.26";"KARTENZAHLUNG";"Café: Say ""hello""\\nand continue";"-1,20";"EUR"\n'
    ).replace("\\n", "\n")
    cp1252_file = tmp_path / "cp1252.csv"
    cp1252_file.write_bytes(content.encode("cp1252"))

    result = parse_sparkasse_csv(cp1252_file)

    assert result.encoding == "cp1252"
    assert result.transactions[0].purpose == 'Café: Say "hello" and continue'

    bom_file = tmp_path / "utf8-bom.csv"
    bom_file.write_bytes(("\ufeff" + content.replace("Café", "Cafe")).encode("utf-8"))
    assert parse_sparkasse_csv(bom_file).encoding == "utf-8-sig"


def test_invalid_amount_identifies_row_and_column_without_value(tmp_path: Path) -> None:
    content = (
        '"Buchungstag";"Buchungstext";"Betrag";"Währung"\n"10.03.26";"CARD";"not-a-number";"EUR"\n'
    )
    source_file = tmp_path / "invalid.csv"
    source_file.write_text(content, encoding="utf-8")

    with pytest.raises(ImportValidationError, match=r"row 2:.*column Betrag"):
        parse_sparkasse_csv(source_file)

    with pytest.raises(ImportValidationError) as error:
        parse_sparkasse_csv(source_file)
    assert "not-a-number" not in str(error.value)
