"""Application services for the approved private CSV upload flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from personal_finance_assistant.domain import (
    DuplicateReview,
    ImportBatchPreview,
    ImportResult,
    ParseResult,
    PeriodReport,
)
from personal_finance_assistant.ingestion.sparkasse_csv import parse_sparkasse_csv
from personal_finance_assistant.services.imports import build_import_preview
from personal_finance_assistant.storage.sqlite import Database


@dataclass(frozen=True, slots=True)
class UploadPreview:
    parsed: ParseResult
    preview: ImportBatchPreview
    duplicates: DuplicateReview


def build_upload_preview(database_path: str | Path, source_path: str | Path) -> UploadPreview:
    """Parse an uploaded source and return safe aggregates before any write."""

    parsed = parse_sparkasse_csv(source_path)
    database = Database(database_path)
    return UploadPreview(parsed, build_import_preview(parsed), database.review_import(parsed))


def commit_upload(
    database_path: str | Path, upload: UploadPreview, *, minimum_free_bytes: int
) -> tuple[ImportResult, PeriodReport]:
    """Commit a previously previewed upload and return its aggregate report."""

    database = Database(database_path, minimum_free_bytes=minimum_free_bytes)
    result = database.import_file(upload.parsed)
    report = database.period_report(
        upload.preview.first_booking_date,
        upload.preview.last_booking_date + timedelta(days=1),
    )
    return result, report
