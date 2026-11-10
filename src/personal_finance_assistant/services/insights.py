"""Deterministic, local-only insights and conservative forecasts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from personal_finance_assistant.domain import (
    BudgetForecast,
    CashFlowForecast,
    MonthlyTrend,
)
from personal_finance_assistant.storage.sqlite import Database


def _month_start(month: str) -> date:
    return date.fromisoformat(f"{month}-01")


def _next_month(month_start: date) -> date:
    return date(
        month_start.year + (month_start.month == 12),
        1 if month_start.month == 12 else month_start.month + 1,
        1,
    )


def _month_sequence(end_month: str, count: int) -> tuple[str, ...]:
    if count < 1 or count > 12:
        raise ValueError("trend month count must be between 1 and 12")
    current = _month_start(end_month)
    result: list[str] = []
    for _ in range(count):
        result.append(current.strftime("%Y-%m"))
        current = date(
            current.year if current.month > 1 else current.year - 1,
            current.month - 1 if current.month > 1 else 12,
            1,
        )
    return tuple(reversed(result))


def forecast_budget(
    database_path: str | Path,
    month: str,
    category_key: str,
    *,
    as_of: date,
    minimum_days: int = 7,
    minimum_observations: int = 3,
) -> BudgetForecast:
    start = _month_start(month)
    month_end = _next_month(start)
    if as_of < start:
        raise ValueError("as_of must be inside or after the forecast month")
    effective_end = min(as_of, month_end)
    observed_days = (effective_end - start).days + (1 if effective_end < month_end else 0)
    used, observations = Database(database_path).category_month_observations(
        month, category_key, effective_end
    )
    sparse = observed_days < minimum_days or observations < minimum_observations
    projected = None if sparse else round(used * (month_end - start).days / observed_days)
    with Database(database_path).session() as connection:
        budget = connection.execute(
            "SELECT limit_minor FROM budgets WHERE month = ? AND category_key = ?",
            (month, category_key),
        ).fetchone()
    limit = None if budget is None else int(budget["limit_minor"])
    return BudgetForecast(
        month,
        category_key,
        as_of,
        observed_days,
        observations,
        used,
        projected,
        limit,
        "sparse" if sparse else "moderate",
        sparse,
    )


def monthly_trend(
    database_path: str | Path, end_month: str, *, months: int = 3
) -> tuple[MonthlyTrend, ...]:
    return Database(database_path).monthly_trends(_month_sequence(end_month, months))


def cash_flow_forecast(
    database_path: str | Path,
    month: str,
    *,
    as_of: date,
    minimum_days: int = 7,
    minimum_observations: int = 3,
) -> CashFlowForecast:
    start = _month_start(month)
    month_end = _next_month(start)
    effective_end = min(as_of, month_end)
    observed_days = (effective_end - start).days + (1 if effective_end < month_end else 0)
    expenses, income, observations = Database(database_path).month_flow_observations(
        month, effective_end
    )
    sparse = observed_days < minimum_days or observations < minimum_observations
    net = income - expenses
    projected = None if sparse else round(net * (month_end - start).days / observed_days)
    return CashFlowForecast(
        month,
        as_of,
        observed_days,
        observations,
        net,
        projected,
        "sparse" if sparse else "moderate",
        sparse,
    )


def anomaly_categories(
    database_path: str | Path, end_month: str, *, baseline_months: int = 3
) -> tuple[tuple[str, int, int], ...]:
    """Find categories at least 50% above their prior average and 500 cents higher."""

    if baseline_months < 2 or baseline_months > 6:
        raise ValueError("baseline month count must be between 2 and 6")
    database = Database(database_path)
    current = _month_start(end_month)
    prior_months = _month_sequence(
        date(
            current.year if current.month > 1 else current.year - 1,
            current.month - 1 if current.month > 1 else 12,
            1,
        ).strftime("%Y-%m"),
        baseline_months,
    )
    current_report = database.period_report(current, _next_month(current))
    prior_reports = [
        database.period_report(_month_start(month), _next_month(_month_start(month)))
        for month in prior_months
    ]
    baseline: dict[str, int] = {}
    for report in prior_reports:
        for item in report.category_expenses:
            baseline[item.category_key] = baseline.get(item.category_key, 0) + item.amount_minor
    current_map = {
        item.category_key: item.amount_minor for item in current_report.category_expenses
    }
    anomalies = []
    for category, amount in current_map.items():
        average = round(baseline.get(category, 0) / baseline_months)
        if amount >= average + 500 and amount * 100 >= average * 150:
            anomalies.append((category, amount, average))
    return tuple(sorted(anomalies))


def local_question(database_path: str | Path, question: str, month: str) -> str:
    """Answer a small allowlisted set of aggregate questions without external AI."""

    normalized = " ".join(question.casefold().split())
    if "spending" in normalized or "expense" in normalized:
        report = Database(database_path).period_report(
            _month_start(month), _next_month(_month_start(month))
        )
        return f"Classified spending for {month}: {report.expenses_minor} cents."
    if "income" in normalized or "earn" in normalized:
        report = Database(database_path).period_report(
            _month_start(month), _next_month(_month_start(month))
        )
        return f"Classified income for {month}: {report.income_minor} cents."
    return "I can answer aggregate spending or income questions for a specified month."


def budget_recommendations(
    database_path: str | Path, month: str, *, as_of: date
) -> tuple[str, ...]:
    """Return explainable review prompts, never autonomous financial advice."""

    database = Database(database_path)
    with database.session() as connection:
        budgets = connection.execute(
            "SELECT category_key FROM budgets WHERE month = ? ORDER BY category_key",
            (month,),
        ).fetchall()
    recommendations: list[str] = []
    for row in budgets:
        forecast = forecast_budget(database_path, month, row["category_key"], as_of=as_of)
        if (
            forecast.projected_minor is not None
            and forecast.limit_minor is not None
            and forecast.projected_minor > forecast.limit_minor
        ):
            recommendations.append(
                f"Review {row['category_key']}: projected classified spend exceeds "
                "the configured budget under the current daily-rate assumption."
            )
    return tuple(recommendations)
