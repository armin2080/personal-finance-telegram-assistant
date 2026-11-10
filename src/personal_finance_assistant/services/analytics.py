"""Application-level analytics use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from personal_finance_assistant.domain import LedgerReconciliation, PeriodReport
from personal_finance_assistant.storage.sqlite import Database


@dataclass(frozen=True, slots=True)
class MonthlySummary:
    """A recorded month summary, with the period label used by the interface."""

    month: str
    month_label: str
    expenses_minor: int
    income_minor: int
    transaction_count: int


def get_period_report(database_path: str | Path, start: date, end: date) -> PeriodReport:
    """Return classified totals for a half-open booking-date period."""

    return Database(database_path).period_report(start, end)


def reconcile_period(database_path: str | Path, start: date, end: date) -> LedgerReconciliation:
    return Database(database_path).reconcile_period(start, end)


def get_month_report(database_path: str | Path, year: int, month: int) -> PeriodReport:
    """Return one calendar month's report using explicit date boundaries."""

    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return get_period_report(database_path, start, end)


def get_current_month_summary(
    database_path: str | Path,
    timezone: str = "Europe/Berlin",
    *,
    now: datetime | None = None,
) -> MonthlySummary:
    """Calculate the current calendar month's candidate totals.

    ``now`` is injectable to make the use case deterministic in tests. The
    database is queried through the storage boundary; Telegram handlers do not
    need to know about SQL or date-boundary rules.
    """

    zone = ZoneInfo(timezone)
    if now is not None and (now.tzinfo is None or now.utcoffset() is None):
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(zone) if now else datetime.now(zone)
    month = local_now.strftime("%Y-%m")
    result = Database(database_path).monthly_summary(month)
    return MonthlySummary(
        month=month,
        month_label=local_now.strftime("%B %Y"),
        expenses_minor=result["expenses_minor"],
        income_minor=result["income_minor"],
        transaction_count=result["transaction_count"],
    )
