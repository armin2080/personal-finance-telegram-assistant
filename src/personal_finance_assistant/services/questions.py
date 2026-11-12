"""Deterministic, local natural-language questions over approved analytics."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from personal_finance_assistant.categories import category_label
from personal_finance_assistant.domain import PeriodReport, QuestionAnswer
from personal_finance_assistant.ingestion.merchant_resolution import normalize_alias_key
from personal_finance_assistant.services.insights import (
    cash_flow_forecast,
    generate_insights,
)
from personal_finance_assistant.storage.sqlite import Database

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "eins": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fuenf": 5,
    "fünf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
    "elf": 11,
    "zwoelf": 12,
    "zwölf": 12,
}
_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "januar": 1,
    "februar": 2,
    "maerz": 3,
    "märz": 3,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "oktober": 10,
    "dezember": 12,
}
_CATEGORY_PATTERNS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("food.coffee",), ("coffee", "kaffee", "espresso", "cafe", "café")),
    (
        ("food.groceries",),
        ("groceries", "grocery", "supermarket", "supermarkt", "lebensmittel"),
    ),
    (
        ("food.restaurants", "food.delivery"),
        ("restaurant", "restaurants", "dining", "eating out", "bistro", "takeaway", "delivery"),
    ),
    (
        (
            "transport.public_transit",
            "transport.fuel",
            "transport.taxi",
            "transport.other",
        ),
        (
            "transport",
            "transit",
            "public transport",
            "bus",
            "train",
            "bahn",
            "fuel",
            "petrol",
            "tanken",
            "taxi",
            "ride",
        ),
    ),
    (
        (
            "shopping.online",
            "shopping.clothing",
            "shopping.electronics",
            "shopping.general",
        ),
        ("shopping", "clothes", "clothing", "electronics", "online shopping", "einkaufen"),
    ),
    (
        ("housing.rent", "housing.utilities", "housing.internet", "housing.household"),
        ("housing", "rent", "miete", "utilities", "strom", "gas", "wasser", "internet"),
    ),
    (
        ("health.pharmacy", "health.medical", "health.fitness"),
        ("health", "pharmacy", "apotheke", "medical", "arzt", "fitness", "gym"),
    ),
    (("insurance",), ("insurance", "versicherung")),
    (
        ("subscriptions.digital", "subscriptions.memberships"),
        ("subscription", "subscriptions", "streaming", "abo", "digital services"),
    ),
    (("leisure",), ("leisure", "entertainment", "cinema", "kino", "freizeit")),
    (("travel",), ("travel", "hotel", "flight", "flights", "urlaub", "reise")),
    (("education",), ("education", "school", "university", "kurs", "studium")),
    (("financial.fees", "fees"), ("fees", "bank fees", "gebühren", "gebuehren")),
    (("gifts_donations",), ("gifts", "donations", "spende", "geschenk")),
)


@dataclass(frozen=True, slots=True)
class ParsedQuestion:
    intent: str
    start: date
    end: date
    baseline_start: date | None = None
    baseline_end: date | None = None
    category_keys: tuple[str, ...] = ()
    merchant: str | None = None
    months: int = 1


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return start, end


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _month_end(month_start: date) -> date:
    return date(
        month_start.year + (month_start.month == 12),
        1 if month_start.month == 12 else month_start.month + 1,
        1,
    )


def _period_label(start: date, end: date) -> str:
    if start.day == 1 and end == _month_end(start):
        return start.strftime("%B %Y")
    if start.month == 1 and start.day == 1 and end == date(start.year + 1, 1, 1):
        return str(start.year)
    return f"{start.isoformat()} to {(end - timedelta(days=1)).isoformat()}"


def _format_eur(minor_units: int) -> str:
    sign = "-" if minor_units < 0 else ""
    value = abs(minor_units)
    whole = f"{value // 100:,}".replace(",", ".")
    return f"{sign}{whole},{value % 100:02d} €"


def _detect_categories(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for categories, markers in _CATEGORY_PATTERNS:
        if any(_marker_present(text, marker) for marker in markers):
            for category in categories:
                if category not in found:
                    found.append(category)
    return tuple(found)


def _marker_present(text: str, marker: str) -> bool:
    folded = _fold(text)
    marker = _fold(marker)
    if " " in marker:
        return marker in folded
    return re.search(rf"(?<![\w]){re.escape(marker)}(?![\w])", folded) is not None


def _detect_merchant(text: str, database_path: str | Path) -> str | None:
    quoted = re.search(r"['\"]([^'\"]{2,80})['\"]", text)
    if quoted:
        return quoted.group(1).strip()
    folded = normalize_alias_key(text)
    best: str | None = None
    for merchant in Database(database_path).find_merchant_names():
        key = normalize_alias_key(merchant)
        if len(key) >= 4 and key in folded and (best is None or len(key) > len(best)):
            best = merchant
    return best


def _parse_date_range(text: str, reference: date) -> tuple[date, date, int]:
    # Explicit YYYY-MM.
    iso_month = re.search(r"\b(20\d{2})-(\d{2})\b", text)
    if iso_month:
        start, end = _month_bounds(int(iso_month.group(1)), int(iso_month.group(2)))
        return start, end, 1

    # Month names, optionally followed by a year.
    for name, month in _MONTH_NAMES.items():
        if _marker_present(text, name):
            year_match = re.search(rf"{re.escape(name)}\s+(20\d{{2}})", text)
            year = int(year_match.group(1)) if year_match else reference.year
            if year_match is None and month > reference.month:
                year -= 1
            start, end = _month_bounds(year, month)
            return start, end, 1

    count_match = re.search(
        r"(?:last|past|previous|letzte[nr]?|vergangene[nr]?)\s+"
        r"(\d+|" + "|".join(_NUMBER_WORDS) + r")\s+"
        r"(months?|monate?n?)",
        text,
    )
    if count_match:
        raw = count_match.group(1)
        count = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
        count = max(1, min(count, 24))
        end = _month_end(date(reference.year, reference.month, 1))
        month_cursor = date(reference.year, reference.month, 1)
        for _ in range(count - 1):
            previous_year, previous_month = _previous_month(month_cursor.year, month_cursor.month)
            month_cursor = date(previous_year, previous_month, 1)
        return month_cursor, end, count

    if any(
        phrase in text
        for phrase in (
            "last month",
            "previous month",
            "letzten monat",
            "letzter monat",
            "voriger monat",
        )
    ):
        previous_year, previous_month = _previous_month(reference.year, reference.month)
        start, end = _month_bounds(previous_year, previous_month)
        return start, end, 1

    if any(
        phrase in text for phrase in ("this year", "current year", "dieses jahr", "diesen jahr")
    ):
        start = date(reference.year, 1, 1)
        return start, date(reference.year + 1, 1, 1), 12

    if any(
        phrase in text for phrase in ("last year", "previous year", "letztes jahr", "voriges jahr")
    ):
        start = date(reference.year - 1, 1, 1)
        return start, date(reference.year, 1, 1), 12

    explicit_year = re.search(r"\b(20\d{2})\b", text)
    if explicit_year:
        year = int(explicit_year.group(1))
        return date(year, 1, 1), date(year + 1, 1, 1), 12

    if "yesterday" in text or "gestern" in text:
        day = reference - timedelta(days=1)
        return day, day + timedelta(days=1), 1
    if "today" in text or "heute" in text:
        return reference, reference + timedelta(days=1), 1

    start = date(reference.year, reference.month, 1)
    return start, _month_end(start), 1


def _baseline_for(start: date, end: date) -> tuple[date, date] | None:
    if start.day == 1 and end == _month_end(start):
        previous_year, previous_month = _previous_month(start.year, start.month)
        return _month_bounds(previous_year, previous_month)
    length = (end - start).days
    if length <= 0:
        return None
    return start - timedelta(days=length), start


def parse_question(
    question: str, reference_month: str, database_path: str | Path
) -> ParsedQuestion:
    text = _fold(question)
    reference_start = date.fromisoformat(f"{reference_month}-01")
    reference = date(
        reference_start.year,
        reference_start.month,
        calendar.monthrange(reference_start.year, reference_start.month)[1],
    )
    start, end, months = _parse_date_range(text, reference)
    categories = _detect_categories(text)
    merchant = _detect_merchant(question, database_path)
    comparison = any(
        marker in text
        for marker in (
            "compare",
            "compared",
            "change",
            "changed",
            "increase",
            "decrease",
            "why did",
            "versus",
            " vs ",
            "vergleich",
            "gestiegen",
            "gesunken",
        )
    )
    baseline = _baseline_for(start, end) if comparison else None
    if comparison and any(
        phrase in text
        for phrase in (
            "compared with last month",
            "compared to last month",
            "than last month",
            "vs last month",
            "versus last month",
        )
    ):
        start = date(reference.year, reference.month, 1)
        end = _month_end(start)
        previous_year, previous_month = _previous_month(start.year, start.month)
        baseline = _month_bounds(previous_year, previous_month)

    if any(
        marker in text
        for marker in (
            "should i buy",
            "what should i buy",
            "is my money good",
            "financial advice",
            "sollte ich kaufen",
        )
    ):
        intent = "clarify"
    elif "budget" in text:
        intent = "budget_remaining"
    elif any(
        marker in text
        for marker in ("by the end of", "might i spend", "forecast", "projected", "ende des monats")
    ):
        intent = "forecast_spending"
    elif any(
        marker in text
        for marker in ("subscription", "subscriptions", "recurring", "abo", "wiederkehrend")
    ) and any(
        marker in text
        for marker in ("increase", "price", "expensive", "teurer", "change", "changed")
    ):
        intent = "recurring_price_change"
    elif any(
        marker in text
        for marker in ("subscription", "subscriptions", "recurring", "abo", "wiederkehrend")
    ):
        intent = "recurring"
    elif any(
        marker in text
        for marker in (
            "uncategorised",
            "uncategorized",
            "not categorised",
            "not categorized",
            "been categorised",
            "been categorized",
            "nicht kategorisiert",
            "without category",
            "ohne kategorie",
        )
    ):
        intent = "uncategorized"
    elif any(
        marker in text
        for marker in (
            "largest",
            "biggest",
            "highest",
            "unusual",
            "one-off",
            "one off",
            "größte",
            "groesste",
            "ungewöhnlich",
            "unusual expenses",
        )
    ):
        intent = "largest_expenses"
    elif any(
        marker in text
        for marker in ("merchant", "merchants", "händler", "haendler", "who received")
    ):
        intent = "top_merchants"
    elif categories and months > 1:
        intent = "spending"
    elif comparison:
        intent = "spending_change"
    elif any(marker in text for marker in ("save", "saved", "savings", "gespart", "ersparnis")):
        intent = "savings"
    elif any(
        marker in text for marker in ("income", "salary", "earn", "verdient", "gehalt", "einkommen")
    ):
        intent = "income"
    elif any(
        marker in text
        for marker in (
            "where did most",
            "breakdown",
            "money go",
            "categories",
            "wo ist",
            "kategorien",
        )
    ):
        intent = "top_categories"
    elif any(
        marker in text
        for marker in (
            "spend",
            "spending",
            "expense",
            "expenses",
            "expenditure",
            "spent",
            "cost",
            "costs",
            "ausgeben",
            "ausgaben",
            "kosten",
        )
    ):
        intent = "spending"
    else:
        intent = "clarify"

    return ParsedQuestion(
        intent=intent,
        start=start,
        end=end,
        baseline_start=baseline[0] if baseline else None,
        baseline_end=baseline[1] if baseline else None,
        category_keys=categories,
        merchant=merchant,
        months=months,
    )


def _report_for(database_path: str | Path, start: date, end: date) -> PeriodReport:
    return Database(database_path).period_report(start, end)


def _spending_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    report = _report_for(database_path, parsed.start, parsed.end)
    label = _period_label(parsed.start, parsed.end)
    if parsed.category_keys:
        categories = [
            item for item in report.category_expenses if item.category_key in parsed.category_keys
        ]
        total = sum(item.amount_minor for item in categories)
        if not categories:
            text = (
                f"No transactions were recorded for {', '.join(category_label(key) for key in parsed.category_keys)} "
                f"in {label}. Total classified spending in the period was {_format_eur(report.expenses_minor)}."
            )
        else:
            lines = [f"Spending on selected categories in {label}: {_format_eur(total)}."]
            for item in sorted(categories, key=lambda entry: entry.amount_minor, reverse=True):
                lines.append(
                    f"• {category_label(item.category_key)}: {_format_eur(item.amount_minor)}"
                )
            if parsed.months > 1:
                lines.append("")
                lines.append("Monthly breakdown:")
                cursor = date(parsed.start.year, parsed.start.month, 1)
                while cursor < parsed.end:
                    month_end = _month_end(cursor)
                    month_report = _report_for(database_path, cursor, month_end)
                    month_total = sum(
                        item.amount_minor
                        for item in month_report.category_expenses
                        if item.category_key in parsed.category_keys
                    )
                    lines.append(f"• {cursor.strftime('%Y-%m')}: {_format_eur(month_total)}")
                    cursor = month_end
            lines.append("")
            lines.append(
                "Classification uses deterministic rules; review uncertain rows before relying on category comparisons."
            )
            text = "\n".join(lines)
        if report.uncategorized_expenses_minor:
            text += (
                f"\n{_format_eur(report.uncategorized_expenses_minor)} of spending in this period "
                "is not yet categorised, so category totals may be incomplete."
            )
        return QuestionAnswer(
            text=text,
            intent="category_spending",
            start_date=parsed.start,
            end_date=parsed.end,
            metric="expenses",
            category_keys=parsed.category_keys,
            confidence="medium" if report.uncategorized_expenses_minor else "high",
            uncertainty=(
                "Uncategorised spending is excluded from category totals."
                if report.uncategorized_expenses_minor
                else None
            ),
        )

    if parsed.merchant:
        merchants = Database(database_path).merchant_expenses(parsed.start, parsed.end, limit=100)
        matching = [
            item for item in merchants if parsed.merchant.casefold() in item.merchant.casefold()
        ]
        total = sum(item.amount_minor for item in matching)
        count = sum(item.transaction_count for item in matching)
        if matching:
            text = (
                f"Spending at {parsed.merchant} in {label}: {_format_eur(total)} "
                f"across {count} classified expense row(s)."
            )
        else:
            text = f"No classified expense rows were found for {parsed.merchant} in {label}."
        return QuestionAnswer(
            text=text,
            intent="merchant_spending",
            start_date=parsed.start,
            end_date=parsed.end,
            metric="expenses",
            merchant=parsed.merchant,
        )

    text = (
        f"From {parsed.start.isoformat()} to {(parsed.end - timedelta(days=1)).isoformat()} "
        f"you spent {_format_eur(report.expenses_minor)} across {report.transaction_count} booked rows."
    )
    if report.uncategorized_expenses_minor:
        text += (
            f" This includes {_format_eur(report.uncategorized_expenses_minor)} that is not yet "
            "categorised; the spending total is complete, but category analysis is incomplete."
        )
    else:
        text += " All spending in this period is categorised."
    text += f" Income of {_format_eur(report.income_minor)} and refunds of {_format_eur(report.refunds_minor)} are reported separately."
    return QuestionAnswer(
        text=text,
        intent="spending",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="expenses",
        confidence="medium" if report.uncategorized_expenses_minor else "high",
        uncertainty=(
            "Uncategorised spending is included in the total but excluded from categories."
            if report.uncategorized_expenses_minor
            else None
        ),
    )


def _top_categories_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    report = _report_for(database_path, parsed.start, parsed.end)
    label = _period_label(parsed.start, parsed.end)
    ordered = sorted(report.category_expenses, key=lambda item: item.amount_minor, reverse=True)
    if not ordered:
        text = f"No classified expenses were recorded for {label}."
    else:
        lines = [
            f"Where your money went in {label}: total spending {_format_eur(report.expenses_minor)}."
        ]
        for item in ordered[:6]:
            share = (
                round(item.amount_minor * 100 / report.expenses_minor)
                if report.expenses_minor
                else 0
            )
            lines.append(
                f"• {category_label(item.category_key)}: {_format_eur(item.amount_minor)} ({share}%)"
            )
        if report.uncategorized_expenses_minor:
            lines.append(
                f"• Uncategorised: {_format_eur(report.uncategorized_expenses_minor)} — review required"
            )
        lines.append("")
        lines.append("Shares use classified expense totals for this period.")
        text = "\n".join(lines)
    return QuestionAnswer(
        text=text,
        intent="top_categories",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="expenses",
        confidence="medium" if report.uncategorized_expenses_minor else "high",
    )


def _top_merchants_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    merchants = Database(database_path).merchant_expenses(parsed.start, parsed.end, limit=8)
    label = _period_label(parsed.start, parsed.end)
    if not merchants:
        text = f"No classified merchant expenses were recorded for {label}."
    else:
        lines = [f"Merchants receiving the most money in {label}:"]
        for item in merchants:
            lines.append(
                f"• {item.merchant}: {_format_eur(item.amount_minor)} across {item.transaction_count} row(s)"
            )
        lines.append("")
        lines.append(
            "Merchant identity is normalised deterministically; ambiguous descriptors remain reviewable."
        )
        text = "\n".join(lines)
    return QuestionAnswer(
        text=text,
        intent="top_merchants",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="expenses",
    )


def _income_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    report = _report_for(database_path, parsed.start, parsed.end)
    label = _period_label(parsed.start, parsed.end)
    text = (
        f"Income in {label}: {_format_eur(report.income_minor)}. "
        f"Refunds are separate: {_format_eur(report.refunds_minor)}. "
        "Only credits with payroll evidence are labelled salary; generic credits remain other income."
    )
    return QuestionAnswer(
        text=text,
        intent="income",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="income",
    )


def _savings_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    overview = Database(database_path).financial_overview(parsed.start, parsed.end)
    label = _period_label(parsed.start, parsed.end)
    rate = (
        f"{overview.savings_rate_percent}%"
        if overview.savings_rate_percent is not None
        else "not available without income"
    )
    text = (
        f"Net cash flow in {label}: {_format_eur(overview.net_cash_flow_minor)} "
        f"(income {_format_eur(overview.income_minor)} + refunds "
        f"{_format_eur(overview.refunds_minor)} − expenses {_format_eur(overview.expenses_minor)} "
        f"− fees {_format_eur(overview.fees_minor)}). Savings rate: {rate}. "
        "Transfers between your own accounts are excluded."
    )
    return QuestionAnswer(
        text=text,
        intent="savings",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="net_cash_flow",
    )


def _uncategorized_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    report = _report_for(database_path, parsed.start, parsed.end)
    rows = Database(database_path).list_transactions(
        parsed.start,
        parsed.end,
        uncategorized_only=True,
        limit=500,
    )
    label = _period_label(parsed.start, parsed.end)
    if not rows:
        text = f"Every transaction in {label} has a category."
    else:
        text = (
            f"{len(rows)} transaction(s) totalling "
            f"{_format_eur(report.uncategorized_expenses_minor)} are not yet categorised in {label}. "
            "They are included in total spending but excluded from category comparisons. "
            "Open Review in the dashboard to assign categories."
        )
    return QuestionAnswer(
        text=text,
        intent="uncategorized",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="uncategorized_expenses",
        confidence="high",
    )


def _largest_expenses_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    rows = Database(database_path).top_expense_transactions(parsed.start, parsed.end, limit=5)
    label = _period_label(parsed.start, parsed.end)
    if not rows:
        text = f"No expense transactions were recorded for {label}."
    else:
        lines = [f"Largest individual expenses in {label}:"]
        for row in rows:
            lines.append(
                f"• {row.booking_date.isoformat()} — {row.merchant}: "
                f"{_format_eur(abs(row.amount_minor))} ({category_label(row.category_key)})"
            )
        lines.append("")
        lines.append(
            "These are the largest single debit rows, ranked by amount; they are not "
            "necessarily statistically unusual."
        )
        text = "\n".join(lines)
    return QuestionAnswer(
        text=text,
        intent="largest_expenses",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="expenses",
    )


def _budget_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    month = parsed.start.strftime("%Y-%m")
    summary = Database(database_path).budget_month_summary(month)
    if not summary.budgets:
        text = (
            f"No budgets are configured for {month}. Create one in the Budgets section "
            "or with `finance-assistant budget set CATEGORY LIMIT_MONTH`."
        )
    else:
        lines = [f"Budget status for {month}:"]
        for status in summary.budgets:
            lines.append(
                f"• {category_label(status.category_key)}: {_format_eur(status.used_minor)} "
                f"of {_format_eur(status.limit_minor)} used, "
                f"{_format_eur(status.remaining_minor)} remaining "
                f"({status.percentage_used}%)."
            )
            if status.projected_minor is not None:
                lines.append(
                    f"  Projected month-end: {_format_eur(status.projected_minor)} "
                    f"({status.elapsed_days}/{status.total_days} days observed)."
                )
        if not summary.complete:
            lines.append("")
            lines.append(summary.disclosure)
        text = "\n".join(lines)
    return QuestionAnswer(
        text=text,
        intent="budget_remaining",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="budget",
        confidence="medium" if not summary.complete else "high",
    )


def _forecast_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    month = parsed.start.strftime("%Y-%m")
    as_of = min(parsed.end - timedelta(days=1), date.today())
    forecast = cash_flow_forecast(database_path, month, as_of=as_of)
    if forecast.sparse_data or forecast.projected_net_minor is None:
        text = (
            f"A projection for {month} is not reliable: only {forecast.observations} "
            f"observations across {forecast.observed_days} observed day(s). "
            "At least 7 days and 3 observations are required."
        )
        confidence = "low"
    else:
        text = (
            f"Observed net flow in {month} is {_format_eur(forecast.net_observed_minor)} "
            f"over {forecast.observed_days} day(s). Projected month-end net flow is "
            f"{_format_eur(forecast.projected_net_minor)} under the current daily-rate "
            "assumption. This is a moderate-confidence estimate and excludes unlinked "
            "reversals and own-account transfers."
        )
        confidence = "moderate"
    return QuestionAnswer(
        text=text,
        intent="forecast_spending",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="net_cash_flow",
        confidence=confidence,
    )


def _spending_change_answer(database_path: str | Path, parsed: ParsedQuestion) -> QuestionAnswer:
    if parsed.baseline_start is None or parsed.baseline_end is None:
        return QuestionAnswer(
            text="I need a comparison period. Ask for example: 'What changed compared with last month?'",
            intent="clarify",
            start_date=parsed.start,
            end_date=parsed.end,
            metric="expenses",
            confidence="low",
        )
    current = _report_for(database_path, parsed.start, parsed.end)
    baseline = _report_for(database_path, parsed.baseline_start, parsed.baseline_end)
    change = current.expenses_minor - baseline.expenses_minor
    percent = round(change * 100 / baseline.expenses_minor) if baseline.expenses_minor else None
    direction = "increased" if change > 0 else "decreased" if change < 0 else "did not change"
    text = (
        f"Classified spending {direction} by {_format_eur(abs(change))} between "
        f"{_period_label(parsed.baseline_start, parsed.baseline_end)} and "
        f"{_period_label(parsed.start, parsed.end)}"
    )
    if percent is not None:
        text += f" ({percent:+d}%)" if change else ""
    text += "."
    baseline_map = {item.category_key: item.amount_minor for item in baseline.category_expenses}
    changes = [
        (item.category_key, item.amount_minor - baseline_map.get(item.category_key, 0))
        for item in current.category_expenses
    ]
    increases = sorted(
        (item for item in changes if item[1] > 0), key=lambda item: item[1], reverse=True
    )
    decreases = sorted((item for item in changes if item[1] < 0), key=lambda item: item[1])
    if increases:
        text += "\nLargest increases:"
        for key, amount in increases[:4]:
            text += f"\n• {category_label(key)}: +{_format_eur(amount)}"
    if decreases:
        text += "\nLargest decreases:"
        for key, amount in decreases[:3]:
            text += f"\n• {category_label(key)}: {_format_eur(amount)}"
    insights = generate_insights(
        database_path,
        parsed.start,
        parsed.end,
        baseline_start=parsed.baseline_start,
        baseline_end=parsed.baseline_end,
    )
    if insights:
        text += "\nEvidence note: " + insights[0].explanation
    return QuestionAnswer(
        text=text,
        intent="spending_change",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="expenses",
        confidence="medium" if current.uncategorized_expenses_minor else "high",
    )


def _recurring_answer(database_path: str | Path) -> QuestionAnswer:
    candidates = Database(database_path).recurring_candidates()
    if not candidates:
        text = (
            "No repeated payment candidate has enough cadence and amount evidence. "
            "Candidates require at least three observations with monthly-to-quarterly spacing."
        )
    else:
        lines = ["Recurring payment candidates (not confirmed subscriptions):"]
        for item in candidates:
            lines.append(
                f"• {item.merchant}: {_format_eur(item.average_amount_minor)} about every "
                f"{item.average_interval_days} days; {item.observations} observations; "
                f"{item.status} confidence"
            )
        lines.append("")
        lines.append(
            "Confirm or dismiss each candidate locally before treating it as a subscription."
        )
        text = "\n".join(lines)
    return QuestionAnswer(
        text=text,
        intent="recurring",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=1),
        metric="recurring",
    )


def _price_change_answer(database_path: str | Path) -> QuestionAnswer:
    changes = Database(database_path).recurring_price_changes()
    if not changes:
        text = "No recurring payment price change has enough evidence."
    else:
        lines = ["Recurring payment price changes with supporting evidence:"]
        for change in changes:
            lines.append(
                f"• {change.merchant}: {_format_eur(change.old_amount_minor)} → "
                f"{_format_eur(change.new_amount_minor)} effective {change.changed_on.isoformat()} "
                f"({change.observations_before} earlier and {change.observations_after} later "
                f"observations; {change.confidence} confidence)."
            )
        lines.append("")
        lines.append("Open the merchant history locally to inspect the supporting transactions.")
        text = "\n".join(lines)
    return QuestionAnswer(
        text=text,
        intent="recurring_price_change",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=1),
        metric="recurring",
    )


def _clarify(parsed: ParsedQuestion) -> QuestionAnswer:
    text = (
        "I can answer deterministic questions about spending, income, categories, merchants, "
        "budgets, recurring payments and savings. I cannot give purchase or investment advice.\n\n"
        'Try: "How much did I spend this month?", "Show me my restaurant spending", '
        '"Where did most of my money go?", "How much budget do I have left?" or '
        '"Did any recurring payment become more expensive?"'
    )
    return QuestionAnswer(
        text=text,
        intent="clarify",
        start_date=parsed.start,
        end_date=parsed.end,
        metric="none",
        confidence="low",
    )


def answer_question(
    database_path: str | Path, question: str, reference_month: str
) -> QuestionAnswer:
    """Parse a question into an approved deterministic use case and answer it."""

    if not question.strip():
        raise ValueError("question is required")
    parsed = parse_question(question, reference_month, database_path)
    if parsed.intent == "clarify":
        return _clarify(parsed)
    if parsed.intent == "budget_remaining":
        return _budget_answer(database_path, parsed)
    if parsed.intent == "forecast_spending":
        return _forecast_answer(database_path, parsed)
    if parsed.intent == "recurring_price_change":
        return _price_change_answer(database_path)
    if parsed.intent == "recurring":
        return _recurring_answer(database_path)
    if parsed.intent == "uncategorized":
        return _uncategorized_answer(database_path, parsed)
    if parsed.intent == "largest_expenses":
        return _largest_expenses_answer(database_path, parsed)
    if parsed.intent == "top_merchants":
        return _top_merchants_answer(database_path, parsed)
    if parsed.intent == "top_categories":
        return _top_categories_answer(database_path, parsed)
    if parsed.intent == "spending_change":
        return _spending_change_answer(database_path, parsed)
    if parsed.intent == "savings":
        return _savings_answer(database_path, parsed)
    if parsed.intent == "income":
        return _income_answer(database_path, parsed)
    if parsed.intent == "spending":
        return _spending_answer(database_path, parsed)
    return _clarify(parsed)
