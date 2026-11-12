"""Private Telegram bot adapter using outbound long polling."""

from __future__ import annotations

import logging
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from personal_finance_assistant.categories import CATEGORY_REGISTRY
from personal_finance_assistant.domain import PeriodReport
from personal_finance_assistant.services.analytics import (
    get_current_month_summary,
    get_month_report,
)
from personal_finance_assistant.services.budgets import (
    delete_budget,
    find_recurring_candidates,
    find_recurring_price_changes,
    get_budget_status,
    list_review_candidates,
    set_budget,
)
from personal_finance_assistant.services.insights import (
    cash_flow_forecast,
    local_question,
    monthly_trend,
)
from personal_finance_assistant.services.management import (
    confirm_transaction,
    correct_transaction,
    dismiss_transaction,
    list_merchants,
    list_rules,
)
from personal_finance_assistant.services.uploads import (
    UploadPreview,
    build_upload_preview,
    commit_upload,
)
from personal_finance_assistant.settings import Settings
from personal_finance_assistant.storage.sqlite import StorageCapacityError

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return cast(Settings, context.application.bot_data["settings"])


def _is_authorized(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    return bool(
        user
        and chat
        and chat.type == ChatType.PRIVATE
        and user.id in settings.telegram_allowed_user_ids
    )


def _validate_upload_metadata(
    filename: str | None,
    file_size: int | None,
    *,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
) -> str | None:
    if not filename or Path(filename).suffix.casefold() != ".csv":
        return "Only CSV bank exports are accepted."
    if file_size is not None and file_size > max_upload_bytes:
        return "The CSV is too large; the maximum supported upload is 10 MiB."
    return None


async def document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if (
        not _is_authorized(update, settings)
        or not update.effective_message
        or context.user_data is None
    ):
        return
    document = update.effective_message.document
    if document is None:
        return
    validation_error = _validate_upload_metadata(
        document.file_name,
        document.file_size,
        max_upload_bytes=settings.max_upload_bytes,
    )
    if validation_error:
        await update.effective_message.reply_text(validation_error)
        return

    try:
        with tempfile.TemporaryDirectory(prefix="finance-assistant-upload-") as directory:
            temporary_path = Path(directory) / "statement.csv"
            remote_file = await document.get_file()
            await remote_file.download_to_drive(custom_path=temporary_path)
            upload = build_upload_preview(settings.database_path, temporary_path)
    except (OSError, ValueError, StorageCapacityError) as exc:
        logger.warning("CSV upload processing failed: %s", type(exc).__name__)
        await update.effective_message.reply_text(
            "The CSV could not be processed. No source file was retained; "
            "please use the local CLI for detailed validation."
        )
        return

    await update.effective_message.reply_text(
        "CSV preview ready.\n\n"
        f"Rows: {upload.preview.transaction_count}\n"
        f"Date range: {upload.preview.first_booking_date} to {upload.preview.last_booking_date}\n"
        f"Reference duplicates: {upload.duplicates.reference_matches}\n"
        f"Possible duplicates: {len(upload.duplicates.possible_duplicates)}\n\n"
        "The source file was processed from temporary storage and deleted. "
        "Confirm to import the canonicalised rows, or cancel.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Confirm import", callback_data="upload:confirm"),
                    InlineKeyboardButton("Cancel", callback_data="upload:cancel"),
                ]
            ]
        ),
    )
    context.user_data["upload_preview"] = upload
    context.user_data["upload_preview_created"] = datetime.now(UTC)


