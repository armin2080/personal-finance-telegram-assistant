"""Conservative, deterministic transaction classification."""

from __future__ import annotations

from personal_finance_assistant.domain import (
    ClassificationResolution,
    ParsedTransaction,
)

RULE_VERSION = "deterministic-v1"
_TRANSFER_MARKERS = ("ueberweisung", "überweisung", "echtzeit-überweisung")
_REFUND_MARKERS = ("refund", "rückerstattung", "rueckerstattung", "retoure", "erstattung")
_SALARY_MARKERS = ("lohn", "gehalt", "salary")


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(marker in folded for marker in markers)


def classify_transaction(transaction: ParsedTransaction) -> ClassificationResolution:
    """Classify direction conservatively without assigning unsupported categories."""

    text = " ".join((transaction.booking_text, transaction.purpose, transaction.counterparty))
    if _contains_marker(text, _REFUND_MARKERS) and transaction.amount_minor > 0:
        return ClassificationResolution(
            "refund_candidate",
            "deterministic",
            0.9,
            "income.refund",
            "deterministic",
            0.9,
            RULE_VERSION,
        )
    if _contains_marker(transaction.booking_text, _TRANSFER_MARKERS):
        return ClassificationResolution(
            "transfer_candidate",
            "deterministic",
            0.95,
            "transfers",
            "deterministic",
            0.95,
            RULE_VERSION,
        )
    if _contains_marker(transaction.booking_text, _SALARY_MARKERS) and transaction.amount_minor > 0:
        return ClassificationResolution(
            "income_candidate",
            "deterministic",
            0.98,
            "income.salary",
            "deterministic",
            0.98,
            RULE_VERSION,
        )
    if transaction.amount_minor < 0:
        return ClassificationResolution(
            "expense_candidate",
            "deterministic",
            0.75,
            "uncategorized",
            "unreviewed",
            0.0,
            RULE_VERSION,
        )
    if transaction.amount_minor > 0:
        return ClassificationResolution(
            "income_candidate",
            "deterministic",
            0.5,
            "uncategorized",
            "unreviewed",
            0.0,
            RULE_VERSION,
        )
    return ClassificationResolution(
        "unknown", "deterministic", 1.0, "uncategorized", "unreviewed", 0.0, RULE_VERSION
    )
