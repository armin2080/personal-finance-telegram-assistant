"""Command-line entry point for private, local transaction imports."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import cast

from personal_finance_assistant.categories import category_label
from personal_finance_assistant.domain import DuplicateReview, ParseResult
from personal_finance_assistant.ingestion.sparkasse_csv import (
    ImportValidationError,
    parse_sparkasse_csv,
)
from personal_finance_assistant.services.analytics import check_database_integrity, reconcile_period
from personal_finance_assistant.services.budgets import (
    delete_budget,
    get_budget_month_summary,
    list_review_candidates,
    set_budget,
)
from personal_finance_assistant.services.imports import build_import_preview
from personal_finance_assistant.services.insights import local_question
from personal_finance_assistant.services.management import (
    add_merchant_alias,
    add_rule,
    correct_transaction,
    correct_transaction_merchant,
    delete_rule,
    list_merchants,
    list_rules,
    merge_merchants,
    remove_merchant_alias,
    set_merchant_default_category,
    set_transaction_note,
    split_transaction,
)
from personal_finance_assistant.settings import Settings
from personal_finance_assistant.storage.sqlite import Database, StorageCapacityError


def _database() -> Database:
    settings = Settings.from_environment()
    return Database(
        settings.database_path,
        minimum_free_bytes=settings.minimum_free_bytes,
    )


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
            "Possible duplicates were not inserted and this import is marked incomplete. "
            "Re-run the same file with --accept-possible-duplicates to append them to the "
            "same batch; exact-file protection remains active."
        )
    elif result.already_imported_file and accept_possible_duplicates:
        print("No previously skipped possible duplicates remained to insert.")
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
            f"{batch.possible_duplicate_count} possible duplicates, status {batch.status}, "
            f"created {batch.created_at}"
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


def _review(*, details: bool = False) -> int:
    candidates = list_review_candidates(_database().path, limit=500)
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
        if details:
            print(
                f"    merchant={candidate.merchant!r} category={candidate.category_key} "
                f"classification={candidate.classification}"
            )
    if not details:
        print("Detailed transaction text is intentionally omitted; add --details locally.")
    return 0


def _status() -> int:
    status = _database().health_status()
    print(f"Schema version: {status['schema_version']}")
    print(f"Database exists: {status['database_exists']}")
    print(f"Import batches: {status['import_batches']}")
    print(f"Stored transactions: {status['transactions']}")
    print(f"Transactions needing review: {status['unreviewed_transactions']}")
    print(f"Latest booking date: {status['latest_booking_date']}")
    print(f"Free storage: {status['free_bytes']} bytes")
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
    print(f"Fees: {result.fee_minor} cents; cash: {result.cash_minor} cents")
    print(f"Reversals: {result.reversal_minor} cents; savings: {result.savings_minor} cents")
    print(f"Unknown flow: {result.unknown_minor} cents")
    print(
        f"Unexplained debit: {result.unexplained_debit_minor} cents; "
        f"unexplained credit: {result.unexplained_credit_minor} cents"
    )
    return 0


def _budget_command(
    action: str,
    month: str,
    category_key: str | None,
    limit_minor: int | None,
) -> int:
    database = _database()
    if action == "list":
        summary = get_budget_month_summary(database.path, month)
        if not summary.budgets:
            print(f"No budgets configured for {month}.")
        else:
            for status in summary.budgets:
                projected = (
                    f"; projected {status.projected_minor} cents"
                    if status.projected_minor is not None
                    else ""
                )
                print(
                    f"{category_label(status.category_key)} ({status.category_key}): "
                    f"{status.used_minor} of {status.limit_minor} cents used, "
                    f"{status.remaining_minor} remaining, {status.percentage_used}%{projected}"
                )
        if not summary.complete:
            print(summary.disclosure)
        return 0
    if not category_key:
        print("A category is required.", file=sys.stderr)
        return 2
    if action == "delete":
        deleted = delete_budget(database.path, month, category_key)
        print("Budget deleted." if deleted else "No matching budget found.")
        return 0 if deleted else 2
    if limit_minor is None:
        print("A non-negative limit in minor units is required.", file=sys.stderr)
        return 2
    set_budget(database.path, month, category_key, limit_minor)
    print(f"Budget saved for {category_key} in {month}.")
    return 0


def _correct(
    transaction_id: str,
    *,
    classification: str | None,
    category_key: str | None,
    merchant: str | None,
    note: str | None,
) -> int:
    database = _database()
    if merchant:
        correct_transaction_merchant(database.path, transaction_id, merchant)
    if note is not None:
        set_transaction_note(database.path, transaction_id, note)
    if classification or category_key:
        if not classification or not category_key:
            print("Both --classification and --category are required together.", file=sys.stderr)
            return 2
        correct_transaction(
            database.path,
            transaction_id,
            classification=classification,
            category_key=category_key,
            note=note,
        )
    print(f"Transaction {transaction_id} updated.")
    return 0


def _split(transaction_id: str, allocations: tuple[str, ...]) -> int:
    parsed: list[tuple[int, str, str]] = []
    for allocation in allocations:
        parts = allocation.split(":", 2)
        if len(parts) < 2:
            print("Allocations must use AMOUNT_MINOR:CATEGORY[:NOTE].", file=sys.stderr)
            return 2
        try:
            amount = int(parts[0])
        except ValueError:
            print("Split amount must be an integer minor-unit value.", file=sys.stderr)
            return 2
        parsed.append((amount, parts[1], parts[2] if len(parts) == 3 else ""))
    split_transaction(_database().path, transaction_id, tuple(parsed))
    print(f"Transaction {transaction_id} split into {len(parsed)} allocations.")
    return 0


def _rule(
    action: str,
    *,
    rule_id: str | None = None,
    pattern: str = "",
    classification: str = "expense_candidate",
    category_key: str = "",
    confidence: float = 1.0,
    priority: int = 100,
    merchant_pattern: str | None = None,
    descriptor_pattern: str | None = None,
    payment_channel: str | None = None,
    direction: str = "any",
    payment_type: str | None = None,
) -> int:
    database = _database()
    if action == "list":
        rules = list_rules(database.path)
        if not rules:
            print("No user classification rules.")
        for rule in rules:
            print(
                f"{rule.rule_id}: {rule.pattern!r} -> {rule.classification} / "
                f"{rule.category_key} priority={rule.priority} confidence={rule.confidence} "
                f"enabled={rule.enabled}"
            )
        return 0
    if action == "delete":
        if not rule_id:
            print("A rule id is required.", file=sys.stderr)
            return 2
        print("Rule deleted." if delete_rule(database.path, rule_id) else "Rule not found.")
        return 0
    add_rule(
        database.path,
        pattern,
        classification,
        category_key,
        confidence=confidence,
        priority=priority,
        merchant_pattern=merchant_pattern,
        descriptor_pattern=descriptor_pattern,
        payment_channel=payment_channel,
        direction=direction,
        payment_type=payment_type,
    )
    print("Classification rule saved.")
    return 0


def _merchant(
    action: str,
    *,
    alias: str | None = None,
    canonical: str | None = None,
    category_key: str | None = None,
    source: str | None = None,
    target: str | None = None,
    confirm: bool = False,
) -> int:
    database = _database()
    if action == "list":
        merchants = list_merchants(database.path)
        if not merchants:
            print("No merchant entities have been created yet.")
        for merchant in merchants:
            print(
                f"{merchant.canonical_name}: {merchant.transaction_count} transactions, "
                f"{merchant.total_minor} cents, default category "
                f"{merchant.default_category_key or 'none'}, aliases={list(merchant.aliases)}"
            )
        return 0
    if action == "alias":
        if not alias or not canonical:
            print("--alias and --canonical are required.", file=sys.stderr)
            return 2
        add_merchant_alias(database.path, alias, canonical, default_category_key=category_key)
        print("Merchant alias saved.")
        return 0
    if action == "remove-alias":
        if not alias:
            print("--alias is required.", file=sys.stderr)
            return 2
        print(f"Removed {remove_merchant_alias(database.path, alias)} alias row(s).")
        return 0
    if action == "default":
        if not canonical or not category_key:
            print("--canonical and --category are required.", file=sys.stderr)
            return 2
        set_merchant_default_category(database.path, canonical, category_key)
        print("Merchant default category saved.")
        return 0
    if action == "merge":
        if not source or not target:
            print("--source and --target are required.", file=sys.stderr)
            return 2
        moved = merge_merchants(database.path, source, target, confirm=confirm)
        print(f"Merged {source} into {target}; updated {moved} transaction(s).")
        return 0
    print("Unknown merchant action.", file=sys.stderr)
    return 2


def _ask(question: str, month: str | None) -> int:
    if month is None:
        today = __import__("datetime").date.today()
        month = f"{today.year:04d}-{today.month:02d}"
    print(local_question(_database().path, question, month))
    return 0


def _integrity() -> int:
    report = check_database_integrity(_database().path)
    foreign_keys = cast(list[object], report["foreign_key_violations"])
    split_violations = cast(list[object], report["split_violations"])
    print(f"Integrity: {report['integrity']}")
    print(f"Foreign-key violations: {len(foreign_keys)}")
    print(f"Split violations: {len(split_violations)}")
    return 0 if (report["integrity"] == "ok" and not foreign_keys and not split_violations) else 2


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
    review_parser = subparsers.add_parser("review", help="list transactions requiring local review")
    review_parser.add_argument(
        "--details", action="store_true", help="show merchant/category labels locally"
    )
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

    web_parser = subparsers.add_parser("web", help="run the local loopback dashboard")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8000)

    backup_parser = subparsers.add_parser("backup", help="create a consistent SQLite backup")
    backup_parser.add_argument("destination", type=Path)

    budget_parser = subparsers.add_parser("budget", help="manage monthly category budgets")
    budget_sub = budget_parser.add_subparsers(dest="budget_action", required=True)
    budget_set = budget_sub.add_parser("set")
    budget_set.add_argument("category")
    budget_set.add_argument("limit_minor", type=int)
    budget_set.add_argument("--month")
    budget_delete = budget_sub.add_parser("delete")
    budget_delete.add_argument("category")
    budget_delete.add_argument("--month")
    budget_list = budget_sub.add_parser("list")
    budget_list.add_argument("--month")
    budget_alert = budget_sub.add_parser("alert")
    budget_alert.add_argument("category")
    budget_alert.add_argument("threshold", type=int)

    correct_parser = subparsers.add_parser("correct", help="correct one transaction")
    correct_parser.add_argument("transaction_id")
    correct_parser.add_argument("--classification")
    correct_parser.add_argument("--category")
    correct_parser.add_argument("--merchant")
    correct_parser.add_argument("--note")

    split_parser = subparsers.add_parser("split", help="split one transaction exactly")
    split_parser.add_argument("transaction_id")
    split_parser.add_argument("allocations", nargs="+", metavar="AMOUNT:CATEGORY[:NOTE]")

    rule_parser = subparsers.add_parser("rule", help="manage explicit classification rules")
    rule_sub = rule_parser.add_subparsers(dest="rule_action", required=True)
    rule_add = rule_sub.add_parser("add")
    rule_add.add_argument("--pattern", default="")
    rule_add.add_argument("--merchant-pattern")
    rule_add.add_argument("--descriptor-pattern")
    rule_add.add_argument("--classification", default="expense_candidate")
    rule_add.add_argument("--category", required=True)
    rule_add.add_argument("--confidence", type=float, default=1.0)
    rule_add.add_argument("--priority", type=int, default=100)
    rule_add.add_argument("--payment-channel")
    rule_add.add_argument("--direction", default="any")
    rule_add.add_argument("--payment-type")
    rule_sub.add_parser("list")
    rule_delete = rule_sub.add_parser("delete")
    rule_delete.add_argument("rule_id")

    merchant_parser = subparsers.add_parser("merchant", help="manage merchant identities")
    merchant_sub = merchant_parser.add_subparsers(dest="merchant_action", required=True)
    merchant_sub.add_parser("list")
    merchant_alias = merchant_sub.add_parser("alias")
    merchant_alias.add_argument("--alias", required=True)
    merchant_alias.add_argument("--canonical", required=True)
    merchant_alias.add_argument("--category")
    merchant_remove = merchant_sub.add_parser("remove-alias")
    merchant_remove.add_argument("--alias", required=True)
    merchant_default = merchant_sub.add_parser("default")
    merchant_default.add_argument("--canonical", required=True)
    merchant_default.add_argument("--category", required=True)
    merchant_merge = merchant_sub.add_parser("merge")
    merchant_merge.add_argument("--source", required=True)
    merchant_merge.add_argument("--target", required=True)
    merchant_merge.add_argument("--yes", action="store_true")

    ask_parser = subparsers.add_parser("ask", help="ask a deterministic financial question")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--month")

    subparsers.add_parser("integrity", help="check database and split invariants")
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
            raise SystemExit(_review(details=args.details))
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
        if args.command == "budget":
            import datetime as _datetime

            today = _datetime.date.today()
            month = getattr(args, "month", None) or f"{today.year:04d}-{today.month:02d}"
            if args.budget_action == "alert":
                from personal_finance_assistant.services.budgets import set_budget_alert

                set_budget_alert(_database().path, args.category, args.threshold)
                print("Budget alert preference saved.")
                return
            limit = getattr(args, "limit_minor", None)
            category = getattr(args, "category", None)
            raise SystemExit(_budget_command(args.budget_action, month, category, limit))
        if args.command == "correct":
            raise SystemExit(
                _correct(
                    args.transaction_id,
                    classification=args.classification,
                    category_key=args.category,
                    merchant=args.merchant,
                    note=args.note,
                )
            )
        if args.command == "split":
            raise SystemExit(_split(args.transaction_id, tuple(args.allocations)))
        if args.command == "rule":
            raise SystemExit(
                _rule(
                    args.rule_action,
                    rule_id=getattr(args, "rule_id", None),
                    pattern=getattr(args, "pattern", ""),
                    classification=getattr(args, "classification", "expense_candidate"),
                    category_key=getattr(args, "category", ""),
                    confidence=getattr(args, "confidence", 1.0),
                    priority=getattr(args, "priority", 100),
                    merchant_pattern=getattr(args, "merchant_pattern", None),
                    descriptor_pattern=getattr(args, "descriptor_pattern", None),
                    payment_channel=getattr(args, "payment_channel", None),
                    direction=getattr(args, "direction", "any"),
                    payment_type=getattr(args, "payment_type", None),
                )
            )
        if args.command == "merchant":
            raise SystemExit(
                _merchant(
                    args.merchant_action,
                    alias=getattr(args, "alias", None),
                    canonical=getattr(args, "canonical", None),
                    category_key=getattr(args, "category", None),
                    source=getattr(args, "source", None),
                    target=getattr(args, "target", None),
                    confirm=getattr(args, "yes", False),
                )
            )
        if args.command == "ask":
            raise SystemExit(_ask(args.question, args.month))
        if args.command == "integrity":
            raise SystemExit(_integrity())
        if args.command == "bot":
            from personal_finance_assistant.bot.application import run_bot

            run_bot(drop_pending_updates=args.drop_pending_updates)
            return
        if args.command == "web":
            import uvicorn

            from personal_finance_assistant.web.app import create_app

            uvicorn.run(create_app(_database().path), host=args.host, port=args.port)
            return
    except (ImportValidationError, StorageCapacityError) as exc:
        print(f"Import error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
