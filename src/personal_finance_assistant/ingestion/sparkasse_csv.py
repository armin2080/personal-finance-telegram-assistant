"""Parser for the observed Sparkasse CSV-CAMT V8-style export.

Important: the supplied file is a semicolon-separated CSV with German column
names. It is not an ISO 20022 CAMT XML document. This adapter is intentionally
specific to the observed export and validates its headers before importing.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from personal_finance_assistant.domain import (
    Classification,
    DedupeBasis,
    ParsedTransaction,
    ParseResult,
)
from personal_finance_assistant.ingestion.merchant_resolution import extract_merchant_candidate

SOURCE_FORMAT = "sparkasse_csv_camt_v8"
REQUIRED_COLUMNS = {
    "Buchungstag",
    "Buchungstext",
    "Betrag",
    "Waehrung",
}
_HEADER_ALIASES = {
    "Gläubiger ID": "Glaeubiger ID",
    "Währung": "Waehrung",
    "Auslagenersatz Rücklastschrift": "Auslagenersatz Ruecklastschrift",
    "Begünstigter/Zahlungspflichtiger": "Beguenstigter/Zahlungspflichtiger",
}

_IBAN_PATTERN = re.compile(r"\b[A-Z]{2}\d{2}(?:[\s-]?[A-Z0-9]){11,30}\b", re.I)
_LONG_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


class ImportValidationError(ValueError):
    """Raised when a file is not a supported export or contains invalid rows."""


def _canonicalize_header(value: str) -> str:
    stripped = value.strip().lstrip("\ufeff")
    return _HEADER_ALIASES.get(stripped, stripped)


def _decode(raw: bytes) -> tuple[str, str]:
    try:
        return raw.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1252"), "cp1252"
        except UnicodeDecodeError as exc:
            raise ImportValidationError("File encoding is not UTF-8 or Windows-1252.") from exc


def _normalise_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\x00", " ")).strip()


def _redact_obvious_identifiers(value: str, source_identifiers: Iterable[str] = ()) -> str:
    """Remove bank-provided identifiers before persisting a memo or party label."""

    value = _IBAN_PATTERN.sub("[IBAN REDACTED]", value)
    value = _LONG_CARD_PATTERN.sub("[CARD NUMBER REDACTED]", value)
    for identifier in source_identifiers:
        identifier = identifier.strip()
        # Avoid deleting ordinary short words or generic labels.
        if len(identifier) >= 6:
            value = re.sub(re.escape(identifier), "[BANK REFERENCE REDACTED]", value, flags=re.I)
    return value[:1000]


def parse_booking_date(value: str | None, *, required: bool = True) -> date | None:
    value = (value or "").strip()
    if not value:
        if required:
            raise ValueError("booking date is missing")
        return None
    for pattern in ("%d.%m.%y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise ValueError("date must use DD.MM.YY, DD.MM.YYYY or YYYY-MM-DD")


def parse_amount_minor(value: str, currency: str) -> int:
    """Parse a localized decimal amount into integer minor units.

    EUR is the first supported currency. No binary floating-point arithmetic is
    used. Values with more than two fractional digits are rounded only when the
    excess digits are zero; otherwise the input is rejected for manual review.
    """

    currency = currency.strip().upper()
    if currency != "EUR":
        raise ValueError("unsupported currency; MVP accepts EUR only")

    text = value.strip().replace("\u00a0", "").replace(" ", "")
    text = text.replace("€", "").replace("EUR", "")
    text = text.replace("−", "-")
    if not text:
        raise ValueError("amount is empty")

    if "," in text and "." in text:
        # The rightmost separator is interpreted as the decimal separator.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif "." in text:
        fractional = text.rsplit(".", 1)[1]
        if len(fractional) == 3 and fractional.isdigit():
            text = text.replace(".", "")

    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("amount is not a valid decimal value") from exc

    if not amount.is_finite():
        raise ValueError("amount must be finite")
    cents = amount * 100
    rounded = cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if cents != rounded:
        raise ValueError("EUR amount has more than two decimal places")
    return int(rounded)


def _classify(amount_minor: int, booking_text: str) -> Classification:
    text = booking_text.upper()
    if any(token in text for token in ("LOHN", "GEHALT", "SALARY")):
        return "income_candidate"
    if "UEBERWEISUNG" in text or "ÜBERWEISUNG" in text:
        return "transfer_candidate"
    if amount_minor < 0:
        return "expense_candidate"
    if amount_minor > 0:
        return "income_candidate"
    return "unknown"


def _payment_channel(booking_text: str) -> str:
    text = booking_text.casefold()
    if "paypal" in text:
        return "paypal"
    if "digitale karte" in text:
        return "digital_wallet"
    if "karten" in text or "card" in text:
        return "card"
    if "lastschrift" in text:
        return "direct_debit"
    if "überweisung" in text or "ueberweisung" in text:
        return "bank_transfer"
    if "bargeld" in text or "geldautomat" in text or "atm" in text:
        return "cash"
    return "unknown"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iter_rows(reader: csv.DictReader[str]) -> Iterable[tuple[int, dict[str, str | None]]]:
    try:
        yield from enumerate(reader, start=2)
    except csv.Error as exc:
        raise ImportValidationError(
            "CSV parsing failed; check the delimiter, quoting, and row structure."
        ) from exc


def _dedupe_data(
    *,
    booking_date: date,
    value_date: date | None,
    booking_text: str,
    purpose: str,
    counterparty: str,
    amount_minor: int,
    currency: str,
    source_reference: str,
) -> tuple[str, DedupeBasis]:
    # Reference-backed keys are stronger. The reference itself is never stored.
    if source_reference:
        material = "|".join(
            (
                "reference",
                booking_date.isoformat(),
                str(amount_minor),
                currency,
                source_reference,
            )
        )
        return _digest(material), "reference"

    # Weak fallback: identical same-day transactions can be legitimate. The
    # storage layer therefore treats this as a possible duplicate, not proof.
    material = "|".join(
        (
            "content",
            booking_date.isoformat(),
            value_date.isoformat() if value_date else "",
            booking_text.casefold(),
            purpose.casefold(),
            counterparty.casefold(),
            str(amount_minor),
            currency,
        )
    )
    return _digest(material), "content"


def parse_sparkasse_csv(path: str | Path) -> ParseResult:
    """Read and validate a Sparkasse CSV-CAMT V8-style export."""

    source_path = Path(path)
    try:
        raw = source_path.read_bytes()
    except OSError as exc:
        raise ImportValidationError(f"cannot read input file: {exc}") from exc
    if not raw:
        raise ImportValidationError("input file is empty")

    text, encoding = _decode(raw)
    reader = csv.DictReader(
        io.StringIO(text, newline=""), delimiter=";", quotechar='"', strict=True
    )
    fieldnames = reader.fieldnames or []
    fieldnames = [_canonicalize_header(fieldname) for fieldname in fieldnames]
    reader.fieldnames = fieldnames
    if len(fieldnames) != len(set(fieldnames)):
        raise ImportValidationError("CSV contains duplicate column headers.")
    headers = set(fieldnames)
    missing = REQUIRED_COLUMNS - headers
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ImportValidationError(
            "unsupported CSV layout; required column(s) missing: " + missing_text
        )

    transactions: list[ParsedTransaction] = []
    errors: list[str] = []
    for row_number, row in _iter_rows(reader):
        if not row or all(not (value or "").strip() for value in row.values()):
            continue
        if None in row:
            errors.append(f"row {row_number}: too many columns")
            continue

        try:
            try:
                booking_date = parse_booking_date(row.get("Buchungstag"))
            except ValueError as exc:
                raise ValueError(f"column Buchungstag: {exc}") from exc
            assert booking_date is not None
            try:
                value_date = parse_booking_date(row.get("Valutadatum"), required=False)
            except ValueError as exc:
                raise ValueError(f"column Valutadatum: {exc}") from exc
            booking_text = _normalise_text(row.get("Buchungstext"))
            if not booking_text:
                raise ValueError("column Buchungstext: value is missing")
            # Read identifiers transiently so they can be removed even when the
            # bank repeats them inside the free-text purpose/counterparty field.
            source_reference = _normalise_text(row.get("Kundenreferenz (End-to-End)"))
            source_identifiers = [
                _normalise_text(row.get(column))
                for column in (
                    "Auftragskonto",
                    "Kontonummer/IBAN",
                    "BIC (SWIFT-Code)",
                    "Glaeubiger ID",
                    "Mandatsreferenz",
                    "Kundenreferenz (End-to-End)",
                    "Sammlerreferenz",
                )
                if _normalise_text(row.get(column))
            ]
            purpose = _redact_obvious_identifiers(
                _normalise_text(row.get("Verwendungszweck")), source_identifiers
            )
            counterparty = _redact_obvious_identifiers(
                _normalise_text(row.get("Beguenstigter/Zahlungspflichtiger")),
                source_identifiers,
            )
            currency = _normalise_text(row.get("Waehrung")).upper()
            if not currency:
                raise ValueError("column Waehrung: value is missing")
            try:
                amount_minor = parse_amount_minor(row.get("Betrag") or "", currency)
            except ValueError as exc:
                raise ValueError(f"column Betrag: {exc}") from exc
            info = _normalise_text(row.get("Info"))
            if info and "umsatz gebucht" not in info.casefold():
                raise ValueError("only booked transactions are supported by this importer")

            # Only the transaction-specific end-to-end reference is a strong
            # dedupe input. A mandate reference identifies a recurring mandate,
            # not one particular booking, so it must not suppress a real payment.
            dedupe_key, dedupe_basis = _dedupe_data(
                booking_date=booking_date,
                value_date=value_date,
                booking_text=booking_text,
                purpose=purpose,
                counterparty=counterparty,
                amount_minor=amount_minor,
                currency=currency,
                source_reference=source_reference,
            )
            merchant = extract_merchant_candidate(counterparty, purpose, booking_text)
            transactions.append(
                ParsedTransaction(
                    booking_date=booking_date,
                    value_date=value_date,
                    booking_text=booking_text,
                    purpose=purpose,
                    counterparty=counterparty,
                    merchant_candidate=merchant,
                    amount_minor=amount_minor,
                    currency=currency,
                    info=info,
                    classification=_classify(amount_minor, booking_text),
                    dedupe_key=dedupe_key,
                    dedupe_basis=dedupe_basis,
                    row_number=row_number,
                    payment_channel=_payment_channel(booking_text),
                )
            )
        except (ValueError, AssertionError) as exc:
            errors.append(f"row {row_number}: {exc}")

    if errors:
        preview = "; ".join(errors[:8])
        suffix = f"; and {len(errors) - 8} more" if len(errors) > 8 else ""
        message = f"CSV validation failed ({len(errors)} row(s)): {preview}{suffix}"
        raise ImportValidationError(message)
    if not transactions:
        raise ImportValidationError("no transactions found in the CSV")

    return ParseResult(
        source_format=SOURCE_FORMAT,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        transactions=tuple(transactions),
        encoding=encoding,
    )
