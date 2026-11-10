"""Command-line entry point for private, local transaction imports."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from personal_finance_assistant.domain import DuplicateReview, ParseResult
from personal_finance_assistant.ingestion.sparkasse_csv import (
    ImportValidationError,
    parse_sparkasse_csv,
)
from personal_finance_assistant.services.analytics import reconcile_period
from personal_finance_assistant.services.budgets import list_review_candidates
from personal_finance_assistant.services.imports import build_import_preview
from personal_finance_assistant.settings import Settings
from personal_finance_assistant.storage.sqlite import Database


def _database() -> Database:
    return Database(Settings.from_environment().database_path)


def _print_preview(parsed: ParseResult, duplicate_review: DuplicateReview | None = None) -> None:
    preview = build_import_preview(parsed)
    print(f"Format: {preview.source_format}")
    print(f"Transactions: {preview.transaction_count}")
    print(f"Booking dates: {preview.first_booking_date} to {preview.last_booking_date}")
    print(f"Currencies: {dict(preview.currency_counts)}")
    print(f"Negative entries: {preview.negative_count}; positive entries: {preview.positive_count}")
    print(
        f"Duplicate strength: {preview.reference_dedupe_count} reference-backed; "
        f"{preview.content_dedupe_count} content-only"
    )
    print("Booking text counts:")
    for name, count in preview.payment_type_counts:
        print(f"  {name}: {count}")
    if duplicate_review is not None:
        print(f"Exact file match: {duplicate_review.exact_file_match}")
        print(f"Reference duplicates: {duplicate_review.reference_matches}")
        print(f"Possible duplicate rows: {len(duplicate_review.possible_duplicates)}")
        for row_number, reason in duplicate_review.possible_duplicates:
            print(f"  row {row_number}: {reason}")


def _inspect(path: Path) -> int:
    parsed = parse_sparkasse_csv(path)
    print(f"Encoding: {parsed.encoding}")
    _print_preview(parsed)
    print("No account identifiers or individual transaction descriptions are displayed.")
    return 0


def _import(path: Path, *, commit: bool, yes: bool, accept_possible_duplicates: bool) -> int:
    parsed = parse_sparkasse_csv(path)
    duplicate_review = _database().review_import(parsed)
    print(f"Validated import from {path.name!r}.")
    _print_preview(parsed, duplicate_review)
    if not commit:
        print("Dry run only. No data has been written. Add --commit to import.")
        return 0

    if not yes:
        if not sys.stdin.isatty():
            print("Refusing non-interactive commit without --yes.", file=sys.stderr)
            return 2
        answer = input("Import these transactions into the local database? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Import cancelled.")
            return 0

    result = _database().import_file(
        parsed,
        accept_possible_duplicates=accept_possible_duplicates,
    )
    if result.already_imported_file:
        print("This exact file has already been imported; no changes made.")
        return 0
    print(f"Inserted: {result.inserted}")
    print(f"Exact duplicates skipped: {result.exact_duplicates}")
    print(f"Possible duplicates: {result.possible_duplicates}")
    if result.possible_duplicates and not accept_possible_duplicates:
        print(
            "Possible duplicates were not inserted. Inspect the source file before "
            "re-running with --accept-possible-duplicates."
        )
    return 0


def _inspect_imports() -> int:
    batches = _database().list_imports()
    if not batches:
        print("No import batches found.")
        return 0
    for batch in batches:
        print(
            f"{batch.import_id}: {batch.transaction_count} rows, "
            f"{batch.inserted_count} inserted, {batch.exact_duplicate_count} exact duplicates, "
            f"{batch.possible_duplicate_count} possible duplicates, created {batch.created_at}"
        )
    return 0


def _undo_import(import_id: str, *, yes: bool) -> int:
    if not yes:
        print("Refusing import undo without --yes.", file=sys.stderr)
        return 2
    try:
        deleted = _database().undo_import(import_id, confirm=True)
    except ValueError as exc:
        print(f"Cannot undo import: {exc}", file=sys.stderr)
        return 2
    print(f"Undid import batch {import_id}; deleted {deleted} transactions.")
    return 0


def _review() -> int:
    candidates = list_review_candidates(_database().path)
    if not candidates:
        print("No transactions require review.")
        return 0
    print(f"Transactions requiring review: {len(candidates)}")
    for candidate in candidates:
        reasons = []
        if candidate.needs_merchant_review:
            reasons.append("merchant")
        if candidate.needs_classification_review:
            reasons.append("classification")
        print(
            f"{candidate.transaction_id}: {candidate.booking_date} "
            f"{candidate.amount_minor} cents; {', '.join(reasons)}"
        )
    print("Detailed transaction text is intentionally omitted.")
    return 0


def _status() -> int:
    status = _database().health_status()
    print(f"Schema version: {status['schema_version']}")
    print(f"Database exists: {status['database_exists']}")
    print(f"Import batches: {status['import_batches']}")
    print(f"Stored transactions: {status['transactions']}")
    return 0


def _purge(*, yes: bool) -> int:
    if not yes:
        print("Refusing database purge without --yes.", file=sys.stderr)
        return 2
    removed = _database().purge(confirm=True)
    print(f"Removed {removed} database file(s).")
    return 0


def _reconcile(start_text: str, end_text: str) -> int:
    result = reconcile_period(
        _database().path, date.fromisoformat(start_text), date.fromisoformat(end_text)
    )
    print(f"Period: {result.start_date} to {result.end_date}")
    print(f"Transactions: {result.transaction_count}")
    print(f"Debits: {result.debit_minor} cents; credits: {result.credit_minor} cents")
    print(f"Classified expenses: {result.expense_minor} cents")
    print(f"Classified income: {result.income_minor} cents")
    print(f"Refunds: {result.refund_minor} cents; transfers: {result.transfer_minor} cents")
    print(f"Unknown flow: {result.unknown_minor} cents")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finance-assistant",
        description="Local-first personal finance assistant",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="create or upgrade the local SQLite database")

    inspect_parser = subparsers.add_parser("inspect", help="validate and inspect a Sparkasse CSV")
    inspect_parser.add_argument("file", type=Path)

    import_parser = subparsers.add_parser("import", help="preview or import a Sparkasse CSV")
    import_parser.add_argument("file", type=Path)
    import_parser.add_argument("--commit", action="store_true", help="write transactions to SQLite")
    import_parser.add_argument("--yes", action="store_true", help="skip interactive confirmation")
    import_parser.add_argument(
        "--accept-possible-duplicates",
        action="store_true",
        help="also insert content-only duplicate matches after manual review",
    )

    subparsers.add_parser("imports", help="inspect persisted import batches")
    subparsers.add_parser("review", help="list transactions requiring local review")
    subparsers.add_parser("status", help="show privacy-safe operational status")
    purge_parser = subparsers.add_parser("purge", help="delete the local database")
    purge_parser.add_argument("--yes", action="store_true", help="confirm permanent deletion")
    reconcile_parser = subparsers.add_parser("reconcile", help="reconcile aggregate ledger totals")
    reconcile_parser.add_argument("start", help="inclusive date, YYYY-MM-DD")
    reconcile_parser.add_argument("end", help="exclusive date, YYYY-MM-DD")

    undo_parser = subparsers.add_parser("undo-import", help="undo one import batch")
    undo_parser.add_argument("import_id")
    undo_parser.add_argument("--yes", action="store_true", help="confirm transactional undo")

    bot_parser = subparsers.add_parser("bot", help="run the Telegram bot using long polling")
    bot_parser.add_argument("--drop-pending-updates", action="store_true")

    backup_parser = subparsers.add_parser("backup", help="create a consistent SQLite backup")
    backup_parser.add_argument("destination", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "init-db":
            database = _database()
            database.initialize()
            print(f"Database initialized at {database.path}")
            return
        if args.command == "inspect":
            raise SystemExit(_inspect(args.file))
        if args.command == "import":
            raise SystemExit(
                _import(
                    args.file,
                    commit=args.commit,
                    yes=args.yes,
                    accept_possible_duplicates=args.accept_possible_duplicates,
                )
            )
        if args.command == "imports":
            raise SystemExit(_inspect_imports())
        if args.command == "review":
            raise SystemExit(_review())
        if args.command == "status":
            raise SystemExit(_status())
        if args.command == "purge":
            raise SystemExit(_purge(yes=args.yes))
        if args.command == "reconcile":
            raise SystemExit(_reconcile(args.start, args.end))
        if args.command == "undo-import":
            raise SystemExit(_undo_import(args.import_id, yes=args.yes))
        if args.command == "backup":
            destination = _database().backup_to(args.destination)
            print(f"Backup created at {destination}")
            return
        if args.command == "bot":
            from personal_finance_assistant.bot.application import run_bot

            run_bot(drop_pending_updates=args.drop_pending_updates)
            return
    except ImportValidationError as exc:
        print(f"Import error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
