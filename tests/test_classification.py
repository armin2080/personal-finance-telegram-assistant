from dataclasses import replace
from pathlib import Path

from personal_finance_assistant.ingestion.classification import classify_transaction
from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv

FIXTURE = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"


def test_transfer_classification_is_separate_from_category() -> None:
    transaction = parse_sparkasse_csv(FIXTURE).transactions[-1]

    result = classify_transaction(transaction)

    assert result.classification == "transfer_candidate"
    assert result.category_key == "transfers"
    assert result.classification_source == "deterministic"


def test_positive_non_salary_credit_remains_uncategorized_income() -> None:
    transaction = replace(
        parse_sparkasse_csv(FIXTURE).transactions[3],
        booking_text="GUTSCHRIFT",
        purpose="Synthetic non-salary credit",
    )

    result = classify_transaction(transaction)

    assert result.classification == "income_candidate"
    assert result.category_key == "income.other"
    assert result.category_confidence < 0.8


def test_blocked_account_payout_is_a_transfer_not_income() -> None:
    transaction = replace(
        parse_sparkasse_csv(FIXTURE).transactions[3],
        booking_text="GUTSCHRIFT",
        purpose="MONATLICHE AUSZAHLUNG SPERRKONTO",
        counterparty="Blocked Account Service",
        merchant_candidate="Blocked Account Service",
        amount_minor=99200,
    )

    result = classify_transaction(transaction)

    assert result.classification == "transfer_candidate"
    assert result.category_key == "transfers.blocked_account"
    assert result.classification_confidence >= 0.9
    assert result.evidence == "blocked account payout"


def test_blocked_account_marker_is_case_and_language_tolerant() -> None:
    base = parse_sparkasse_csv(FIXTURE).transactions[3]

    for purpose in ("Blocked Account monthly payout", "Sperrkonto Auszahlung"):
        result = classify_transaction(
            replace(
                base,
                booking_text="GUTSCHRIFT",
                purpose=purpose,
                counterparty="Synthetic provider",
                merchant_candidate="Synthetic provider",
                amount_minor=99200,
            )
        )
        assert result.classification == "transfer_candidate"
        assert result.category_key == "transfers.blocked_account"


def test_ordinary_credit_without_blocked_account_evidence_stays_income() -> None:
    result = classify_transaction(
        replace(
            parse_sparkasse_csv(FIXTURE).transactions[3],
            booking_text="GUTSCHRIFT",
            purpose="Synthetic marketplace payout",
            counterparty="Synthetic Marketplace",
            merchant_candidate="Synthetic Marketplace",
        )
    )

    assert result.classification == "income_candidate"
    assert result.category_key != "transfers.blocked_account"
