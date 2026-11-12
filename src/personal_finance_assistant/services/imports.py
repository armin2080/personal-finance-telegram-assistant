"""Application services for safe local import previews."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from personal_finance_assistant.domain import (
    DuplicateReview,
    ImportBatchInfo,
    ImportBatchPreview,
    ImportResult,
    ImportRowOverride,
    ImportRowPreview,
    ParseResult,
)


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


def preview_import_rows(
    database_path: str | Path, parsed: ParseResult, *, account_alias: str = "primary"
) -> tuple[tuple[ImportRowPreview, ...], DuplicateReview]:
    from personal_finance_assistant.storage.sqlite import Database

    return Database(database_path).preview_import_rows(parsed, account_alias=account_alias)


def commit_import(
    database_path: str | Path,
    parsed: ParseResult,
    *,
    accept_possible_duplicates: bool = False,
    overrides: dict[int, ImportRowOverride] | None = None,
    account_alias: str = "primary",
) -> ImportResult:
    from personal_finance_assistant.storage.sqlite import Database

    return Database(database_path).import_file(
        parsed,
        account_alias=account_alias,
        accept_possible_duplicates=accept_possible_duplicates,
        overrides=overrides,
    )


def list_import_batches(database_path: str | Path) -> tuple[ImportBatchInfo, ...]:
    from personal_finance_assistant.storage.sqlite import Database

    return Database(database_path).list_imports()


def undo_import_batch(database_path: str | Path, import_id: str, *, confirm: bool) -> int:
    from personal_finance_assistant.storage.sqlite import Database

    return Database(database_path).undo_import(import_id, confirm=confirm)


def data_coverage(database_path: str | Path) -> dict[str, object]:
    from personal_finance_assistant.storage.sqlite import Database

    return Database(database_path).data_coverage()
