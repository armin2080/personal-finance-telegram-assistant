"""Loopback-only FastAPI adapter for the local finance dashboard."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from personal_finance_assistant.categories import CATEGORY_REGISTRY
from personal_finance_assistant.services.analytics import get_financial_overview
from personal_finance_assistant.services.budgets import (
    find_recurring_candidates,
    list_budget_statuses,
)
from personal_finance_assistant.services.insights import generate_insights, monthly_trend
from personal_finance_assistant.storage.sqlite import Database

STATIC_DIR = Path(__file__).parent / "static"


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field} must use YYYY-MM-DD") from exc


def _money(minor_units: int) -> dict[str, int | str]:
    return {"minor": minor_units, "currency": "EUR"}


def create_app(database_path: str | Path) -> FastAPI:
    """Create a dashboard app bound to one local SQLite database."""

    app = FastAPI(title="Personal Finance Cockpit", docs_url="/api/docs")

    @app.get("/api/health")
    def health() -> dict[str, int | bool]:
        return Database(database_path).health_status()

    @app.get("/api/categories")
    def categories() -> dict[str, str]:
        return CATEGORY_REGISTRY

    @app.get("/api/overview")
    def overview(
        start: Annotated[str, Query(description="Inclusive booking date")] = "",
        end: Annotated[str, Query(description="Exclusive booking date")] = "",
        baseline_start: str | None = None,
        baseline_end: str | None = None,
    ) -> dict[str, object]:
        if not start or not end:
            raise HTTPException(status_code=400, detail="start and end are required")
        start_date = _parse_date(start, "start")
        end_date = _parse_date(end, "end")
        baseline_start_date = (
            _parse_date(baseline_start, "baseline_start") if baseline_start else None
        )
        baseline_end_date = _parse_date(baseline_end, "baseline_end") if baseline_end else None
        try:
            result = get_financial_overview(
                database_path,
                start_date,
                end_date,
                baseline_start=baseline_start_date,
                baseline_end=baseline_end_date,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "period": {"start": result.start_date, "end": result.end_date},
            "baseline": (
                {"start": result.baseline_start_date, "end": result.baseline_end_date}
                if result.baseline_start_date
                else None
            ),
            "income": _money(result.income_minor),
            "expenses": _money(result.expenses_minor),
            "refunds": _money(result.refunds_minor),
            "transfers": _money(result.transfers_minor),
            "fees": _money(result.fees_minor),
            "net_cash_flow": _money(result.net_cash_flow_minor),
            "savings_rate_percent": result.savings_rate_percent,
            "transaction_count": result.transaction_count,
            "data_quality": result.data_quality,
            "categories": [
                {"key": item.category_key, "amount": _money(item.amount_minor)}
                for item in Database(database_path)
                .period_report(start_date, end_date)
                .category_expenses
            ],
        }

    @app.get("/api/transactions")
    def transactions(
        start: str,
        end: str,
        search: str | None = None,
        category: str | None = None,
        classification: str | None = None,
        review_status: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        try:
            rows = Database(database_path).list_transactions(
                _parse_date(start, "start"),
                _parse_date(end, "end"),
                search=search,
                category_key=category,
                classification=classification,
                review_status=review_status,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "transactions": [
                {
                    "id": row.transaction_id,
                    "date": row.booking_date,
                    "amount": _money(row.amount_minor),
                    "merchant": row.merchant,
                    "counterparty": row.counterparty,
                    "description": row.description,
                    "classification": row.classification,
                    "category": row.category_key,
                    "review_status": row.review_status,
                    "payment_channel": row.payment_channel,
                }
                for row in rows
            ]
        }

    @app.get("/api/insights")
    def insights(
        start: str,
        end: str,
        baseline_start: str | None = None,
        baseline_end: str | None = None,
    ) -> dict[str, object]:
        start_date = _parse_date(start, "start")
        end_date = _parse_date(end, "end")
        try:
            items = generate_insights(
                database_path,
                start_date,
                end_date,
                baseline_start=_parse_date(baseline_start, "baseline_start")
                if baseline_start
                else None,
                baseline_end=_parse_date(baseline_end, "baseline_end") if baseline_end else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "insights": [
                {
                    "id": item.insight_id,
                    "title": item.title,
                    "explanation": item.explanation,
                    "relevance": item.relevance,
                    "period": {"start": item.start_date, "end": item.end_date},
                    "confidence": item.confidence,
                    "supporting_transaction_ids": item.supporting_transaction_ids,
                    "next_action": item.next_action,
                }
                for item in items
            ]
        }

    @app.get("/api/trends")
    def trends(end_month: str, months: int = 6) -> dict[str, object]:
        try:
            result = monthly_trend(database_path, end_month, months=months)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "months": [
                {
                    "month": item.month,
                    "expenses": _money(item.expenses_minor),
                    "income": _money(item.income_minor),
                }
                for item in result
            ]
        }

    @app.get("/api/budgets")
    def budgets(month: str) -> dict[str, object]:
        try:
            result = list_budget_statuses(database_path, month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "budgets": [
                {
                    "category": item.category_key,
                    "limit": _money(item.limit_minor),
                    "used": _money(item.used_minor),
                    "remaining": _money(item.remaining_minor),
                    "exceeded": item.exceeded,
                }
                for item in result
            ]
        }

    @app.get("/api/recurring")
    def recurring() -> dict[str, object]:
        return {
            "candidates": [
                {
                    "merchant": item.merchant,
                    "observations": item.observations,
                    "average_amount": _money(item.average_amount_minor),
                    "first_date": item.first_date,
                    "last_date": item.last_date,
                    "average_interval_days": item.average_interval_days,
                    "confidence": item.confidence,
                    "confirmed": item.confirmed,
                    "regularity": item.regularity,
                }
                for item in find_recurring_candidates(database_path)
            ]
        }

    @app.get("/", response_class=FileResponse)
    def dashboard() -> Path:
        return STATIC_DIR / "index.html"

    @app.get("/assets/{filename}", response_class=FileResponse)
    def asset(filename: str) -> Path:
        path = STATIC_DIR / filename
        if path.parent != STATIC_DIR or not path.is_file():
            raise HTTPException(status_code=404, detail="asset not found")
        return path

    return app
