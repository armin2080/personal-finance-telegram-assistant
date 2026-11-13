"""Loopback-only FastAPI adapter for the local finance cockpit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from personal_finance_assistant.categories import CATEGORY_REGISTRY, category_label
from personal_finance_assistant.domain import (
    DuplicateReview,
    ImportRowOverride,
    ImportRowPreview,
    ParseResult,
    TransactionRecord,
)
from personal_finance_assistant.ingestion.sparkasse_csv import (
    ImportValidationError,
    parse_sparkasse_csv_bytes,
)
from personal_finance_assistant.services.analytics import (
    check_database_integrity,
    get_financial_overview,
    get_period_report,
    list_transactions_page,
    merchant_expenses,
    weekly_trend,
)
from personal_finance_assistant.services.budgets import (
    decide_recurring,
    delete_budget,
    find_recurring_candidates,
    find_recurring_price_changes,
    get_budget_month_summary,
    list_review_candidates,
    set_budget,
    set_budget_alert,
)
from personal_finance_assistant.services.imports import (
    commit_import,
    data_coverage,
    list_import_batches,
    preview_import_rows,
    undo_import_batch,
)
from personal_finance_assistant.services.insights import (
    ask_financial_question,
    generate_insights,
    monthly_trend,
)
from personal_finance_assistant.services.management import (
    add_merchant_alias,
    add_rule,
    confirm_transaction,
    correct_transaction,
    correct_transaction_merchant,
    delete_rule,
    delete_split,
    dismiss_transaction,
    get_transaction_splits,
    link_transactions,
    list_merchants,
    list_rules,
    merge_merchants,
    remove_merchant_alias,
    reprocess_rules,
    set_merchant_default_category,
    set_transaction_note,
    split_transaction,
    undo_transaction_correction,
)

STATIC_DIR = Path(__file__).parent / "static"
MAX_IMPORT_BYTES = 10 * 1024 * 1024
IMPORT_PREVIEW_TTL_SECONDS = 30 * 60
MAX_IMPORT_PREVIEWS = 4


@dataclass(slots=True)
class _ImportPreview:
    parsed: ParseResult
    rows: tuple[ImportRowPreview, ...]
    duplicate_review: DuplicateReview
    file_name: str
    created_at: float


_IMPORT_PREVIEWS: dict[str, _ImportPreview] = {}
_IMPORT_PREVIEWS_LOCK = Lock()


def _prune_import_previews(now: float) -> None:
    expired = [
        preview_id
        for preview_id, preview in _IMPORT_PREVIEWS.items()
        if now - preview.created_at > IMPORT_PREVIEW_TTL_SECONDS
    ]
    for preview_id in expired:
        _IMPORT_PREVIEWS.pop(preview_id, None)
    while len(_IMPORT_PREVIEWS) > MAX_IMPORT_PREVIEWS:
        oldest = min(_IMPORT_PREVIEWS, key=lambda item: _IMPORT_PREVIEWS[item].created_at)
        _IMPORT_PREVIEWS.pop(oldest, None)


def _store_import_preview(
    parsed: ParseResult,
    rows: tuple[ImportRowPreview, ...],
    duplicate_review: DuplicateReview,
    file_name: str,
) -> str:
    preview_id = uuid4().hex
    now = monotonic()
    with _IMPORT_PREVIEWS_LOCK:
        _prune_import_previews(now)
        _IMPORT_PREVIEWS[preview_id] = _ImportPreview(
            parsed=parsed,
            rows=rows,
            duplicate_review=duplicate_review,
            file_name=file_name,
            created_at=now,
        )
    return preview_id


def _get_import_preview(preview_id: str) -> _ImportPreview | None:
    now = monotonic()
    with _IMPORT_PREVIEWS_LOCK:
        _prune_import_previews(now)
        return _IMPORT_PREVIEWS.get(preview_id)


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field} must use YYYY-MM-DD") from exc


def _money(minor_units: int) -> dict[str, int | str]:
    return {"minor": minor_units, "currency": "EUR"}


def _share(part: int, whole: int) -> int:
    return round(part * 100 / whole) if whole else 0


def _transaction_payload(record: TransactionRecord) -> dict[str, object]:
    return {
        "id": record.transaction_id,
        "date": record.booking_date,
        "amount": _money(record.amount_minor),
        "merchant": record.merchant,
        "counterparty": record.counterparty,
        "description": record.description,
        "classification": record.classification,
        "category": record.category_key,
        "category_label": category_label(record.category_key),
        "review_status": record.review_status,
        "payment_channel": record.payment_channel,
        "merchant_source": record.merchant_source,
        "merchant_confidence": record.merchant_confidence,
        "classification_source": record.classification_source,
        "classification_confidence": record.classification_confidence,
        "category_source": record.category_source,
        "category_confidence": record.category_confidence,
        "evidence": record.evidence,
        "note": record.note,
        "has_split": record.has_split,
        "split_categories": [
            {"key": key, "label": category_label(key)} for key in record.split_categories
        ],
    }


def _import_row_payload(row: ImportRowPreview) -> dict[str, object]:
    return {
        "row_number": row.row_number,
        "date": row.booking_date.isoformat(),
        "value_date": row.value_date.isoformat() if row.value_date else None,
        "amount": _money(row.amount_minor),
        "booking_text": row.booking_text,
        "description": row.purpose,
        "counterparty": row.counterparty,
        "merchant": row.merchant,
        "merchant_source": row.merchant_source,
        "merchant_confidence": row.merchant_confidence,
        "classification": row.classification,
        "classification_source": row.classification_source,
        "classification_confidence": row.classification_confidence,
        "category": row.category_key,
        "category_label": category_label(row.category_key),
        "category_source": row.category_source,
        "category_confidence": row.category_confidence,
        "review_required": row.review_required,
        "duplicate_reason": row.duplicate_reason,
        "payment_channel": row.payment_channel,
        "evidence": row.evidence,
        "merchant_learnable": row.merchant_learnable,
        "descriptor_pattern": row.descriptor_pattern,
    }


class ImportRowOverrideBody(BaseModel):
    row_number: int
    merchant: str | None = None
    classification: str | None = None
    category_key: str | None = None
    note: str | None = None
    remember: str | None = None


class ImportCommitBody(BaseModel):
    preview_id: str
    accept_possible_duplicates: bool = False
    overrides: list[ImportRowOverrideBody] = Field(default_factory=list)


class CorrectBody(BaseModel):
    classification: str | None = None
    category_key: str | None = None
    merchant: str | None = None
    note: str | None = None
    apply_to_future: bool = False
    rule_priority: int = Field(default=150, ge=0)


class NoteBody(BaseModel):
    note: str


class SplitAllocation(BaseModel):
    amount_minor: int
    category_key: str
    note: str = ""


class SplitBody(BaseModel):
    allocations: list[SplitAllocation] = Field(min_length=1)


class LinkBody(BaseModel):
    linked_transaction_id: str
    link_type: str


class RuleBody(BaseModel):
    pattern: str = ""
    classification: str = "expense_candidate"
    category_key: str
    confidence: float = 1.0
    priority: int = 100
    merchant_pattern: str | None = None
    descriptor_pattern: str | None = None
    payment_channel: str | None = None
    direction: str = "any"
    payment_type: str | None = None
    label: str = ""


class BudgetBody(BaseModel):
    month: str
    category_key: str
    limit_minor: int


class BudgetAlertBody(BaseModel):
    category_key: str
    threshold_percent: int
    enabled: bool = True


class RecurringDecisionBody(BaseModel):
    merchant: str
    decision: str


class MerchantAliasBody(BaseModel):
    alias: str
    canonical_name: str
    confidence: float = 1.0
    default_category_key: str | None = None


class MerchantDefaultBody(BaseModel):
    canonical_name: str
    category_key: str | None = None


class MerchantMergeBody(BaseModel):
    source_canonical: str
    target_canonical: str
    confirm: bool = False


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    month: str | None = None


def create_app(database_path: str | Path) -> FastAPI:
    """Create a dashboard app bound to one local SQLite database."""

    app = FastAPI(title="Personal Finance Cockpit", docs_url="/api/docs")

    @app.get("/api/health")
    def health() -> dict[str, int | bool | str | None]:
        from personal_finance_assistant.storage.sqlite import Database

        return Database(database_path).health_status()

    @app.get("/api/coverage")
    def coverage() -> dict[str, object]:
        return data_coverage(database_path)

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
            report = get_period_report(database_path, start_date, end_date)
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
            "categorized_expenses": _money(result.categorized_expenses_minor),
            "uncategorized_expenses": _money(result.uncategorized_expenses_minor),
            "refunds": _money(result.refunds_minor),
            "transfers": _money(result.transfers_minor),
            "fees": _money(result.fees_minor),
            "reversals": _money(result.reversals_minor),
            "cash_withdrawals": _money(result.cash_withdrawals_minor),
            "savings": _money(result.savings_minor),
            "net_cash_flow": _money(result.net_cash_flow_minor),
            "savings_rate_percent": result.savings_rate_percent,
            "transaction_count": result.transaction_count,
            "data_quality": result.data_quality,
            "categories": [
                {
                    "key": item.category_key,
                    "label": category_label(item.category_key),
                    "amount": _money(item.amount_minor),
                    "share_percent": _share(item.amount_minor, report.expenses_minor),
                }
                for item in sorted(
                    report.category_expenses, key=lambda item: item.amount_minor, reverse=True
                )
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
        merchant: str | None = None,
        uncategorized: bool = False,
        ids: str | None = None,
        sort: str = "date",
        direction: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        try:
            rows, total = list_transactions_page(
                database_path,
                _parse_date(start, "start"),
                _parse_date(end, "end"),
                search=search,
                category_key=category,
                classification=classification,
                review_status=review_status,
                merchant=merchant,
                uncategorized_only=uncategorized,
                transaction_ids=tuple(item for item in (ids or "").split(",") if item) or None,
                sort_by=sort,
                sort_dir=direction,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "transactions": [_transaction_payload(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "sort": sort,
            "direction": direction,
        }

    @app.get("/api/review")
    def review(limit: int = 200) -> dict[str, object]:
        try:
            candidates = list_review_candidates(database_path, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "review": [
                {
                    "id": item.transaction_id,
                    "date": item.booking_date,
                    "amount": _money(item.amount_minor),
                    "merchant": item.merchant,
                    "classification": item.classification,
                    "category": item.category_key,
                    "needs_merchant_review": item.needs_merchant_review,
                    "needs_classification_review": item.needs_classification_review,
                }
                for item in candidates
            ]
        }

    @app.post("/api/transactions/{transaction_id}/correct")
    def correct(transaction_id: str, body: CorrectBody) -> dict[str, object]:
        try:
            if body.merchant:
                correct_transaction_merchant(database_path, transaction_id, body.merchant)
            if body.classification or body.category_key:
                if not body.classification or not body.category_key:
                    raise ValueError("classification and category_key are required together")
                correct_transaction(
                    database_path,
                    transaction_id,
                    classification=body.classification,
                    category_key=body.category_key,
                    note=body.note,
                )
            elif body.note is not None:
                set_transaction_note(database_path, transaction_id, body.note)
            if body.apply_to_future:
                merchant = body.merchant
                if not merchant:
                    raise ValueError("apply_to_future requires a merchant")
                add_rule(
                    database_path,
                    pattern=merchant,
                    classification=body.classification or "expense_candidate",
                    category_key=body.category_key or "uncategorized",
                    merchant_pattern=merchant,
                    priority=body.rule_priority,
                    label=f"Learned from transaction {transaction_id}",
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "updated", "transaction_id": transaction_id}

    @app.post("/api/transactions/{transaction_id}/note")
    def note(transaction_id: str, body: NoteBody) -> dict[str, object]:
        try:
            set_transaction_note(database_path, transaction_id, body.note)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "updated"}

    @app.post("/api/transactions/{transaction_id}/confirm")
    def confirm(transaction_id: str) -> dict[str, object]:
        try:
            confirm_transaction(database_path, transaction_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "confirmed"}

    @app.post("/api/transactions/{transaction_id}/dismiss")
    def dismiss(transaction_id: str) -> dict[str, object]:
        try:
            dismiss_transaction(database_path, transaction_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "dismissed"}

    @app.post("/api/transactions/{transaction_id}/undo")
    def undo_correction(transaction_id: str) -> dict[str, object]:
        try:
            undo_transaction_correction(database_path, transaction_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "recomputed"}

    @app.get("/api/transactions/{transaction_id}/splits")
    def splits(transaction_id: str) -> dict[str, object]:
        return {
            "splits": [
                {
                    "id": item.split_id,
                    "amount": _money(item.amount_minor),
                    "category": item.category_key,
                    "category_label": category_label(item.category_key),
                    "note": item.note,
                }
                for item in get_transaction_splits(database_path, transaction_id)
            ]
        }

    @app.post("/api/transactions/{transaction_id}/split")
    def create_split(transaction_id: str, body: SplitBody) -> dict[str, object]:
        try:
            split_transaction(
                database_path,
                transaction_id,
                tuple(
                    (item.amount_minor, item.category_key, item.note) for item in body.allocations
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "split"}

    @app.delete("/api/transactions/{transaction_id}/split")
    def remove_split(transaction_id: str) -> dict[str, object]:
        try:
            deleted = delete_split(database_path, transaction_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "removed", "deleted": deleted}

    @app.post("/api/transactions/{transaction_id}/link")
    def link(transaction_id: str, body: LinkBody) -> dict[str, object]:
        try:
            link_transactions(
                database_path,
                transaction_id,
                body.linked_transaction_id,
                link_type=body.link_type,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "linked"}

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

    @app.get("/api/weekly-trends")
    def weekly_trends(start: str, end: str) -> dict[str, object]:
        try:
            result = weekly_trend(
                database_path,
                _parse_date(start, "start"),
                _parse_date(end, "end"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "weeks": [
                {
                    "start": item.week_start,
                    "expenses": _money(item.expenses_minor),
                    "income": _money(item.income_minor),
                }
                for item in result
            ]
        }

    @app.get("/api/merchants")
    def merchants(start: str, end: str, limit: int = 20) -> dict[str, object]:
        try:
            result = merchant_expenses(
                database_path,
                _parse_date(start, "start"),
                _parse_date(end, "end"),
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "merchants": [
                {
                    "merchant": item.merchant,
                    "amount": _money(item.amount_minor),
                    "transaction_count": item.transaction_count,
                }
                for item in result
            ]
        }

    @app.get("/api/merchant-entities")
    def merchant_entities() -> dict[str, object]:
        return {
            "merchants": [
                {
                    "id": item.entity_id,
                    "canonical_name": item.canonical_name,
                    "default_category": item.default_category_key,
                    "default_category_label": category_label(item.default_category_key)
                    if item.default_category_key
                    else None,
                    "aliases": list(item.aliases),
                    "transaction_count": item.transaction_count,
                    "total": _money(item.total_minor),
                }
                for item in list_merchants(database_path)
            ]
        }

    @app.post("/api/merchant-entities/alias")
    def merchant_alias(body: MerchantAliasBody) -> dict[str, object]:
        try:
            add_merchant_alias(
                database_path,
                body.alias,
                body.canonical_name,
                confidence=body.confidence,
                default_category_key=body.default_category_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved"}

    @app.delete("/api/merchant-entities/alias")
    def merchant_alias_delete(alias: str) -> dict[str, object]:
        return {"removed": remove_merchant_alias(database_path, alias)}

    @app.post("/api/merchant-entities/default")
    def merchant_default(body: MerchantDefaultBody) -> dict[str, object]:
        try:
            set_merchant_default_category(database_path, body.canonical_name, body.category_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved"}

    @app.post("/api/merchant-entities/merge")
    def merchant_merge(body: MerchantMergeBody) -> dict[str, object]:
        try:
            moved = merge_merchants(
                database_path,
                body.source_canonical,
                body.target_canonical,
                confirm=body.confirm,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "merged", "transactions_updated": moved}

    @app.get("/api/rules")
    def rules() -> dict[str, object]:
        return {
            "rules": [
                {
                    "id": item.rule_id,
                    "pattern": item.pattern,
                    "classification": item.classification,
                    "category": item.category_key,
                    "category_label": category_label(item.category_key),
                    "confidence": item.confidence,
                    "priority": item.priority,
                    "match_type": item.match_type,
                    "merchant_pattern": item.merchant_pattern,
                    "descriptor_pattern": item.descriptor_pattern,
                    "payment_channel": item.payment_channel,
                    "direction": item.direction,
                    "payment_type": item.payment_type,
                    "enabled": item.enabled,
                    "label": item.label,
                }
                for item in list_rules(database_path)
            ]
        }

    @app.post("/api/rules")
    def rule_create(body: RuleBody) -> dict[str, object]:
        try:
            add_rule(
                database_path,
                body.pattern,
                body.classification,
                body.category_key,
                confidence=body.confidence,
                priority=body.priority,
                merchant_pattern=body.merchant_pattern,
                descriptor_pattern=body.descriptor_pattern,
                payment_channel=body.payment_channel,
                direction=body.direction,
                payment_type=body.payment_type,
                label=body.label,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved"}

    @app.delete("/api/rules/{rule_id}")
    def rule_delete(rule_id: str) -> dict[str, object]:
        return {"deleted": delete_rule(database_path, rule_id)}

    @app.post("/api/reprocess")
    def reprocess() -> dict[str, object]:
        return {"updated": reprocess_rules(database_path)}

    @app.get("/api/budgets")
    def budgets(month: str) -> dict[str, object]:
        try:
            summary = get_budget_month_summary(database_path, month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "month": summary.month,
            "total_expenses": _money(summary.total_expenses_minor),
            "categorized_expenses": _money(summary.categorized_expenses_minor),
            "uncategorized_expenses": _money(summary.uncategorized_expenses_minor),
            "complete": summary.complete,
            "disclosure": summary.disclosure,
            "budgets": [
                {
                    "category": item.category_key,
                    "category_label": category_label(item.category_key),
                    "limit": _money(item.limit_minor),
                    "used": _money(item.used_minor),
                    "remaining": _money(item.remaining_minor),
                    "exceeded": item.exceeded,
                    "percentage_used": item.percentage_used,
                    "elapsed_days": item.elapsed_days,
                    "total_days": item.total_days,
                    "projected": _money(item.projected_minor)
                    if item.projected_minor is not None
                    else None,
                    "uncategorized_expenses": _money(item.uncategorized_expenses_minor),
                    "complete": item.complete,
                    "status": item.status,
                    "alert_threshold_percent": item.alert_threshold_percent,
                }
                for item in summary.budgets
            ],
        }

    @app.post("/api/budgets")
    def budget_save(body: BudgetBody) -> dict[str, object]:
        try:
            set_budget(database_path, body.month, body.category_key, body.limit_minor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved"}

    @app.delete("/api/budgets")
    def budget_delete(month: str, category: str) -> dict[str, object]:
        return {"deleted": delete_budget(database_path, month, category)}

    @app.post("/api/budgets/alert")
    def budget_alert(body: BudgetAlertBody) -> dict[str, object]:
        try:
            set_budget_alert(
                database_path,
                body.category_key,
                body.threshold_percent,
                enabled=body.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved"}

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
                    "status": item.status,
                    "latest_amount": _money(item.latest_amount_minor)
                    if item.latest_amount_minor is not None
                    else None,
                    "previous_amount": _money(item.previous_amount_minor)
                    if item.previous_amount_minor is not None
                    else None,
                    "supporting_transaction_ids": list(item.supporting_transaction_ids),
                }
                for item in find_recurring_candidates(database_path)
            ],
            "price_changes": [
                {
                    "merchant": item.merchant,
                    "old_amount": _money(item.old_amount_minor),
                    "new_amount": _money(item.new_amount_minor),
                    "changed_on": item.changed_on,
                    "observations_before": item.observations_before,
                    "observations_after": item.observations_after,
                    "confidence": item.confidence,
                    "supporting_transaction_ids": list(item.supporting_transaction_ids),
                }
                for item in find_recurring_price_changes(database_path)
            ],
        }

    @app.post("/api/recurring/decision")
    def recurring_decision(body: RecurringDecisionBody) -> dict[str, object]:
        try:
            decide_recurring(database_path, body.merchant, body.decision)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved"}

    @app.post("/api/ask")
    def ask(body: AskBody) -> dict[str, object]:
        month = body.month or date.today().strftime("%Y-%m")
        try:
            answer = ask_financial_question(database_path, body.question, month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "text": answer.text,
            "intent": answer.intent,
            "period": {"start": answer.start_date, "end": answer.end_date},
            "metric": answer.metric,
            "category_keys": list(answer.category_keys),
            "merchant": answer.merchant,
            "confidence": answer.confidence,
            "uncertainty": answer.uncertainty,
        }

    @app.post("/api/imports/preview")
    def import_preview(file: Annotated[UploadFile, File()]) -> dict[str, object]:
        file_name = Path(file.filename or "statement.csv").name[:120]
        if not file_name.lower().endswith((".csv", ".txt")):
            raise HTTPException(status_code=400, detail="Upload a .csv file exported by your bank.")
        raw = file.file.read(MAX_IMPORT_BYTES + 1)
        if len(raw) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="The file is larger than 10 MB.")
        try:
            parsed = parse_sparkasse_csv_bytes(raw)
        except ImportValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        rows, duplicate_review = preview_import_rows(database_path, parsed)
        existing = next(
            (
                item
                for item in list_import_batches(database_path)
                if item.file_sha256 == parsed.file_sha256
            ),
            None,
        )
        preview_id = _store_import_preview(parsed, rows, duplicate_review, file_name)
        total_in = sum(item.amount_minor for item in parsed.transactions if item.amount_minor > 0)
        total_out = -sum(item.amount_minor for item in parsed.transactions if item.amount_minor < 0)
        return {
            "preview_id": preview_id,
            "file_name": file_name,
            "source_format": parsed.source_format,
            "encoding": parsed.encoding,
            "transaction_count": len(parsed.transactions),
            "first_date": min(item.booking_date for item in parsed.transactions).isoformat(),
            "last_date": max(item.booking_date for item in parsed.transactions).isoformat(),
            "total_in": _money(total_in),
            "total_out": _money(total_out),
            "uncategorized_count": sum(1 for row in rows if row.category_key == "uncategorized"),
            "review_required_count": sum(1 for row in rows if row.review_required),
            "exact_file_match": duplicate_review.exact_file_match,
            "reference_matches": duplicate_review.reference_matches,
            "possible_duplicate_count": len(duplicate_review.possible_duplicates),
            "existing_import": (
                {
                    "import_id": existing.import_id,
                    "inserted_count": existing.inserted_count,
                    "exact_duplicate_count": existing.exact_duplicate_count,
                    "possible_duplicate_count": existing.possible_duplicate_count,
                    "status": existing.status,
                }
                if existing
                else None
            ),
            "rows": [_import_row_payload(row) for row in rows],
        }

    @app.post("/api/imports/commit")
    def import_commit(body: ImportCommitBody) -> dict[str, object]:
        preview = _get_import_preview(body.preview_id)
        if preview is None:
            raise HTTPException(
                status_code=410, detail="Import preview expired. Upload the file again."
            )
        transactions_by_row = {
            transaction.row_number: transaction for transaction in preview.parsed.transactions
        }
        preview_rows_by_number = {row.row_number: row for row in preview.rows}
        overrides: dict[int, ImportRowOverride] = {}
        for item in body.overrides:
            transaction = transactions_by_row.get(item.row_number)
            if transaction is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Row {item.row_number} is not part of this import.",
                )
            remember: Literal["merchant", "descriptor"] | None = None
            if item.remember == "merchant":
                remember = "merchant"
            elif item.remember == "descriptor":
                remember = "descriptor"
            elif item.remember:
                raise HTTPException(
                    status_code=400,
                    detail="remember must be merchant or descriptor.",
                )
            merchant = item.merchant.strip() if item.merchant and item.merchant.strip() else None
            classification = (
                item.classification.strip()
                if item.classification and item.classification.strip()
                else None
            )
            category = (
                item.category_key.strip()
                if item.category_key and item.category_key.strip()
                else None
            )
            note = item.note.strip() if item.note and item.note.strip() else None
            if (
                merchant is None
                and classification is None
                and category is None
                and note is None
                and remember is None
            ):
                continue
            overrides[transaction.row_number] = ImportRowOverride(
                merchant=merchant,
                classification=classification,
                category_key=category,
                note=note,
                remember=remember,
            )
        try:
            result = commit_import(
                database_path,
                preview.parsed,
                accept_possible_duplicates=body.accept_possible_duplicates,
                overrides=overrides,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        learned: list[str] = []
        learning_errors: list[str] = []
        for item in body.overrides:
            if item.remember not in {"merchant", "descriptor"}:
                continue
            transaction = transactions_by_row[item.row_number]
            row = preview_rows_by_number[item.row_number]
            category = (item.category_key or row.category_key).strip()
            classification = (item.classification or row.classification).strip()
            merchant = (item.merchant or row.merchant).strip()
            try:
                if category == "uncategorized":
                    raise ValueError("choose a category before remembering this row")
                if item.remember == "merchant":
                    if not row.merchant_learnable:
                        raise ValueError(
                            "this merchant is ambiguous; remember the description instead"
                        )
                    add_merchant_alias(
                        database_path,
                        alias=transaction.merchant_candidate,
                        canonical_name=merchant,
                        default_category_key=category,
                    )
                    add_rule(
                        database_path,
                        pattern=merchant,
                        classification=classification,
                        category_key=category,
                        merchant_pattern=merchant,
                        priority=200,
                        label="Learned from import review",
                    )
                    learned.append(f"merchant: {merchant}")
                else:
                    pattern = row.descriptor_pattern.strip()
                    if not pattern:
                        raise ValueError(
                            "this description is too generic; remember the merchant instead"
                        )
                    add_rule(
                        database_path,
                        pattern=pattern,
                        classification=classification,
                        category_key=category,
                        descriptor_pattern=pattern,
                        payment_channel=(
                            row.payment_channel if row.payment_channel != "unknown" else None
                        ),
                        priority=200,
                        label="Learned from import review",
                    )
                    learned.append(f"description: {pattern}")
            except ValueError as exc:
                learning_errors.append(f"Row {item.row_number}: {exc}")
        return {
            "import_id": result.import_id,
            "inserted": result.inserted,
            "exact_duplicates": result.exact_duplicates,
            "possible_duplicates": result.possible_duplicates,
            "status": result.status,
            "already_imported_file": result.already_imported_file,
            "learned": learned,
            "learning_errors": learning_errors,
        }

    @app.get("/api/imports")
    def imports() -> dict[str, object]:
        return {
            "imports": [
                {
                    "id": item.import_id,
                    "source_format": item.source_format,
                    "encoding": item.encoding,
                    "transaction_count": item.transaction_count,
                    "inserted_count": item.inserted_count,
                    "exact_duplicate_count": item.exact_duplicate_count,
                    "possible_duplicate_count": item.possible_duplicate_count,
                    "status": item.status,
                    "created_at": item.created_at,
                }
                for item in list_import_batches(database_path)
            ]
        }

    @app.post("/api/imports/{import_id}/undo")
    def import_undo(import_id: str, confirm: bool = False) -> dict[str, object]:
        try:
            deleted = undo_import_batch(database_path, import_id, confirm=confirm)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "undone", "deleted": deleted}

    @app.get("/api/integrity")
    def integrity() -> dict[str, object]:
        return check_database_integrity(database_path)

    @app.get("/", response_class=FileResponse)
    def dashboard() -> Path:
        return STATIC_DIR / "index.html"

    @app.get("/manifest.webmanifest", response_class=FileResponse)
    def manifest() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/sw.js", response_class=FileResponse)
    def service_worker() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="text/javascript",
            headers={
                "Cache-Control": "no-store",
                "Service-Worker-Allowed": "/",
            },
        )

    @app.get("/assets/{filename}", response_class=FileResponse)
    def asset(filename: str) -> Path:
        path = STATIC_DIR / filename
        if path.parent != STATIC_DIR or not path.is_file():
            raise HTTPException(status_code=404, detail="asset not found")
        return path

    return app