async def upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    settings = _settings(context)
    if query is None or not _is_authorized(update, settings) or context.user_data is None:
        return
    await query.answer()
    upload = context.user_data.get("upload_preview")
    created = context.user_data.get("upload_preview_created")
    if (
        not isinstance(upload, UploadPreview)
        or not isinstance(created, datetime)
        or (datetime.now(UTC) - created).total_seconds() > 600
    ):
        await query.edit_message_text("This upload preview expired. Send the CSV again.")
        context.user_data.pop("upload_preview", None)
        context.user_data.pop("upload_preview_created", None)
        return
    if query.data == "upload:cancel":
        await query.edit_message_text("Import cancelled. No database changes were made.")
        context.user_data.pop("upload_preview", None)
        context.user_data.pop("upload_preview_created", None)
        return
    if query.data != "upload:confirm":
        await query.edit_message_text("Unknown upload action. Send the CSV again.")
        return
    try:
        result, report = commit_upload(
            settings.database_path,
            upload,
            minimum_free_bytes=settings.minimum_free_bytes,
        )
    except (OSError, StorageCapacityError, ValueError) as exc:
        logger.warning("CSV upload commit failed: %s", type(exc).__name__)
        await query.edit_message_text(
            "The CSV could not be imported. No source file was retained; "
            "please use the local CLI for detailed validation."
        )
        return
    await query.edit_message_text(
        "CSV imported locally.\n\n"
        f"Inserted: {result.inserted}\n"
        f"Exact duplicates skipped: {result.exact_duplicates}\n"
        f"Possible duplicates not inserted: {result.possible_duplicates}\n\n"
        f"Expenses: {_format_eur(report.expenses_minor)}\n"
        f"Income: {_format_eur(report.income_minor)}\n"
        f"Refunds: {_format_eur(report.refunds_minor)}\n"
        f"Transfers excluded: {_format_eur(report.transfers_minor)}\n"
        f"Uncategorised expenses: {_format_eur(report.uncategorized_expenses_minor)}"
    )
    context.user_data.pop("upload_preview", None)
    context.user_data.pop("upload_preview_created", None)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    await update.effective_message.reply_text(
        "Your private finance assistant is running on your own device.\n\n"
        "Send one supported CSV bank export here for temporary local processing, or "
        "import bank exports locally on the device.\n"
        "Use /summary for the current month's totals or /help for commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    await update.effective_message.reply_text(
        "Available commands:\n"
        "/summary — current month's recorded candidate income and expenses\n"
        "/spending — current month's spending by category\n"
        "/income — current month's income and refunds\n"
        "/compare — compare current and previous month\n"
        "/review — count transactions needing local review\n"
        "/trend — recent classified expense/income trend\n"
        "/forecast — conservative month-end cash-flow forecast\n"
        "/ask QUESTION — deterministic question over local analytics\n"
        "/budget CATEGORY [YYYY-MM] — budget status\n"
        "/budget set CATEGORY LIMIT [YYYY-MM] — create or update a budget\n"
        "/budget delete CATEGORY [YYYY-MM] — remove a budget\n"
        "/review — review queue with inline confirm/dismiss actions\n"
        "/correct TX_ID CATEGORY [CLASSIFICATION] — record a correction\n"
        "/rules — list explicit classification rules\n"
        "/merchants — list canonical merchants and aliases\n"
        "/subscriptions — repeated payment candidates for review\n"
        "/privacy — how data is handled\n"
        "/help — show this message\n\n"
        "You may send one CSV bank export as a document from this private chat. "
        "It is processed locally, not retained, and only aggregate results are returned."
    )


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    await update.effective_message.reply_text(
        "Privacy model:\n"
        "• CSV exports sent in this private chat are downloaded temporarily, processed "
        "locally, and deleted after processing.\n"
        "• Replies pass through Telegram, so the bot sends summaries only.\n"
        "• Access is restricted to the configured Telegram user ID.\n"
        "• Do not send PINs, TANs, passwords, full IBANs or raw statements here.\n\n"
        "See docs/SECURITY_AND_PRIVACY.md for the full policy."
    )


