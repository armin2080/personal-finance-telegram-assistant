"""Application services for safe local import previews."""

from __future__ import annotations

from collections import Counter

from personal_finance_assistant.domain import ImportBatchPreview, ParseResult


def build_import_preview(parsed: ParseResult) -> ImportBatchPreview:
    """Summarise a parsed file without exposing individual transaction values."""

    dates = [transaction.booking_date for transaction in parsed.transactions]
    currencies = Counter(transaction.currency for transaction in parsed.transactions)
    payment_types = Counter(transaction.booking_text for transaction in parsed.transactions)
    return ImportBatchPreview(
        source_format=parsed.source_format,
        file_sha256=parsed.file_sha256,
        transaction_count=len(parsed.transactions),
        first_booking_date=min(dates),
        last_booking_date=max(dates),
        currency_counts=tuple(sorted(currencies.items())),
        positive_count=sum(transaction.amount_minor > 0 for transaction in parsed.transactions),
        negative_count=sum(transaction.amount_minor < 0 for transaction in parsed.transactions),
        payment_type_counts=tuple(sorted(payment_types.items())),
        reference_dedupe_count=sum(
            transaction.dedupe_basis == "reference" for transaction in parsed.transactions
        ),
        content_dedupe_count=sum(
            transaction.dedupe_basis == "content" for transaction in parsed.transactions
        ),
    )
