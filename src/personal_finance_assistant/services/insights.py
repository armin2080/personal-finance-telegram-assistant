"""Deterministic, local-only insights and conservative forecasts."""

from __future__ import annotations

from datetime import date, timedelta
from math import isqrt
from pathlib import Path

from personal_finance_assistant.categories import (
    FIXED_COST_CATEGORIES,
    category_label,
)
from personal_finance_assistant.domain import (
    BudgetForecast,
    CashFlowForecast,
    Insight,
    MonthlyTrend,
    QuestionAnswer,
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


def _format_eur(minor_units: int) -> str:
    sign = "-" if minor_units < 0 else ""
    value = abs(minor_units)
    whole = f"{value // 100:,}".replace(",", ".")
    return f"{sign}{whole},{value % 100:02d} €"


def local_question(database_path: str | Path, question: str, month: str) -> str:
    """Answer a local question through the structured deterministic parser."""

    from personal_finance_assistant.services.questions import answer_question

    try:
        return answer_question(database_path, question, month).text
    except ValueError:
        return (
            "I could not read that question. Try: 'How much did I spend this month?' "
            "or 'Where did most of my money go?'"
        )


def ask_financial_question(database_path: str | Path, question: str, month: str) -> QuestionAnswer:
    from personal_finance_assistant.services.questions import answer_question

    return answer_question(database_path, question, month)


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
        status = database.budget_status(month, row["category_key"], as_of=as_of)
        if status.exceeded:
            recommendations.append(
                f"Review {row['category_key']}: classified spend already exceeds "
                "the configured budget."
            )
            continue
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


def _safe_percentage(part: int, whole: int) -> int:
    return round(part * 100 / whole) if whole else 0


def generate_insights(
    database_path: str | Path,
    start: date,
    end: date,
    *,
    baseline_start: date | None = None,
    baseline_end: date | None = None,
) -> tuple[Insight, ...]:
    """Generate concise, evidence-backed insights from deterministic reports."""

    database = Database(database_path)
    overview = database.financial_overview(
        start,
        end,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
    )
    insights: list[Insight] = []
    if overview.transaction_count == 0:
        insights.append(
            Insight(
                "no-data",
                "No activity in this period",
                "No booked transactions were found for the selected dates.",
                "low",
                start,
                end,
                "high",
                (),
                "Import a booked Sparkasse CSV or choose another period.",
            )
        )
        return tuple(insights)

    report = database.period_report(start, end)
    if report.uncategorized_expenses_minor:
        insights.append(
            Insight(
                "review-needed",
                "Some spending is not yet categorised",
                f"{_format_eur(report.uncategorized_expenses_minor)} of "
                f"{_format_eur(report.expenses_minor)} spending is included in the total "
                "but excluded from category comparisons until it is reviewed.",
                "high",
                start,
                end,
                "high",
                (),
                "Open Review and assign a category to the uncertain transactions.",
            )
        )

    if report.category_expenses:
        largest = max(report.category_expenses, key=lambda item: item.amount_minor)
        evidence = database.category_transaction_ids(start, end, largest.category_key, limit=10)
        share = _safe_percentage(largest.amount_minor, report.expenses_minor)
        insights.append(
            Insight(
                f"largest-category-{largest.category_key}",
                f"Largest spending category: {category_label(largest.category_key)}",
                f"{category_label(largest.category_key)} accounted for "
                f"{_format_eur(largest.amount_minor)} ({share}% of "
                f"{_format_eur(report.expenses_minor)} classified spending).",
                "medium",
                start,
                end,
                "high",
                evidence,
                "Open the category to inspect its transactions.",
            )
        )

    if baseline_start is not None and baseline_end is not None:
        baseline = database.period_report(baseline_start, baseline_end)
        baseline_categories = {
            item.category_key: item.amount_minor for item in baseline.category_expenses
        }
        changes = [
            (
                item.category_key,
                item.amount_minor - baseline_categories.get(item.category_key, 0),
            )
            for item in report.category_expenses
        ]
        increases = [item for item in changes if item[1] > 0]
        decreases = [item for item in changes if item[1] < 0]
        if increases:
            category, increase = max(increases, key=lambda item: item[1])
            evidence = database.category_transaction_ids(start, end, category, limit=10)
            insights.append(
                Insight(
                    f"category-increase-{category}",
                    f"{category_label(category)} increased most",
                    f"{category_label(category)} is {_format_eur(increase)} above "
                    f"{_period_label(baseline_start, baseline_end)}.",
                    "medium",
                    start,
                    end,
                    "high",
                    evidence,
                    "Open the filtered transactions and review the largest contributors.",
                )
            )
        if decreases:
            category, decrease = min(decreases, key=lambda item: item[1])
            evidence = database.category_transaction_ids(start, end, category, limit=10)
            insights.append(
                Insight(
                    f"category-decrease-{category}",
                    f"{category_label(category)} decreased most",
                    f"{category_label(category)} is {_format_eur(abs(decrease))} below "
                    f"{_period_label(baseline_start, baseline_end)}.",
                    "medium",
                    start,
                    end,
                    "high",
                    evidence,
                    "Open the category to confirm whether the change is expected.",
                )
            )
        income_change = report.income_minor - baseline.income_minor
        if income_change:
            direction = "increased" if income_change > 0 else "decreased"
            insights.append(
                Insight(
                    "income-change",
                    f"Income {direction}",
                    f"Classified income {direction} by {_format_eur(abs(income_change))} "
                    f"versus {_period_label(baseline_start, baseline_end)}.",
                    "medium",
                    start,
                    end,
                    "high",
                    (),
                    "Check whether the change reflects a salary change or a one-off credit.",
                )
            )

    merchants = database.merchant_expenses(start, end, limit=5)
    if merchants and report.expenses_minor:
        top = merchants[0]
        share = _safe_percentage(top.amount_minor, report.expenses_minor)
        merchant_evidence: tuple[str, ...] = ()
        insights.append(
            Insight(
                "merchant-concentration",
                f"Top merchant: {top.merchant}",
                f"{top.merchant} received {_format_eur(top.amount_minor)} "
                f"({share}% of classified spending) across {top.transaction_count} row(s).",
                "medium",
                start,
                end,
                "high",
                merchant_evidence,
                "Open merchant history to review the underlying transactions.",
            )
        )

    expense_rows = database.top_expense_transactions(start, end, limit=25)
    if expense_rows:
        amounts = [abs(row.amount_minor) for row in expense_rows]
        mean = sum(amounts) // len(amounts)
        variance = sum((amount - mean) ** 2 for amount in amounts) // len(amounts)
        threshold = mean + 2 * isqrt(variance)
        unusual = [
            row
            for row in expense_rows
            if abs(row.amount_minor) > threshold and abs(row.amount_minor) >= 5000
        ]
        if unusual:
            row = max(unusual, key=lambda item: abs(item.amount_minor))
            insights.append(
                Insight(
                    "unusual-expense",
                    f"Unusually large expense at {row.merchant}",
                    f"A single {_format_eur(abs(row.amount_minor))} payment on "
                    f"{row.booking_date.isoformat()} is above the period's typical range.",
                    "medium",
                    start,
                    end,
                    "medium",
                    (row.transaction_id,),
                    "Open the transaction to confirm whether it is a one-off or a classification error.",
                )
            )

    if report.category_expenses:
        fixed = sum(
            item.amount_minor
            for item in report.category_expenses
            if item.category_key in FIXED_COST_CATEGORIES
        )
        discretionary = report.expenses_minor - fixed
        insights.append(
            Insight(
                "fixed-vs-discretionary",
                "Fixed and discretionary spending",
                f"Fixed commitments were {_format_eur(fixed)} and discretionary spending "
                f"was {_format_eur(discretionary)} in this period.",
                "low",
                start,
                end,
                "medium",
                (),
                "Review discretionary categories first when adjusting a budget.",
            )
        )

    month = start.strftime("%Y-%m")
    for status in database.list_budget_statuses(month):
        if status.exceeded or (
            status.projected_minor is not None and status.projected_minor > status.limit_minor
        ):
            insights.append(
                Insight(
                    f"budget-pace-{status.category_key}",
                    f"Budget pace: {category_label(status.category_key)}",
                    f"{_format_eur(status.used_minor)} of "
                    f"{_format_eur(status.limit_minor)} used "
                    f"({status.percentage_used}%); projected month-end "
                    f"{_format_eur(status.projected_minor or status.used_minor)}.",
                    "high",
                    start,
                    end,
                    "medium",
                    (),
                    "Review the category transactions or adjust the budget.",
                )
            )

    for change in database.recurring_price_changes():
        if start - timedelta(days=365) <= change.changed_on <= end:
            insights.append(
                Insight(
                    f"recurring-price-{change.merchant}",
                    f"{change.merchant} became more expensive",
                    f"{change.merchant} increased from {_format_eur(change.old_amount_minor)} "
                    f"to {_format_eur(change.new_amount_minor)} effective "
                    f"{change.changed_on.isoformat()}, with "
                    f"{change.observations_before} earlier and {change.observations_after} "
                    "later observations.",
                    "medium",
                    start,
                    end,
                    change.confidence,
                    change.supporting_transaction_ids[:10],
                    "Open the merchant history to confirm the new recurring amount.",
                )
            )

    return tuple(insights)


def _period_label(start: date, end: date) -> str:
    return f"{start.isoformat()} to {(end - timedelta(days=1)).isoformat()}"