def _format_eur(minor_units: int) -> str:
    sign = "-" if minor_units < 0 else ""
    value = abs(minor_units)
    whole = f"{value // 100:,}".replace(",", ".")
    return f"{sign}{whole},{value % 100:02d} €"


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return

    summary = get_current_month_summary(settings.database_path, settings.user_timezone)
    await update.effective_message.reply_text(
        f"Recorded summary for {summary.month_label}\n\n"
        f"Candidate expenses: {_format_eur(summary.expenses_minor)}\n"
        f"Candidate income: {_format_eur(summary.income_minor)}\n"
        f"Imported rows: {summary.transaction_count}\n\n"
        "Transfers and unclassified entries are excluded from these totals. "
        "These are preliminary figures, not a bank reconciliation."
    )


def _current_month(settings: Settings) -> tuple[int, int]:
    local_today = datetime.now(ZoneInfo(settings.user_timezone)).date()
    return local_today.year, local_today.month


def _report_text(report: PeriodReport, title: str) -> str:
    typed_report = report
    lines = [
        f"{title} ({typed_report.start_date} to {typed_report.end_date})",
        "",
        f"Expenses: {_format_eur(typed_report.expenses_minor)}",
        f"Income: {_format_eur(typed_report.income_minor)}",
        f"Refunds: {_format_eur(typed_report.refunds_minor)}",
        f"Transfers excluded from totals: {_format_eur(typed_report.transfers_minor)}",
        f"Uncategorised expenses: {_format_eur(typed_report.uncategorized_expenses_minor)}",
    ]
    if typed_report.category_expenses:
        lines.extend(
            [
                "",
                "Expense categories:",
                *(
                    f"• {CATEGORY_REGISTRY.get(item.category_key, item.category_key)}: "
                    f"{_format_eur(item.amount_minor)}"
                    for item in typed_report.category_expenses[:10]
                ),
            ]
        )
    lines.extend(
        [
            "",
            "Period uses booking dates. Only classified expense/income candidates "
            "are included in those totals; transfers, refunds, and uncertain rows "
            "remain separate.",
        ]
    )
    return "\n".join(lines)


async def spending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    year, month = _current_month(settings)
    report = get_month_report(settings.database_path, year, month)
    await update.effective_message.reply_text(_report_text(report, "Spending report"))


async def income_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    year, month = _current_month(settings)
    report = get_month_report(settings.database_path, year, month)
    await update.effective_message.reply_text(
        "\n".join(
            [
                f"Income report ({report.start_date} to {report.end_date})",
                "",
                f"Classified income: {_format_eur(report.income_minor)}",
                f"Refunds kept separate: {_format_eur(report.refunds_minor)}",
                f"Transfers excluded: {_format_eur(report.transfers_minor)}",
                "",
                "Generic credits are not automatically treated as salary.",
            ]
        )
    )


async def compare_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    year, month = _current_month(settings)
    current = get_month_report(settings.database_path, year, month)
    previous_month = month - 1
    previous_year = year
    if previous_month == 0:
        previous_month = 12
        previous_year -= 1
    previous = get_month_report(settings.database_path, previous_year, previous_month)
    change = current.expenses_minor - previous.expenses_minor
    await update.effective_message.reply_text(
        "\n".join(
            [
                f"Expense comparison: {previous.start_date} vs {current.start_date}",
                "",
                f"Previous: {_format_eur(previous.expenses_minor)}",
                f"Current: {_format_eur(current.expenses_minor)}",
                f"Change: {_format_eur(change)}",
                "",
                "Comparison uses classified expense candidates by booking month; "
                "transfers, refunds, and uncertain rows are excluded.",
            ]
        )
    )


