"""Budget and recurring-payment application services."""

from __future__ import annotations

from pathlib import Path

from personal_finance_assistant.domain import BudgetStatus, RecurringCandidate, ReviewCandidate
from personal_finance_assistant.storage.sqlite import Database


def set_budget(database_path: str | Path, month: str, category_key: str, limit_minor: int) -> None:
    """Create or replace a non-negative monthly category budget."""

    if len(month) != 7 or month[4] != "-":
        raise ValueError("budget month must use YYYY-MM")
    if not category_key or limit_minor < 0:
        raise ValueError("budget category and non-negative limit are required")
    Database(database_path).set_budget(month, category_key, limit_minor)


def get_budget_status(database_path: str | Path, month: str, category_key: str) -> BudgetStatus:
    return Database(database_path).budget_status(month, category_key)


def find_recurring_candidates(
    database_path: str | Path,
    *,
    minimum_observations: int = 3,
    tolerance_minor: int = 100,
) -> tuple[RecurringCandidate, ...]:
    """Find repeated classified expenses without calling them subscriptions."""

    if minimum_observations < 3 or tolerance_minor < 0:
        raise ValueError("recurrence requires at least three observations")
    return Database(database_path).recurring_candidates(
        minimum_observations=minimum_observations,
        tolerance_minor=tolerance_minor,
    )


def list_review_candidates(
    database_path: str | Path, *, limit: int = 50
) -> tuple[ReviewCandidate, ...]:
    return Database(database_path).list_review_candidates(limit=limit)


def set_budget_alert(
    database_path: str | Path,
    category_key: str,
    threshold_percent: int,
    *,
    enabled: bool = True,
) -> None:
    Database(database_path).set_budget_alert_preference(
        category_key, threshold_percent, enabled=enabled
    )


def decide_recurring(database_path: str | Path, merchant: str, decision: str) -> None:
    Database(database_path).set_recurring_decision(merchant, decision)
