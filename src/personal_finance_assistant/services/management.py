"""Application services for owner review, merchant memory and rule management."""

from __future__ import annotations

from pathlib import Path

from personal_finance_assistant.domain import (
    ClassificationRuleInfo,
    MerchantEntityInfo,
    TransactionRecord,
    TransactionSplit,
)
from personal_finance_assistant.storage.sqlite import Database


def correct_transaction(
    database_path: str | Path,
    transaction_id: str,
    *,
    classification: str,
    category_key: str,
    note: str | None = None,
) -> None:
    Database(database_path).correct_transaction_classification(
        transaction_id, classification, category_key, note=note
    )


def correct_transaction_merchant(
    database_path: str | Path, transaction_id: str, merchant: str
) -> None:
    Database(database_path).correct_transaction_merchant(transaction_id, merchant)


def set_transaction_note(database_path: str | Path, transaction_id: str, note: str) -> None:
    Database(database_path).set_transaction_note(transaction_id, note)


def confirm_transaction(database_path: str | Path, transaction_id: str) -> None:
    Database(database_path).confirm_transaction(transaction_id)


def dismiss_transaction(database_path: str | Path, transaction_id: str) -> None:
    Database(database_path).dismiss_transaction(transaction_id)


def undo_transaction_correction(database_path: str | Path, transaction_id: str) -> None:
    Database(database_path).undo_transaction_correction(transaction_id)


def split_transaction(
    database_path: str | Path,
    transaction_id: str,
    allocations: tuple[tuple[int, str, str], ...],
) -> None:
    Database(database_path).split_transaction(transaction_id, allocations)


def get_transaction_splits(
    database_path: str | Path, transaction_id: str
) -> tuple[TransactionSplit, ...]:
    return Database(database_path).get_transaction_splits(transaction_id)


def delete_split(database_path: str | Path, transaction_id: str) -> int:
    return Database(database_path).delete_split(transaction_id)


def link_transactions(
    database_path: str | Path,
    transaction_id: str,
    linked_transaction_id: str,
    *,
    link_type: str,
) -> None:
    Database(database_path).link_transactions(
        transaction_id, linked_transaction_id, link_type=link_type
    )


def add_rule(
    database_path: str | Path,
    pattern: str,
    classification: str,
    category_key: str,
    *,
    confidence: float = 1.0,
    priority: int = 100,
    merchant_pattern: str | None = None,
    descriptor_pattern: str | None = None,
    payment_channel: str | None = None,
    direction: str = "any",
    payment_type: str | None = None,
    label: str = "",
) -> None:
    Database(database_path).add_classification_rule(
        pattern,
        classification,
        category_key,
        confidence=confidence,
        priority=priority,
        merchant_pattern=merchant_pattern,
        descriptor_pattern=descriptor_pattern,
        payment_channel=payment_channel,
        direction=direction,
        payment_type=payment_type,
        label=label,
    )


def list_rules(database_path: str | Path) -> tuple[ClassificationRuleInfo, ...]:
    return Database(database_path).list_classification_rules()


def delete_rule(database_path: str | Path, rule_id: str) -> bool:
    return Database(database_path).delete_classification_rule(rule_id)


def add_merchant_alias(
    database_path: str | Path,
    alias: str,
    canonical_name: str,
    *,
    confidence: float = 1.0,
    default_category_key: str | None = None,
) -> None:
    Database(database_path).add_merchant_alias(
        alias,
        canonical_name,
        confidence=confidence,
        default_category_key=default_category_key,
    )


def remove_merchant_alias(database_path: str | Path, alias: str) -> int:
    return Database(database_path).remove_merchant_alias(alias)


def set_merchant_default_category(
    database_path: str | Path, canonical_name: str, category_key: str | None
) -> None:
    Database(database_path).set_merchant_default_category(canonical_name, category_key)


def merge_merchants(
    database_path: str | Path,
    source_canonical: str,
    target_canonical: str,
    *,
    confirm: bool = False,
) -> int:
    return Database(database_path).merge_merchants(
        source_canonical, target_canonical, confirm=confirm
    )


def list_merchants(database_path: str | Path) -> tuple[MerchantEntityInfo, ...]:
    return Database(database_path).list_merchant_entities()


def merchant_history(
    database_path: str | Path, merchant: str, *, limit: int = 100
) -> tuple[TransactionRecord, ...]:
    from datetime import date

    records, _ = Database(database_path).transaction_page(
        date(1900, 1, 1),
        date(2100, 1, 1),
        merchant=merchant,
        limit=limit,
        sort_by="date",
        sort_dir="desc",
    )
    return records