def _parse_eur_minor(value: str) -> int:
    from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

    normalized = value.strip().replace("€", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("amount is not a valid decimal value") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("amount must be a non-negative decimal value")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    args = list(context.args or [])
    year, month = _current_month(settings)
    default_month = f"{year:04d}-{month:02d}"
    if not args:
        await update.effective_message.reply_text(
            "Usage:\n"
            "/budget CATEGORY [YYYY-MM]\n"
            "/budget set CATEGORY LIMIT [YYYY-MM]\n"
            "/budget delete CATEGORY [YYYY-MM]\n"
            "Limits use EUR, for example 150,00."
        )
        return
    action = args[0].casefold()
    try:
        if action == "list":
            from personal_finance_assistant.services.budgets import get_budget_month_summary

            budget_month = args[1] if len(args) > 1 else default_month
            summary = get_budget_month_summary(settings.database_path, budget_month)
            if not summary.budgets:
                await update.effective_message.reply_text(
                    f"No budgets configured for {budget_month}."
                )
                return
            lines = [f"Budgets for {budget_month}:"]
            for item in summary.budgets:
                lines.append(
                    f"• {CATEGORY_REGISTRY.get(item.category_key, item.category_key)}: "
                    f"{_format_eur(item.used_minor)} of {_format_eur(item.limit_minor)}, "
                    f"{_format_eur(item.remaining_minor)} left ({item.percentage_used}%)"
                )
            if not summary.complete:
                lines.append("")
                lines.append(summary.disclosure)
            await update.effective_message.reply_text("\n".join(lines))
            return
        if action == "set":
            if len(args) < 3:
                raise ValueError("Usage: /budget set CATEGORY LIMIT [YYYY-MM]")
            category_key = args[1]
            limit_minor = _parse_eur_minor(args[2])
            budget_month = args[3] if len(args) > 3 else default_month
            set_budget(settings.database_path, budget_month, category_key, limit_minor)
            await update.effective_message.reply_text(
                f"Budget saved: {CATEGORY_REGISTRY.get(category_key, category_key)} "
                f"{_format_eur(limit_minor)} for {budget_month}."
            )
            return
        if action == "delete":
            if len(args) < 2:
                raise ValueError("Usage: /budget delete CATEGORY [YYYY-MM]")
            category_key = args[1]
            budget_month = args[2] if len(args) > 2 else default_month
            deleted = delete_budget(settings.database_path, budget_month, category_key)
            await update.effective_message.reply_text(
                "Budget deleted." if deleted else "No matching budget was found."
            )
            return
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    if len(args) > 2:
        await update.effective_message.reply_text(
            "Usage: /budget CATEGORY [YYYY-MM] or /budget set CATEGORY LIMIT [YYYY-MM]"
        )
        return
    category_key = args[0]
    budget_month = args[1] if len(args) == 2 else default_month
    try:
        status = get_budget_status(settings.database_path, budget_month, category_key)
    except ValueError:
        await update.effective_message.reply_text("No matching budget was found.")
        return
    state_text = "exceeded" if status.exceeded else status.status.replace("_", " ")
    lines = [
        f"Budget: {CATEGORY_REGISTRY.get(category_key, category_key)} ({status.month})",
        f"Limit: {_format_eur(status.limit_minor)}",
        f"Used: {_format_eur(status.used_minor)}",
        f"Remaining: {_format_eur(status.remaining_minor)}",
        f"Used: {status.percentage_used}% · {status.elapsed_days}/{status.total_days} days",
        f"Status: {state_text}",
    ]
    if status.projected_minor is not None:
        lines.append(f"Projected month-end: {_format_eur(status.projected_minor)}")
    if not status.complete:
        lines.append(
            f"{_format_eur(status.uncategorized_expenses_minor)} of expenditure is not yet "
            "categorised. Category budget status is incomplete."
        )
    await update.effective_message.reply_text("\n".join(lines))


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    candidates = list_review_candidates(settings.database_path, limit=5)
    if not candidates:
        await update.effective_message.reply_text(
            "No transactions need review. High-confidence deterministic categories are "
            "confirmed automatically."
        )
        return
    if context.user_data is not None:
        context.user_data["review_ids"] = [item.transaction_id for item in candidates]
    buttons: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(candidates):
        buttons.append(
            [
                InlineKeyboardButton(
                    f"Confirm {item.booking_date} {_format_eur(item.amount_minor)}",
                    callback_data=f"review:confirm:{index}",
                ),
                InlineKeyboardButton("Dismiss", callback_data=f"review:dismiss:{index}"),
            ]
        )
    await update.effective_message.reply_text(
        f"{len(candidates)} transaction(s) shown for local review.\n"
        "Confirm or dismiss without exposing raw bank text. Use /correct TX_ID CATEGORY "
        "for an explicit category correction.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    settings = _settings(context)
    if query is None or not _is_authorized(update, settings) or context.user_data is None:
        return
    await query.answer()
    parts = (query.data or "").split(":")
    ids = context.user_data.get("review_ids") or []
    if len(parts) != 3 or not isinstance(ids, list):
        await query.edit_message_text("This review action expired. Run /review again.")
        return
    action, raw_index = parts[1], parts[2]
    try:
        index = int(raw_index)
    except ValueError:
        await query.edit_message_text("This review action is invalid.")
        return
    if index < 0 or index >= len(ids):
        await query.edit_message_text("This review action expired. Run /review again.")
        return
    transaction_id = ids[index]
    if action == "confirm":
        confirm_transaction(settings.database_path, transaction_id)
        message = "Transaction confirmed."
    elif action == "dismiss":
        dismiss_transaction(settings.database_path, transaction_id)
        message = "Transaction dismissed."
    else:
        message = "Unknown review action."
    await query.edit_message_text(message)


async def trend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    year, month = _current_month(settings)
    points = monthly_trend(settings.database_path, f"{year:04d}-{month:02d}", months=3)
    lines = ["Recent classified trend (booking months):"]
    lines.extend(
        f"• {point.month}: expenses {_format_eur(point.expenses_minor)}, "
        f"income {_format_eur(point.income_minor)}"
        for point in points
    )
    lines.append("Transfers, refunds, and uncertain rows are excluded.")
    await update.effective_message.reply_text("\n".join(lines))


async def forecast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    year, month = _current_month(settings)
    forecast = cash_flow_forecast(
        settings.database_path,
        f"{year:04d}-{month:02d}",
        as_of=datetime.now(ZoneInfo(settings.user_timezone)).date(),
    )
    if forecast.sparse_data:
        text = (
            f"Forecast for {forecast.month} is unavailable: only {forecast.observations} "
            f"observations across {forecast.observed_days} observed days. "
            "At least 7 days and 3 observations are required."
        )
    else:
        text = (
            f"Conservative cash-flow forecast for {forecast.month}: "
            f"{_format_eur(forecast.projected_net_minor or 0)} net.\n"
            "Assumption: current classified daily net flow continues through the month; "
            "this is a moderate-confidence estimate."
        )
    await update.effective_message.reply_text(text)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    question = " ".join(context.args or []).strip()
    if not question:
        await update.effective_message.reply_text(
            "Usage: /ask QUESTION\nOnly aggregate spending and income questions are supported locally."
        )
        return
    year, month = _current_month(settings)
    await update.effective_message.reply_text(
        local_question(settings.database_path, question, f"{year:04d}-{month:02d}")
    )


async def subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    candidates = find_recurring_candidates(settings.database_path)
    changes = find_recurring_price_changes(settings.database_path)
    if not candidates:
        await update.effective_message.reply_text(
            "No repeated payment candidates found. Candidates require at least "
            "three stable classified expenses with monthly-to-quarterly spacing."
        )
        return
    lines = ["Repeated payment candidates (not confirmed subscriptions):", ""]
    for candidate in candidates[:10]:
        lines.append(
            f"• {candidate.merchant}: {_format_eur(candidate.average_amount_minor)} "
            f"about every {candidate.average_interval_days} days; "
            f"{candidate.observations} observations; {candidate.status} confidence"
        )
    if changes:
        lines.extend(["", "Price changes with evidence:"])
        for change in changes[:5]:
            lines.append(
                f"• {change.merchant}: {_format_eur(change.old_amount_minor)} → "
                f"{_format_eur(change.new_amount_minor)} effective {change.changed_on}"
            )
    lines.extend(
        [
            "",
            "Review dates and amounts locally before treating any candidate as a subscription.",
        ]
    )
    await update.effective_message.reply_text("\n".join(lines))


async def correct_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    args = list(context.args or [])
    if len(args) < 2:
        await update.effective_message.reply_text(
            "Usage: /correct TX_ID CATEGORY [CLASSIFICATION]\n"
            "Classification defaults to expense_candidate."
        )
        return
    classification = args[2] if len(args) > 2 else "expense_candidate"
    try:
        correct_transaction(
            settings.database_path,
            args[0],
            classification=classification,
            category_key=args[1],
        )
    except ValueError as exc:
        await update.effective_message.reply_text(f"Correction failed: {exc}")
        return
    await update.effective_message.reply_text("Correction saved and confirmed.")


async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    rules = list_rules(settings.database_path)
    if not rules:
        await update.effective_message.reply_text(
            "No explicit classification rules are configured."
        )
        return
    lines = ["Explicit classification rules:"]
    for rule in rules[:10]:
        lines.append(
            f"• {rule.merchant_pattern or rule.descriptor_pattern or rule.pattern} → "
            f"{CATEGORY_REGISTRY.get(rule.category_key, rule.category_key)} "
            f"(priority {rule.priority})"
        )
    await update.effective_message.reply_text("\n".join(lines))


async def merchants_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    merchants = list_merchants(settings.database_path)
    if not merchants:
        await update.effective_message.reply_text("No canonical merchant entities yet.")
        return
    lines = ["Canonical merchants:"]
    for merchant in merchants[:10]:
        lines.append(
            f"• {merchant.canonical_name}: {merchant.transaction_count} rows, "
            f"default {merchant.default_category_key or 'none'}"
        )
    await update.effective_message.reply_text("\n".join(lines))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report a safe error reference to an authorized private chat only."""

    error_id = uuid.uuid4().hex[:12]
    logger.error("Bot command failed; error_id=%s", error_id, exc_info=context.error)
    if not isinstance(update, Update) or not update.effective_message:
        return
    settings = _settings(context)
    if _is_authorized(update, settings):
        await update.effective_message.reply_text(
            f"That command could not be completed. Please check local logs for error {error_id}."
        )


def run_bot(*, drop_pending_updates: bool = False) -> None:
    settings = Settings.from_environment()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing; configure it in the private .env file.")
    if not settings.telegram_allowed_user_ids:
        raise RuntimeError(
            "TELEGRAM_ALLOWED_USER_IDS is empty; set your numeric Telegram user ID before startup."
        )
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # HTTP request logs may include Bot API URLs containing the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["settings"] = settings
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("privacy", privacy_command))
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("spending", spending_command))
    application.add_handler(CommandHandler("income", income_command))
    application.add_handler(CommandHandler("compare", compare_command))
    application.add_handler(CommandHandler("review", review_command))
    application.add_handler(CommandHandler("trend", trend_command))
    application.add_handler(CommandHandler("forecast", forecast_command))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CallbackQueryHandler(upload_callback, pattern=r"^upload:"))
    application.add_handler(MessageHandler(filters.Document.ALL, document_upload))
    application.add_handler(CommandHandler("budget", budget_command))
    application.add_handler(CommandHandler("subscriptions", subscriptions_command))
    application.add_handler(CommandHandler("correct", correct_command))
    application.add_handler(CommandHandler("rules", rules_command))
    application.add_handler(CommandHandler("merchants", merchants_command))
    application.add_handler(CallbackQueryHandler(review_callback, pattern=r"^review:"))
    application.add_error_handler(error_handler)
    logger.info("Starting private finance bot in long-polling mode")
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=drop_pending_updates,
    )
