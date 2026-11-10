"""Private Telegram bot adapter using outbound long polling."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes

from personal_finance_assistant.categories import CATEGORY_REGISTRY
from personal_finance_assistant.domain import PeriodReport
from personal_finance_assistant.services.analytics import (
    get_current_month_summary,
    get_month_report,
)
from personal_finance_assistant.services.budgets import (
    find_recurring_candidates,
    get_budget_status,
    list_review_candidates,
)
from personal_finance_assistant.settings import Settings

logger = logging.getLogger(__name__)


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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    await update.effective_message.reply_text(
        "Your private finance assistant is running on your own device.\n\n"
        "Import bank exports locally on the device; this bot does not accept bank files.\n"
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
        "/budget CATEGORY — current month's budget status\n"
        "/subscriptions — repeated payment candidates for review\n"
        "/privacy — how data is handled\n"
        "/help — show this message\n\n"
        "Bank files are imported locally with `finance-assistant import`; they are not "
        "uploaded to this Telegram chat."
    )


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    await update.effective_message.reply_text(
        "Privacy model:\n"
        "• Bank exports are imported locally and stored in SQLite on your device.\n"
        "• This bot does not accept statement uploads in the MVP.\n"
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


async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    if not context.args or len(context.args) > 2:
        await update.effective_message.reply_text(
            "Usage: /budget CATEGORY [YYYY-MM]\n"
            "Use a stable category key, for example subscriptions.digital."
        )
        return
    category_key = context.args[0]
    year, month = _current_month(settings)
    budget_month = context.args[1] if len(context.args) == 2 else f"{year:04d}-{month:02d}"
    status = get_budget_status(settings.database_path, budget_month, category_key)
    state = "exceeded" if status.exceeded else "within limit"
    await update.effective_message.reply_text(
        f"Budget: {CATEGORY_REGISTRY.get(category_key, category_key)} ({status.month})\n"
        f"Limit: {_format_eur(status.limit_minor)}\n"
        f"Used: {_format_eur(status.used_minor)}\n"
        f"Remaining: {_format_eur(status.remaining_minor)}\n"
        f"Status: {state}\n\n"
        "Used totals include classified expenses only."
    )


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    candidates = list_review_candidates(settings.database_path, limit=100)
    await update.effective_message.reply_text(
        f"{len(candidates)} transaction(s) need local review.\n\n"
        "Use `finance-assistant review` on the device for safe review identifiers "
        "and reasons. Detailed bank text is not sent through Telegram."
    )


async def subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not _is_authorized(update, settings) or not update.effective_message:
        return
    candidates = find_recurring_candidates(settings.database_path)
    if not candidates:
        await update.effective_message.reply_text(
            "No repeated payment candidates found. Candidates require at least "
            "three stable classified expenses."
        )
        return
    lines = ["Repeated payment candidates (not confirmed subscriptions):", ""]
    for candidate in candidates[:10]:
        lines.append(
            f"• {candidate.merchant}: {_format_eur(candidate.average_amount_minor)} "
            f"about every {candidate.average_interval_days} days; "
            f"{candidate.observations} observations; {candidate.confidence} confidence"
        )
    lines.extend(
        [
            "",
            "Review dates and amounts locally before treating any candidate as a subscription.",
        ]
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
    application.add_handler(CommandHandler("budget", budget_command))
    application.add_handler(CommandHandler("subscriptions", subscriptions_command))
    application.add_error_handler(error_handler)
    logger.info("Starting private finance bot in long-polling mode")
    application.run_polling(
        allowed_updates=["message"],
        drop_pending_updates=drop_pending_updates,
    )
