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
