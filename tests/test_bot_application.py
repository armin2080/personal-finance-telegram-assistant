import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from personal_finance_assistant.bot.application import (
    _format_eur,
    _is_authorized,
    _report_text,
    _settings,
    _validate_upload_metadata,
    document_upload,
    upload_callback,
)
from personal_finance_assistant.domain import CategoryTotal, PeriodReport
from personal_finance_assistant.services.uploads import build_upload_preview
from personal_finance_assistant.settings import Settings


def _settings_for(user_ids: frozenset[int]) -> Settings:
    return Settings(None, user_ids, Path("finance.sqlite3"), "Europe/Berlin", "INFO")


def test_authorization_requires_allowlisted_private_chat() -> None:
    settings = _settings_for(frozenset({123}))
    allowed = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
    )
    group = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="group"),
    )
    unknown = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_chat=SimpleNamespace(type="private"),
    )

    assert _is_authorized(allowed, settings)
    assert not _is_authorized(group, settings)
    assert not _is_authorized(unknown, settings)


def test_report_text_is_aggregate_and_explains_inclusions() -> None:
    report = PeriodReport(
        start_date=__import__("datetime").date(2026, 3, 1),
        end_date=__import__("datetime").date(2026, 4, 1),
        expenses_minor=1200,
        income_minor=5000,
        refunds_minor=300,
        transfers_minor=900,
        uncategorized_expenses_minor=1200,
        category_expenses=(CategoryTotal("uncategorized", 1200),),
        transaction_count=3,
    )

    text = _report_text(report, "Spending report")

    assert "Spending report" in text
    assert "Transfers excluded from totals" in text
    assert "booking dates" in text
    assert "1200" not in text
    assert "12,00 €" in text


def test_settings_helper_rejects_missing_context_key() -> None:
    with pytest.raises(KeyError):
        _settings(SimpleNamespace(application=SimpleNamespace(bot_data={})))


def test_currency_formatting_is_minor_unit_safe() -> None:
    assert _format_eur(123456) == "1.234,56 €"
    assert _format_eur(-9) == "-0,09 €"


def test_upload_metadata_accepts_only_small_csv_documents() -> None:
    assert _validate_upload_metadata("statement.CSV", 100) is None
    assert _validate_upload_metadata("statement.pdf", 100) is not None
    assert _validate_upload_metadata("statement.csv", 101, max_upload_bytes=100) is not None
    assert _validate_upload_metadata(None, 100) is not None


def test_document_upload_rejects_non_csv_without_downloading(tmp_path: Path) -> None:
    replies: list[str] = []

    async def reply_text(text: str, **_: object) -> None:
        replies.append(text)

    message = SimpleNamespace(
        document=SimpleNamespace(file_name="statement.pdf", file_size=100),
        reply_text=reply_text,
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        effective_message=message,
    )
    settings = _settings_for(frozenset({123}))
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"settings": settings}),
        user_data={},
    )

    asyncio.run(document_upload(update, context))

    assert replies == ["Only CSV bank exports are accepted."]


def test_document_upload_processes_csv_and_returns_aggregates(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"
    database_path = tmp_path / "finance.sqlite3"
    replies: list[str] = []

    async def reply_text(text: str, **_: object) -> None:
        replies.append(text)

    async def download_to_drive(*, custom_path: Path) -> None:
        custom_path.write_bytes(fixture.read_bytes())

    async def get_file():
        return SimpleNamespace(download_to_drive=download_to_drive)

    message = SimpleNamespace(
        document=SimpleNamespace(
            file_name="private-statement.csv",
            file_size=fixture.stat().st_size,
            get_file=get_file,
        ),
        reply_text=reply_text,
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        effective_message=message,
    )
    settings = Settings(
        None,
        frozenset({123}),
        database_path,
        "Europe/Berlin",
        "INFO",
        minimum_free_bytes=0,
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"settings": settings}),
        user_data={},
    )

    asyncio.run(document_upload(update, context))

    assert len(replies) == 1
    assert "CSV preview ready." in replies[0]
    assert "Rows: 5" in replies[0]
    assert "private-statement.csv" not in replies[0]
    assert "CARD" not in replies[0]

    edited: list[str] = []

    async def answer() -> None:
        return None

    async def edit_message_text(text: str) -> None:
        edited.append(text)

    callback_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=SimpleNamespace(
            data="upload:confirm",
            answer=answer,
            edit_message_text=edit_message_text,
        ),
    )
    asyncio.run(upload_callback(callback_update, context))

    assert "CSV imported locally." in edited[0]
    assert "CARD" not in edited[0]


def test_upload_callback_cancel_discards_preview(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"
    database_path = tmp_path / "finance.sqlite3"
    settings = Settings(
        None,
        frozenset({123}),
        database_path,
        "Europe/Berlin",
        "INFO",
        minimum_free_bytes=0,
    )
    upload = build_upload_preview(database_path, fixture)
    edited: list[str] = []

    async def answer() -> None:
        return None

    async def edit_message_text(text: str) -> None:
        edited.append(text)

    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"settings": settings}),
        user_data={
            "upload_preview": upload,
            "upload_preview_created": datetime.now(UTC),
        },
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=SimpleNamespace(
            data="upload:cancel",
            answer=answer,
            edit_message_text=edit_message_text,
        ),
    )

    asyncio.run(upload_callback(update, context))

    assert edited == ["Import cancelled. No database changes were made."]
    assert context.user_data == {}


def test_upload_callback_expires_preview_without_importing(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"
    database_path = tmp_path / "finance.sqlite3"
    settings = Settings(
        None,
        frozenset({123}),
        database_path,
        "Europe/Berlin",
        "INFO",
        minimum_free_bytes=0,
    )
    upload = build_upload_preview(database_path, fixture)
    edited: list[str] = []

    async def answer() -> None:
        return None

    async def edit_message_text(text: str) -> None:
        edited.append(text)

    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"settings": settings}),
        user_data={
            "upload_preview": upload,
            "upload_preview_created": datetime.now(UTC) - timedelta(minutes=11),
        },
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=SimpleNamespace(
            data="upload:confirm",
            answer=answer,
            edit_message_text=edit_message_text,
        ),
    )

    asyncio.run(upload_callback(update, context))

    assert edited == ["This upload preview expired. Send the CSV again."]
    assert context.user_data == {}


def test_upload_callback_rejects_unknown_action(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "sparkasse_sample.csv"
    database_path = tmp_path / "finance.sqlite3"
    settings = Settings(
        None,
        frozenset({123}),
        database_path,
        "Europe/Berlin",
        "INFO",
        minimum_free_bytes=0,
    )
    upload = build_upload_preview(database_path, fixture)
    edited: list[str] = []

    async def answer() -> None:
        return None

    async def edit_message_text(text: str) -> None:
        edited.append(text)

    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"settings": settings}),
        user_data={
            "upload_preview": upload,
            "upload_preview_created": datetime.now(UTC),
        },
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=SimpleNamespace(
            data="upload:unexpected",
            answer=answer,
            edit_message_text=edit_message_text,
        ),
    )

    asyncio.run(upload_callback(update, context))

    assert edited == ["Unknown upload action. Send the CSV again."]
