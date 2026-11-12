"""SQLite persistence with explicit transaction boundaries and minimal data retention."""

from __future__ import annotations

import itertools
import re
import shutil
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, date, datetime
from pathlib import Path

from personal_finance_assistant.categories import CATEGORY_REGISTRY
from personal_finance_assistant.domain import (
    BudgetMonthSummary,
    BudgetStatus,
    CategoryTotal,
    ClassificationResolution,
    ClassificationRuleInfo,
    DuplicateReason,
    DuplicateReview,
    FinancialOverview,
    ImportBatchInfo,
    ImportResult,
    ImportRowOverride,
    ImportRowPreview,
    LedgerReconciliation,
    MerchantEntityInfo,
    MerchantResolution,
    MerchantTotal,
    MonthlyTrend,
    ParsedTransaction,
    ParseResult,
    PeriodReport,
    RecurringCandidate,
    RecurringPriceChange,
    ReviewCandidate,
    TransactionRecord,
    TransactionSplit,
    WeeklyTrend,
)
from personal_finance_assistant.ingestion.classification import classify_transaction
from personal_finance_assistant.ingestion.merchant_resolution import (
    canonical_merchant,
    is_ambiguous_merchant,
    learnable_descriptor,
    normalize_alias_key,
    normalize_merchant_display,
)

SCHEMA_VERSION = 6
_ALLOWED_CLASSIFICATIONS = frozenset(
    {
        "expense_candidate",
        "income_candidate",
        "transfer_candidate",
        "refund_candidate",
        "reversal_candidate",
        "fee_candidate",
        "cash_withdrawal_candidate",
        "savings_candidate",
        "unknown",
    }
)
_PAYMENT_CHANNELS = frozenset(
    {"paypal", "card", "digital_wallet", "direct_debit", "bank_transfer", "cash", "unknown"}
)
_RECURRING_CATEGORIES = frozenset(
    {
        "subscriptions.digital",
        "subscriptions.memberships",
        "insurance",
        "housing.rent",
        "housing.utilities",
        "housing.internet",
        "health.fitness",
        "transport.public_transit",
        "education",
    }
)


class StorageCapacityError(RuntimeError):
    """Raised when a write would risk exhausting the local filesystem."""


_ID_SEQUENCE = itertools.count()


def _new_id(prefix: str) -> str:
    """Return a lexicographically sortable identifier without host metadata."""

    return f"{prefix}_{time.time_ns():020d}{next(_ID_SEQUENCE):010d}{uuid.uuid4().hex[:8]}"


def _split_sql(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";\n") if statement.strip()]


_MIGRATION_0 = """
CREATE TABLE IF NOT EXISTS imports (
    id TEXT PRIMARY KEY,
    file_sha256 TEXT NOT NULL UNIQUE,
    source_format TEXT NOT NULL,
    encoding TEXT NOT NULL,
    transaction_count INTEGER NOT NULL,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    exact_duplicate_count INTEGER NOT NULL DEFAULT 0,
    possible_duplicate_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS classification_rules (
    id TEXT PRIMARY KEY,
    pattern TEXT NOT NULL UNIQUE,
    classification TEXT NOT NULL,
    category_key TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    import_id TEXT NOT NULL REFERENCES imports(id),
    account_alias TEXT NOT NULL DEFAULT 'primary',
    booking_date TEXT NOT NULL,
    value_date TEXT,
    booking_text TEXT NOT NULL,
    description TEXT NOT NULL,
    counterparty TEXT NOT NULL,
    merchant_candidate TEXT NOT NULL,
    merchant_source TEXT NOT NULL DEFAULT 'unreviewed',
    merchant_confidence REAL NOT NULL DEFAULT 0,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL CHECK(currency = 'EUR'),
    classification TEXT NOT NULL,
    classification_source TEXT NOT NULL DEFAULT 'unreviewed',
    classification_confidence REAL NOT NULL DEFAULT 0,
    category_key TEXT NOT NULL DEFAULT 'uncategorized',
    category_source TEXT NOT NULL DEFAULT 'unreviewed',
    category_confidence REAL NOT NULL DEFAULT 0,
    dedupe_key TEXT NOT NULL,
    dedupe_basis TEXT NOT NULL CHECK(dedupe_basis IN ('reference', 'content')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transactions_booking_date ON transactions(booking_date);
CREATE INDEX IF NOT EXISTS idx_transactions_merchant ON transactions(merchant_candidate);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category_key);
CREATE INDEX IF NOT EXISTS idx_transactions_dedupe ON transactions(account_alias, dedupe_key);
CREATE TABLE IF NOT EXISTS merchant_rules (
    id TEXT PRIMARY KEY,
    merchant_pattern TEXT NOT NULL,
    canonical_merchant TEXT NOT NULL,
    category_key TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS merchant_entities (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS merchant_aliases (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES merchant_entities(id),
    alias TEXT NOT NULL UNIQUE,
    normalized_alias TEXT NOT NULL UNIQUE,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transaction_corrections (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL UNIQUE REFERENCES transactions(id),
    merchant TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
    id TEXT PRIMARY KEY,
    month TEXT NOT NULL,
    category_key TEXT NOT NULL,
    limit_minor INTEGER NOT NULL CHECK(limit_minor >= 0),
    created_at TEXT NOT NULL,
    UNIQUE(month, category_key)
);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_alert_preferences (
    category_key TEXT PRIMARY KEY,
    threshold_percent INTEGER NOT NULL CHECK(threshold_percent BETWEEN 1 AND 100),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1))
);
CREATE TABLE IF NOT EXISTS budget_alert_deliveries (
    id TEXT PRIMARY KEY,
    month TEXT NOT NULL,
    category_key TEXT NOT NULL,
    threshold_percent INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(month, category_key, threshold_percent)
);
CREATE TABLE IF NOT EXISTS recurring_decisions (
    merchant TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK(decision IN ('confirmed', 'dismissed')),
    updated_at TEXT NOT NULL
);
PRAGMA user_version = 4
"""

_MIGRATION_1 = """
ALTER TABLE transactions ADD COLUMN merchant_source TEXT NOT NULL DEFAULT 'unreviewed';
ALTER TABLE transactions ADD COLUMN merchant_confidence REAL NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS merchant_entities (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS merchant_aliases (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES merchant_entities(id),
    alias TEXT NOT NULL UNIQUE,
    normalized_alias TEXT NOT NULL UNIQUE,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transaction_corrections (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL UNIQUE REFERENCES transactions(id),
    merchant TEXT NOT NULL,
    created_at TEXT NOT NULL
);
PRAGMA user_version = 2
"""

_MIGRATION_2 = """
ALTER TABLE transactions ADD COLUMN classification_source TEXT NOT NULL DEFAULT 'unreviewed';
ALTER TABLE transactions ADD COLUMN classification_confidence REAL NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS classification_rules (
    id TEXT PRIMARY KEY,
    pattern TEXT NOT NULL UNIQUE,
    classification TEXT NOT NULL,
    category_key TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
PRAGMA user_version = 3
"""

_MIGRATION_3 = """
CREATE TABLE IF NOT EXISTS budget_alert_preferences (
    category_key TEXT PRIMARY KEY,
    threshold_percent INTEGER NOT NULL CHECK(threshold_percent BETWEEN 1 AND 100),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1))
);
CREATE TABLE IF NOT EXISTS budget_alert_deliveries (
    id TEXT PRIMARY KEY,
    month TEXT NOT NULL,
    category_key TEXT NOT NULL,
    threshold_percent INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(month, category_key, threshold_percent)
);
CREATE TABLE IF NOT EXISTS recurring_decisions (
    merchant TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK(decision IN ('confirmed', 'dismissed')),
    updated_at TEXT NOT NULL
);
PRAGMA user_version = 4
"""

_MIGRATION_4 = """
ALTER TABLE transactions ADD COLUMN payment_channel TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE transactions ADD COLUMN review_status TEXT NOT NULL DEFAULT 'needs_review';
ALTER TABLE transactions ADD COLUMN subcategory_key TEXT;
ALTER TABLE classification_rules ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_transactions_review_status ON transactions(review_status);
CREATE TABLE IF NOT EXISTS transaction_splits (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    amount_minor INTEGER NOT NULL CHECK(amount_minor != 0),
    category_key TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transaction_splits_transaction
    ON transaction_splits(transaction_id);
PRAGMA user_version = 5
"""

_MIGRATION_5 = """
ALTER TABLE imports ADD COLUMN status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE transactions ADD COLUMN note TEXT NOT NULL DEFAULT '';
ALTER TABLE transactions ADD COLUMN evidence TEXT NOT NULL DEFAULT '';
ALTER TABLE merchant_entities ADD COLUMN default_category_key TEXT;
ALTER TABLE classification_rules ADD COLUMN match_type TEXT NOT NULL DEFAULT 'tokens';
ALTER TABLE classification_rules ADD COLUMN merchant_pattern TEXT;
ALTER TABLE classification_rules ADD COLUMN descriptor_pattern TEXT;
ALTER TABLE classification_rules ADD COLUMN payment_channel TEXT;
ALTER TABLE classification_rules ADD COLUMN direction TEXT NOT NULL DEFAULT 'any';
ALTER TABLE classification_rules ADD COLUMN payment_type TEXT;
ALTER TABLE classification_rules ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE classification_rules ADD COLUMN label TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS transaction_links (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL UNIQUE REFERENCES transactions(id),
    linked_transaction_id TEXT NOT NULL REFERENCES transactions(id),
    link_type TEXT NOT NULL CHECK(link_type IN ('refund', 'reversal')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transaction_links_linked
    ON transaction_links(linked_transaction_id);
UPDATE imports SET status = 'incomplete' WHERE possible_duplicate_count > 0;
DROP VIEW IF EXISTS transaction_flows;
CREATE VIEW transaction_flows AS
    SELECT t.id AS transaction_id, t.booking_date, t.amount_minor, t.classification,
           t.category_key, t.merchant_candidate, t.import_id, 0 AS is_split
      FROM transactions t
     WHERE NOT EXISTS (
         SELECT 1 FROM transaction_splits s WHERE s.transaction_id = t.id
     )
    UNION ALL
    SELECT t.id, t.booking_date, s.amount_minor, t.classification, s.category_key,
           t.merchant_candidate, t.import_id, 1 AS is_split
      FROM transaction_splits s
      JOIN transactions t ON t.id = s.transaction_id;
PRAGMA user_version = 6
"""

_MIGRATIONS: dict[int, str] = {
    0: _MIGRATION_0,
    1: _MIGRATION_1,
    2: _MIGRATION_2,
    3: _MIGRATION_3,
    4: _MIGRATION_4,
    5: _MIGRATION_5,
}


def _month_bounds(month: str) -> tuple[date, date]:
    start = date.fromisoformat(f"{month}-01")
    end = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
    return start, end


def _auto_confirmed(resolution: ClassificationResolution) -> bool:
    return (
        resolution.category_key != "uncategorized"
        and resolution.classification_confidence >= 0.8
        and resolution.category_confidence >= 0.8
    )


class Database:
    def __init__(self, path: str | Path, *, minimum_free_bytes: int = 100 * 1024 * 1024) -> None:
        self.path = Path(path).expanduser()
        if minimum_free_bytes < 0:
            raise ValueError("minimum free bytes cannot be negative")
        self.minimum_free_bytes = minimum_free_bytes

    def ensure_write_capacity(self) -> None:
        free_bytes = shutil.disk_usage(self.path.parent).free
        if free_bytes < self.minimum_free_bytes:
            raise StorageCapacityError(
                f"insufficient free storage; need at least {self.minimum_free_bytes} bytes"
            )

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        with suppress(OSError):
            self.path.chmod(0o600)
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Apply all pending migrations atomically.

        Each migration script runs inside one SQLite transaction. A failure
        rolls the whole upgrade back, leaving the previous schema version
        intact and retryable on the next start.
        """

        with self.session() as connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {current_version} is newer than this app "
                    f"supports ({SCHEMA_VERSION}). Upgrade the application before opening it."
                )
            if current_version == SCHEMA_VERSION:
                return
            if current_version not in _MIGRATIONS:
                raise RuntimeError(
                    f"No migration path exists from database schema {current_version}."
                )
            # Manage the transaction explicitly: Python's legacy sqlite3
            # transaction handling may commit DDL implicitly, which would leave
            # a half-applied migration after a failure.
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            try:
                while current_version < SCHEMA_VERSION:
                    script = _MIGRATIONS.get(current_version)
                    if script is None:
                        raise RuntimeError(
                            f"No migration path exists from database schema {current_version}."
                        )
                    for statement in _split_sql(script):
                        connection.execute(statement)
                    # The fresh-install script creates the historical version-4
                    # baseline directly. Later ALTER steps only apply to databases
                    # that were genuinely created at versions 1, 2 or 3.
                    current_version = 4 if current_version == 0 else current_version + 1
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------
    # Import lifecycle
    # ------------------------------------------------------------------

    def import_file(
        self,
        parsed: ParseResult,
        *,
        account_alias: str = "primary",
        accept_possible_duplicates: bool = False,
        overrides: Mapping[int, ImportRowOverride] | None = None,
    ) -> ImportResult:
        """Persist an import atomically and keep possible duplicates resumable.

        Exact-file protection stays in place. When possible duplicates were
        skipped, the file hash is recorded with an ``incomplete`` status so the
        owner can re-run the same file with ``--accept-possible-duplicates`` and
        append the skipped rows to the same batch instead of being locked out.
        """

        self.initialize()
        self.ensure_write_capacity()
        overrides_by_row = dict(overrides or {})
        now = datetime.now(UTC).isoformat()

        with self.session() as connection:
            existing_file = connection.execute(
                """SELECT id, inserted_count, exact_duplicate_count,
                          possible_duplicate_count, status
                   FROM imports WHERE file_sha256 = ?""",
                (parsed.file_sha256,),
            ).fetchone()
            if existing_file is not None:
                if not accept_possible_duplicates:
                    return ImportResult(
                        import_id=existing_file["id"],
                        inserted=0,
                        exact_duplicates=len(parsed.transactions),
                        possible_duplicates=int(existing_file["possible_duplicate_count"]),
                        already_imported_file=True,
                        status=str(existing_file["status"]),
                    )
                inserted = self._accept_pending_duplicates(
                    connection, parsed, existing_file["id"], account_alias, now, overrides_by_row
                )
                connection.execute(
                    """UPDATE imports
                       SET inserted_count = inserted_count + ?,
                           possible_duplicate_count = 0,
                           status = 'completed'
                       WHERE id = ?""",
                    (inserted, existing_file["id"]),
                )
                return ImportResult(
                    import_id=existing_file["id"],
                    inserted=inserted,
                    exact_duplicates=0,
                    possible_duplicates=0,
                    already_imported_file=inserted == 0,
                    status="completed",
                )

            import_id = _new_id("imp")
            inserted = 0
            exact_duplicates = 0
            possible_duplicates = 0
            seen_reference: set[str] = set()
            seen_content: set[str] = set()
            connection.execute(
                """INSERT INTO imports
                   (id, file_sha256, source_format, encoding, transaction_count,
                    created_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    import_id,
                    parsed.file_sha256,
                    parsed.source_format,
                    parsed.encoding,
                    len(parsed.transactions),
                    now,
                ),
            )

            for transaction in parsed.transactions:
                exists = connection.execute(
                    """SELECT id FROM transactions
                       WHERE account_alias = ? AND dedupe_key = ? LIMIT 1""",
                    (account_alias, transaction.dedupe_key),
                ).fetchone()
                if transaction.dedupe_basis == "reference":
                    if transaction.dedupe_key in seen_reference or exists:
                        exact_duplicates += 1
                        continue
                    seen_reference.add(transaction.dedupe_key)
                else:
                    duplicate_in_current_file = transaction.dedupe_key in seen_content
                    if duplicate_in_current_file or exists:
                        possible_duplicates += 1
                        if not accept_possible_duplicates:
                            continue
                    seen_content.add(transaction.dedupe_key)
                transaction_id = self._insert_transaction(
                    connection, transaction, import_id, account_alias, now
                )
                if transaction_id is not None:
                    override = overrides_by_row.get(transaction.row_number)
                    if override is not None:
                        self._apply_import_override(connection, transaction_id, override, now)
                    inserted += 1

            accepted = accept_possible_duplicates and possible_duplicates > 0
            status = "completed" if possible_duplicates == 0 or accepted else "incomplete"
            stored_possible = 0 if accepted else possible_duplicates
            connection.execute(
                """UPDATE imports SET inserted_count = ?, exact_duplicate_count = ?,
                   possible_duplicate_count = ?, status = ? WHERE id = ?""",
                (inserted, exact_duplicates, stored_possible, status, import_id),
            )

        return ImportResult(
            import_id=import_id,
            inserted=inserted,
            exact_duplicates=exact_duplicates,
            possible_duplicates=possible_duplicates,
            status=status,
        )

    def _accept_pending_duplicates(
        self,
        connection: sqlite3.Connection,
        parsed: ParseResult,
        import_id: str,
        account_alias: str,
        now: str,
        overrides: Mapping[int, ImportRowOverride],
    ) -> int:
        """Insert rows that a previous run of the same file held back."""

        inserted = 0
        seen_content: set[str] = set()
        for index, transaction in enumerate(parsed.transactions):
            if transaction.dedupe_basis == "reference":
                continue
            seen_content.add(transaction.dedupe_key)
            occurrences_in_batch = int(
                connection.execute(
                    """SELECT COUNT(*) FROM transactions
                       WHERE import_id = ? AND dedupe_key = ?""",
                    (import_id, transaction.dedupe_key),
                ).fetchone()[0]
            )
            occurrences_in_file = sum(
                1
                for earlier in parsed.transactions[:index]
                if earlier.dedupe_basis == "content"
                and earlier.dedupe_key == transaction.dedupe_key
            )
            if occurrences_in_batch > occurrences_in_file:
                continue
            transaction_id = self._insert_transaction(
                connection, transaction, import_id, account_alias, now
            )
            if transaction_id is not None:
                override = overrides.get(transaction.row_number)
                if override is not None:
                    self._apply_import_override(connection, transaction_id, override, now)
                inserted += 1
        return inserted

    def _insert_transaction(
        self,
        connection: sqlite3.Connection,
        transaction: ParsedTransaction,
        import_id: str,
        account_alias: str,
        now: str,
    ) -> str:
        transaction_id = _new_id("txn")
        resolution_merchant = self._resolve_merchant(connection, transaction.merchant_candidate)
        classification = self._resolve_classification(connection, transaction, resolution_merchant)
        review_status = (
            "confirmed"
            if classification.classification_source == "user"
            or classification.category_source == "user"
            or _auto_confirmed(classification)
            else "needs_review"
        )
        connection.execute(
            """INSERT INTO transactions (
                id, import_id, account_alias, booking_date, value_date,
                booking_text, description, counterparty, merchant_candidate,
                merchant_source, merchant_confidence, amount_minor, currency,
                classification, classification_source, classification_confidence,
                category_key, category_source, category_confidence,
                dedupe_key, dedupe_basis, created_at, payment_channel, review_status,
                note, evidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)""",
            (
                transaction_id,
                import_id,
                account_alias,
                transaction.booking_date.isoformat(),
                transaction.value_date.isoformat() if transaction.value_date else None,
                transaction.booking_text,
                transaction.purpose,
                transaction.counterparty,
                resolution_merchant.merchant,
                resolution_merchant.source,
                resolution_merchant.confidence,
                transaction.amount_minor,
                transaction.currency,
                classification.classification,
                classification.classification_source,
                classification.classification_confidence,
                classification.category_key,
                classification.category_source,
                classification.category_confidence,
                transaction.dedupe_key,
                transaction.dedupe_basis,
                now,
                transaction.payment_channel,
                review_status,
                classification.evidence,
            ),
        )
        return transaction_id

    @staticmethod
    def _resolve_merchant(connection: sqlite3.Connection, candidate: str) -> MerchantResolution:
        key = normalize_alias_key(candidate)
        legacy_key = " ".join(candidate.casefold().split())
        row = connection.execute(
            """SELECT e.canonical_name, e.default_category_key, a.confidence
               FROM merchant_aliases a
               JOIN merchant_entities e ON e.id = a.entity_id
               WHERE a.normalized_alias IN (?, ?)
               ORDER BY a.confidence DESC LIMIT 1""",
            (key, legacy_key),
        ).fetchone()
        if row is not None:
            return MerchantResolution(
                row["canonical_name"],
                "alias",
                float(row["confidence"]),
                row["default_category_key"],
            )
        canonical = canonical_merchant(candidate) or canonical_merchant(
            normalize_merchant_display(candidate)
        )
        if canonical is not None:
            return MerchantResolution(canonical, "deterministic", 0.9)
        display = normalize_merchant_display(candidate) or candidate
        folded = candidate.casefold()
        confidence = 0.0 if "unclear" in folded else 0.5
        return MerchantResolution(display, "unreviewed", confidence)

    def _resolve_classification(
        self,
        connection: sqlite3.Connection,
        transaction: ParsedTransaction,
        merchant: MerchantResolution,
    ) -> ClassificationResolution:
        text = " ".join(
            (
                transaction.booking_text,
                transaction.purpose,
                transaction.counterparty,
                merchant.merchant,
            )
        )
        rules = connection.execute(
            """SELECT id, pattern, classification, category_key, confidence, rule_version,
                      payment_channel, direction, payment_type, merchant_pattern,
                      descriptor_pattern
               FROM classification_rules
               WHERE enabled = 1
               ORDER BY priority DESC, updated_at DESC"""
        ).fetchall()
        for rule in rules:
            if self._rule_matches(rule, transaction, merchant.merchant, text):
                return ClassificationResolution(
                    classification=rule["classification"],
                    classification_source="user",
                    classification_confidence=float(rule["confidence"]),
                    category_key=rule["category_key"],
                    category_source="user",
                    category_confidence=float(rule["confidence"]),
                    rule_version=rule["rule_version"],
                    evidence=f"user rule {rule['id']}",
                    rule_id=rule["id"],
                )
        return classify_transaction(
            transaction,
            merchant=merchant.merchant,
            merchant_default_category=merchant.default_category_key,
        )

    @staticmethod
    def _rule_matches(
        rule: sqlite3.Row,
        transaction: ParsedTransaction,
        merchant: str,
        text: str,
    ) -> bool:
        direction = str(rule["direction"] or "any")
        if direction == "debit" and transaction.amount_minor >= 0:
            return False
        if direction == "credit" and transaction.amount_minor <= 0:
            return False
        channel = rule["payment_channel"]
        if channel and channel != "any" and channel != transaction.payment_channel:
            return False
        payment_type = rule["payment_type"]
        if payment_type and not Database._safe_text_match(transaction.booking_text, payment_type):
            return False
        merchant_pattern = rule["merchant_pattern"]
        if merchant_pattern and not Database._safe_text_match(merchant, merchant_pattern):
            return False
        descriptor_pattern = rule["descriptor_pattern"]
        descriptor_text = " ".join(
            (transaction.purpose, transaction.booking_text, transaction.counterparty)
        )
        if descriptor_pattern and not Database._safe_text_match(
            descriptor_text, descriptor_pattern
        ):
            return False
        pattern = str(rule["pattern"] or "")
        if pattern and not Database._safe_text_match(text, pattern):
            return False
        return bool(pattern or merchant_pattern or descriptor_pattern)

    @staticmethod
    def _normalize_rule_text(value: str) -> str:
        folded = " ".join(value.casefold().split())
        folded = re.sub(r"(?<=\w)-(?=\w)", " ", folded)
        folded = re.sub(r"[^\wäöüß]+", " ", folded, flags=re.UNICODE)
        return " ".join(folded.split())

    @staticmethod
    def _safe_text_match(haystack: str, needle: str) -> bool:
        from personal_finance_assistant.ingestion.classification import _phrase_present

        folded = Database._normalize_rule_text(haystack)
        target = Database._normalize_rule_text(needle)
        if not target:
            return False
        return _phrase_present(folded, target)

    def review_import(
        self, parsed: ParseResult, *, account_alias: str = "primary"
    ) -> DuplicateReview:
        """Find duplicate classes without exposing transaction content."""

        if not self.path.exists():
            return DuplicateReview(
                exact_file_match=False,
                reference_matches=0,
                possible_duplicates=(),
            )
        self.initialize()
        with self.session() as connection:
            exact_file_match = (
                connection.execute(
                    "SELECT 1 FROM imports WHERE file_sha256 = ?", (parsed.file_sha256,)
                ).fetchone()
                is not None
            )
            seen_content: set[str] = set()
            reference_matches = 0
            possible_duplicates: list[tuple[int, DuplicateReason]] = []
            for transaction in parsed.transactions:
                exists = (
                    connection.execute(
                        """SELECT 1 FROM transactions
                       WHERE account_alias = ? AND dedupe_key = ? LIMIT 1""",
                        (account_alias, transaction.dedupe_key),
                    ).fetchone()
                    is not None
                )
                if transaction.dedupe_basis == "reference":
                    if exists:
                        reference_matches += 1
                elif transaction.dedupe_key in seen_content:
                    possible_duplicates.append(
                        (transaction.row_number, "content_duplicate_in_file")
                    )
                elif exists:
                    possible_duplicates.append((transaction.row_number, "content_match_existing"))
                seen_content.add(transaction.dedupe_key)
        return DuplicateReview(
            exact_file_match=exact_file_match,
            reference_matches=reference_matches,
            possible_duplicates=tuple(possible_duplicates),
        )

    def preview_import_rows(
        self, parsed: ParseResult, *, account_alias: str = "primary"
    ) -> tuple[tuple[ImportRowPreview, ...], DuplicateReview]:
        """Return per-row deterministic suggestions without writing financial data."""

        self.initialize()
        duplicate_review = self.review_import(parsed, account_alias=account_alias)
        possible_by_row = {
            row_number: reason for row_number, reason in duplicate_review.possible_duplicates
        }
        rows: list[ImportRowPreview] = []
        with self.session() as connection:
            for transaction in parsed.transactions:
                merchant = self._resolve_merchant(connection, transaction.merchant_candidate)
                classification = self._resolve_classification(connection, transaction, merchant)
                if transaction.dedupe_basis == "reference":
                    exists = (
                        connection.execute(
                            """SELECT 1 FROM transactions
                               WHERE account_alias = ? AND dedupe_key = ? LIMIT 1""",
                            (account_alias, transaction.dedupe_key),
                        ).fetchone()
                        is not None
                    )
                    duplicate_reason: str | None = "reference_match_existing" if exists else None
                else:
                    duplicate_reason = possible_by_row.get(transaction.row_number)
                review_required = not (
                    classification.classification_source == "user"
                    or classification.category_source == "user"
                    or _auto_confirmed(classification)
                )
                rows.append(
                    ImportRowPreview(
                        row_number=transaction.row_number,
                        booking_date=transaction.booking_date,
                        value_date=transaction.value_date,
                        booking_text=transaction.booking_text,
                        purpose=transaction.purpose,
                        counterparty=transaction.counterparty,
                        amount_minor=transaction.amount_minor,
                        currency=transaction.currency,
                        payment_channel=transaction.payment_channel,
                        merchant=merchant.merchant,
                        merchant_source=merchant.source,
                        merchant_confidence=merchant.confidence,
                        classification=classification.classification,
                        classification_source=classification.classification_source,
                        classification_confidence=classification.classification_confidence,
                        category_key=classification.category_key,
                        category_source=classification.category_source,
                        category_confidence=classification.category_confidence,
                        review_required=review_required,
                        duplicate_reason=duplicate_reason,
                        evidence=classification.evidence,
                        merchant_learnable=not is_ambiguous_merchant(transaction.merchant_candidate)
                        and not is_ambiguous_merchant(merchant.merchant),
                        descriptor_pattern=learnable_descriptor(
                            transaction.purpose or transaction.counterparty
                        ),
                    )
                )
        return tuple(rows), duplicate_review

    def _apply_import_override(
        self,
        connection: sqlite3.Connection,
        transaction_id: str,
        override: ImportRowOverride,
        now: str,
    ) -> None:
        """Apply explicit owner edits during the same import transaction."""

        if override.merchant is not None:
            merchant = " ".join(override.merchant.split()).strip()
            if not merchant:
                raise ValueError("merchant override must not be empty")
            connection.execute(
                """INSERT INTO transaction_corrections
                   (id, transaction_id, merchant, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(transaction_id) DO UPDATE SET
                     merchant = excluded.merchant,
                     created_at = excluded.created_at""",
                (str(uuid.uuid4()), transaction_id, merchant, now),
            )
            existing_entity = connection.execute(
                "SELECT 1 FROM merchant_entities WHERE canonical_name = ?", (merchant,)
            ).fetchone()
            if existing_entity is None:
                connection.execute(
                    "INSERT INTO merchant_entities (id, canonical_name, created_at) "
                    "VALUES (?, ?, ?)",
                    (str(uuid.uuid4()), merchant, now),
                )
            connection.execute(
                """UPDATE transactions
                   SET merchant_candidate = ?, merchant_source = 'user',
                       merchant_confidence = 1
                   WHERE id = ?""",
                (merchant, transaction_id),
            )
            connection.execute(
                """INSERT INTO audit_events
                   (id, event_type, entity_type, entity_id, created_at)
                   VALUES (?, 'merchant_correction', 'transaction', ?, ?)""",
                (str(uuid.uuid4()), transaction_id, now),
            )
        if override.classification is not None or override.category_key is not None:
            if (
                override.classification is not None
                and override.classification not in _ALLOWED_CLASSIFICATIONS
            ):
                raise ValueError("classification override is not allowed")
            if override.category_key is not None and override.category_key not in CATEGORY_REGISTRY:
                raise ValueError("category override is not in the registry")
            if override.classification is not None:
                connection.execute(
                    """UPDATE transactions
                       SET classification = ?, classification_source = 'user',
                           classification_confidence = 1
                       WHERE id = ?""",
                    (override.classification, transaction_id),
                )
            if override.category_key is not None:
                connection.execute(
                    """UPDATE transactions
                       SET category_key = ?, category_source = 'user',
                           category_confidence = 1
                       WHERE id = ?""",
                    (override.category_key, transaction_id),
                )
            connection.execute(
                "UPDATE transactions SET review_status = 'confirmed' WHERE id = ?",
                (transaction_id,),
            )
            connection.execute(
                """INSERT INTO audit_events
                   (id, event_type, entity_type, entity_id, created_at)
                   VALUES (?, 'classification_correction', 'transaction', ?, ?)""",
                (str(uuid.uuid4()), transaction_id, now),
            )
        if override.note is not None:
            note = " ".join(override.note.split()).strip()[:1000]
            connection.execute(
                "UPDATE transactions SET note = ? WHERE id = ?", (note, transaction_id)
            )

    def list_imports(self) -> tuple[ImportBatchInfo, ...]:
        """Return safe aggregate information for all persisted import batches."""

        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT id, file_sha256, source_format, encoding, transaction_count,
                          inserted_count, exact_duplicate_count, possible_duplicate_count,
                          created_at, status
                   FROM imports ORDER BY created_at DESC"""
            ).fetchall()
        return tuple(
            ImportBatchInfo(
                import_id=row["id"],
                file_sha256=row["file_sha256"],
                source_format=row["source_format"],
                encoding=row["encoding"],
                transaction_count=row["transaction_count"],
                inserted_count=row["inserted_count"],
                exact_duplicate_count=row["exact_duplicate_count"],
                possible_duplicate_count=row["possible_duplicate_count"],
                created_at=row["created_at"],
                status=row["status"],
            )
            for row in rows
        )

    def undo_import(self, import_id: str, *, confirm: bool = False) -> int:
        """Delete one import batch transactionally, including split records."""

        if not confirm:
            raise ValueError("import undo requires explicit confirmation")
        self.initialize()
        with self.session() as connection:
            batch = connection.execute(
                "SELECT id FROM imports WHERE id = ?", (import_id,)
            ).fetchone()
            if batch is None:
                raise ValueError("import batch was not found")
            dependent = connection.execute(
                """SELECT 1
                   WHERE EXISTS (
                       SELECT 1 FROM audit_events
                       WHERE entity_type = 'transaction'
                         AND entity_id IN (
                             SELECT id FROM transactions WHERE import_id = ?
                         )
                   )
                   OR EXISTS (
                       SELECT 1 FROM transaction_corrections
                       WHERE transaction_id IN (
                           SELECT id FROM transactions WHERE import_id = ?
                       )
                   )
                   LIMIT 1""",
                (import_id, import_id),
            ).fetchone()
            if dependent is not None:
                raise ValueError("import batch has dependent transaction corrections")
            connection.execute(
                """DELETE FROM transaction_links
                   WHERE transaction_id IN (SELECT id FROM transactions WHERE import_id = ?)
                      OR linked_transaction_id IN (
                          SELECT id FROM transactions WHERE import_id = ?
                      )""",
                (import_id, import_id),
            )
            connection.execute(
                """DELETE FROM transaction_splits
                   WHERE transaction_id IN (SELECT id FROM transactions WHERE import_id = ?)""",
                (import_id,),
            )
            deleted = connection.execute(
                "DELETE FROM transactions WHERE import_id = ?", (import_id,)
            ).rowcount
            connection.execute("DELETE FROM imports WHERE id = ?", (import_id,))
            problems = connection.execute("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise ValueError("import undo would violate a database relationship")
        return deleted

    # ------------------------------------------------------------------
    # Analytics (split-aware)
    # ------------------------------------------------------------------

    def _flow_rows(
        self, connection: sqlite3.Connection, start: date, end: date
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT transaction_id, booking_date, amount_minor, classification,
                      category_key, merchant_candidate
               FROM transaction_flows
               WHERE booking_date >= ? AND booking_date < ?
               ORDER BY booking_date, transaction_id""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    def monthly_summary(self, month: str) -> dict[str, int]:
        """Return candidate expense/income totals for YYYY-MM, in euro cents."""

        self.initialize()
        start, end = _month_bounds(month)
        with self.session() as connection:
            flows = self._flow_rows(connection, start, end)
            row = connection.execute(
                "SELECT COUNT(*) AS transaction_count FROM transactions "
                "WHERE booking_date >= ? AND booking_date < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        expenses = sum(
            -int(item["amount_minor"])
            for item in flows
            if item["classification"] == "expense_candidate" and int(item["amount_minor"]) < 0
        )
        income = sum(
            int(item["amount_minor"])
            for item in flows
            if item["classification"] == "income_candidate" and int(item["amount_minor"]) > 0
        )
        return {
            "expenses_minor": expenses,
            "income_minor": income,
            "transaction_count": int(row["transaction_count"]),
        }

    def period_report(self, start: date, end: date) -> PeriodReport:
        """Return reproducible classified totals for a half-open date period."""

        if end <= start:
            raise ValueError("report end date must be after start date")
        self.initialize()
        with self.session() as connection:
            flows = self._flow_rows(connection, start, end)
            parent_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM transactions "
                    "WHERE booking_date >= ? AND booking_date < ?",
                    (start.isoformat(), end.isoformat()),
                ).fetchone()[0]
            )
            links = connection.execute(
                """SELECT l.transaction_id, l.linked_transaction_id, l.link_type
                   FROM transaction_links l
                   JOIN transactions current_tx ON current_tx.id = l.transaction_id
                   JOIN transactions original_tx ON original_tx.id = l.linked_transaction_id
                   WHERE current_tx.booking_date >= ? AND current_tx.booking_date < ?
                     AND original_tx.booking_date >= ? AND original_tx.booking_date < ?""",
                (start.isoformat(), end.isoformat(), start.isoformat(), end.isoformat()),
            ).fetchall()
        expenses: dict[str, int] = {}
        expenses_minor = income_minor = refunds_minor = transfers_minor = 0
        fees_minor = cash_minor = savings_minor = reversals_minor = 0
        uncategorized = 0
        for row in flows:
            amount = int(row["amount_minor"])
            classification = row["classification"]
            category = row["category_key"]
            if classification == "expense_candidate" and amount < 0:
                spent = -amount
                expenses_minor += spent
                expenses[category] = expenses.get(category, 0) + spent
                if category == "uncategorized":
                    uncategorized += spent
            elif classification == "income_candidate" and amount > 0:
                income_minor += amount
            elif classification == "refund_candidate" and amount > 0:
                refunds_minor += amount
            elif classification == "transfer_candidate":
                transfers_minor += abs(amount)
            elif classification == "fee_candidate":
                fees_minor += abs(amount)
            elif classification == "cash_withdrawal_candidate":
                cash_minor += abs(amount)
            elif classification == "savings_candidate":
                savings_minor += abs(amount)
            elif classification == "reversal_candidate":
                reversals_minor += abs(amount)

        # A linked refund or reversal offsets the original expense instead of
        # being counted a second time. Unlinked reversals stay outside net flow.
        flows_by_transaction: dict[str, list[sqlite3.Row]] = {}
        for row in flows:
            flows_by_transaction.setdefault(row["transaction_id"], []).append(row)
        for link in links:
            current_rows = flows_by_transaction.get(link["transaction_id"], [])
            original_rows = flows_by_transaction.get(link["linked_transaction_id"], [])
            if not current_rows or not original_rows:
                continue
            current_total = sum(abs(int(item["amount_minor"])) for item in current_rows)
            if current_total <= 0:
                continue
            original_expenses = [
                item
                for item in original_rows
                if item["classification"] == "expense_candidate" and int(item["amount_minor"]) < 0
            ]
            if not original_expenses:
                continue
            original_total = sum(-int(item["amount_minor"]) for item in original_expenses)
            reduction = min(current_total, original_total)
            if reduction <= 0:
                continue
            if link["link_type"] == "reversal":
                reversals_minor = max(0, reversals_minor - current_total)
            else:
                refunds_minor = max(0, refunds_minor - current_total)
            expenses_minor -= reduction
            remaining = reduction
            for item in original_expenses:
                if remaining <= 0:
                    break
                category = item["category_key"]
                available = -int(item["amount_minor"])
                taken = min(available, remaining)
                expenses[category] = expenses.get(category, 0) - taken
                if expenses.get(category) == 0:
                    expenses.pop(category, None)
                if category == "uncategorized":
                    uncategorized = max(0, uncategorized - taken)
                remaining -= taken
        return PeriodReport(
            start_date=start,
            end_date=end,
            expenses_minor=expenses_minor,
            income_minor=income_minor,
            refunds_minor=refunds_minor,
            transfers_minor=transfers_minor,
            uncategorized_expenses_minor=uncategorized,
            category_expenses=tuple(
                CategoryTotal(key, amount) for key, amount in sorted(expenses.items())
            ),
            transaction_count=parent_count,
            fees_minor=fees_minor,
            cash_withdrawals_minor=cash_minor,
            savings_minor=savings_minor,
            reversals_minor=reversals_minor,
        )

    def merchant_expenses(
        self,
        start: date,
        end: date,
        *,
        limit: int = 20,
    ) -> tuple[MerchantTotal, ...]:
        """Return the largest classified expense merchants in a period."""

        if end <= start or limit < 1 or limit > 100:
            raise ValueError("invalid merchant query bounds")
        self.initialize()
        with self.session() as connection:
            flows = self._flow_rows(connection, start, end)
        totals: dict[str, list[int]] = {}
        parent_ids: dict[str, set[str]] = {}
        for row in flows:
            if row["classification"] != "expense_candidate" or int(row["amount_minor"]) >= 0:
                continue
            merchant = row["merchant_candidate"] or "Unresolved merchant"
            bucket = totals.setdefault(merchant, [0, 0])
            bucket[0] += -int(row["amount_minor"])
            parent_ids.setdefault(merchant, set()).add(row["transaction_id"])
        for merchant, ids in parent_ids.items():
            totals[merchant][1] = len(ids)
        ranked = sorted(totals.items(), key=lambda item: (-item[1][0], item[0]))
        return tuple(
            MerchantTotal(merchant, values[0], values[1]) for merchant, values in ranked[:limit]
        )

    def weekly_trend(self, start: date, end: date) -> tuple[WeeklyTrend, ...]:
        """Return Monday-based weekly totals for a half-open date period."""

        if end <= start:
            raise ValueError("trend end date must be after start date")
        self.initialize()
        with self.session() as connection:
            flows = self._flow_rows(connection, start, end)
        totals: dict[date, list[int]] = {}
        for row in flows:
            booking_date = date.fromisoformat(row["booking_date"])
            week_start = booking_date.fromordinal(booking_date.toordinal() - booking_date.weekday())
            bucket = totals.setdefault(week_start, [0, 0])
            amount = int(row["amount_minor"])
            if row["classification"] == "expense_candidate" and amount < 0:
                bucket[0] += -amount
            elif row["classification"] == "income_candidate" and amount > 0:
                bucket[1] += amount
        return tuple(
            WeeklyTrend(week, values[0], values[1]) for week, values in sorted(totals.items())
        )

    def financial_overview(
        self,
        start: date,
        end: date,
        *,
        baseline_start: date | None = None,
        baseline_end: date | None = None,
    ) -> FinancialOverview:
        """Return deterministic cash-flow metrics for a period and optional baseline.

        Net cash flow is ``income + refunds - expenses - fees``. Unlinked
        reversals remain visible in reconciliation but are not counted as
        ordinary income or spending until the owner links them to an original
        transaction.
        """

        if end <= start:
            raise ValueError("overview end date must be after start date")
        if (baseline_start is None) != (baseline_end is None):
            raise ValueError("baseline start and end must be provided together")
        if baseline_start is not None and (baseline_end is None or baseline_end <= baseline_start):
            raise ValueError("baseline end date must be after baseline start date")
        report = self.period_report(start, end)
        with self.session() as connection:
            unresolved = connection.execute(
                """SELECT COUNT(*) FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?
                     AND (review_status != 'confirmed' OR classification = 'unknown')""",
                (start.isoformat(), end.isoformat()),
            ).fetchone()[0]
        net = report.income_minor + report.refunds_minor - report.expenses_minor - report.fees_minor
        savings_rate = round(net * 100 / report.income_minor) if report.income_minor else None
        if report.transaction_count == 0:
            quality = "no_data"
        elif int(unresolved) == 0:
            quality = "complete"
        else:
            quality = "review_needed"
        return FinancialOverview(
            start,
            end,
            baseline_start,
            baseline_end,
            report.income_minor,
            report.expenses_minor,
            report.refunds_minor,
            report.transfers_minor,
            report.fees_minor,
            net,
            savings_rate,
            report.transaction_count,
            quality,
            uncategorized_expenses_minor=report.uncategorized_expenses_minor,
            categorized_expenses_minor=report.categorized_expenses_minor,
            reversals_minor=report.reversals_minor,
            cash_withdrawals_minor=report.cash_withdrawals_minor,
            savings_minor=report.savings_minor,
        )

    def list_transactions(
        self,
        start: date,
        end: date,
        *,
        search: str | None = None,
        category_key: str | None = None,
        classification: str | None = None,
        review_status: str | None = None,
        merchant: str | None = None,
        uncategorized_only: bool = False,
        transaction_ids: tuple[str, ...] | None = None,
        sort_by: str = "date",
        sort_dir: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[TransactionRecord, ...]:
        """Return a bounded owner-visible transaction list for local interfaces."""

        records, _ = self.transaction_page(
            start,
            end,
            search=search,
            category_key=category_key,
            classification=classification,
            review_status=review_status,
            merchant=merchant,
            uncategorized_only=uncategorized_only,
            transaction_ids=transaction_ids,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
            offset=offset,
        )
        return records

    def transaction_page(
        self,
        start: date,
        end: date,
        *,
        search: str | None = None,
        category_key: str | None = None,
        classification: str | None = None,
        review_status: str | None = None,
        merchant: str | None = None,
        uncategorized_only: bool = False,
        transaction_ids: tuple[str, ...] | None = None,
        sort_by: str = "date",
        sort_dir: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[tuple[TransactionRecord, ...], int]:
        if end <= start or limit < 1 or limit > 500 or offset < 0:
            raise ValueError("invalid transaction query bounds")
        sort_columns = {
            "date": "booking_date",
            "amount": "amount_minor",
            "merchant": "merchant_candidate",
            "category": "category_key",
            "status": "review_status",
        }
        if sort_by not in sort_columns:
            raise ValueError("unsupported sort field")
        direction = "DESC" if sort_dir.casefold() != "asc" else "ASC"
        self.initialize()
        clauses = ["booking_date >= ?", "booking_date < ?"]
        parameters: list[object] = [start.isoformat(), end.isoformat()]
        if search:
            clauses.append(
                "(merchant_candidate LIKE ? OR counterparty LIKE ? OR description LIKE ?)"
            )
            term = f"%{search}%"
            parameters.extend((term, term, term))
        if category_key:
            clauses.append("category_key = ?")
            parameters.append(category_key)
        if classification:
            clauses.append("classification = ?")
            parameters.append(classification)
        if review_status:
            clauses.append("review_status = ?")
            parameters.append(review_status)
        if merchant:
            clauses.append("merchant_candidate = ?")
            parameters.append(merchant)
        if uncategorized_only:
            clauses.append("category_key = 'uncategorized'")
        if transaction_ids:
            placeholders = ", ".join("?" for _ in transaction_ids)
            clauses.append(f"id IN ({placeholders})")
            parameters.extend(transaction_ids)
        where = " AND ".join(clauses)
        with self.session() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM transactions WHERE {where}", parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT id, booking_date, amount_minor, currency, merchant_candidate,
                           counterparty, description, classification, category_key,
                           review_status, payment_channel, merchant_source,
                           merchant_confidence, classification_source,
                           classification_confidence, category_source,
                           category_confidence, evidence, note
                    FROM transactions
                    WHERE {where}
                    ORDER BY {sort_columns[sort_by]} {direction}, id {direction}
                    LIMIT ? OFFSET ?""",
                (*parameters, limit, offset),
            ).fetchall()
            split_rows: list[sqlite3.Row] = []
            row_ids = [row["id"] for row in rows]
            if row_ids:
                placeholders = ", ".join("?" for _ in row_ids)
                split_rows = connection.execute(
                    f"""SELECT transaction_id, category_key FROM transaction_splits
                        WHERE transaction_id IN ({placeholders})
                        ORDER BY id""",
                    row_ids,
                ).fetchall()
        splits: dict[str, list[str]] = {}
        for row in split_rows:
            splits.setdefault(row["transaction_id"], []).append(row["category_key"])
        records = tuple(
            TransactionRecord(
                transaction_id=row["id"],
                booking_date=date.fromisoformat(row["booking_date"]),
                amount_minor=int(row["amount_minor"]),
                currency=row["currency"],
                merchant=row["merchant_candidate"],
                counterparty=row["counterparty"],
                description=row["description"],
                classification=row["classification"],
                category_key=row["category_key"],
                review_status=row["review_status"],
                payment_channel=row["payment_channel"],
                merchant_source=row["merchant_source"],
                merchant_confidence=float(row["merchant_confidence"]),
                classification_source=row["classification_source"],
                classification_confidence=float(row["classification_confidence"]),
                category_source=row["category_source"],
                category_confidence=float(row["category_confidence"]),
                evidence=row["evidence"],
                note=row["note"],
                has_split=row["id"] in splits,
                split_categories=tuple(splits.get(row["id"], ())),
            )
            for row in rows
        )
        return records, total

    def category_transaction_ids(
        self, start: date, end: date, category_key: str, *, limit: int = 10
    ) -> tuple[str, ...]:
        """Return bounded evidence IDs without exposing row content in logs."""

        if end <= start or limit < 1 or limit > 50:
            raise ValueError("invalid evidence query bounds")
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT DISTINCT transaction_id, ABS(amount_minor) AS magnitude
                   FROM transaction_flows
                   WHERE booking_date >= ? AND booking_date < ?
                     AND category_key = ?
                     AND classification = 'expense_candidate'
                   ORDER BY magnitude DESC, transaction_id
                   LIMIT ?""",
                (start.isoformat(), end.isoformat(), category_key, limit),
            ).fetchall()
        return tuple(row["transaction_id"] for row in rows)

    def top_expense_transactions(
        self, start: date, end: date, *, limit: int = 5
    ) -> tuple[TransactionRecord, ...]:
        return self.list_transactions(
            start,
            end,
            classification="expense_candidate",
            sort_by="amount",
            sort_dir="asc",
            limit=limit,
        )

    def reconcile_period(self, start: date, end: date) -> LedgerReconciliation:
        """Return signed-ledger aggregates alongside classified flow totals."""

        if end <= start:
            raise ValueError("reconciliation end date must be after start date")
        self.initialize()
        with self.session() as connection:
            flows = self._flow_rows(connection, start, end)
            parents = int(
                connection.execute(
                    "SELECT COUNT(*) FROM transactions "
                    "WHERE booking_date >= ? AND booking_date < ?",
                    (start.isoformat(), end.isoformat()),
                ).fetchone()[0]
            )
        debit = credit = expense = income = refund = 0
        transfer = transfer_in = transfer_out = unknown = 0
        fee = cash = savings = savings_in = savings_out = reversal = 0
        unexplained_debit = unexplained_credit = 0
        for row in flows:
            amount = int(row["amount_minor"])
            classification = row["classification"]
            if amount < 0:
                debit += -amount
            else:
                credit += amount
            if classification == "expense_candidate" and amount < 0:
                expense += -amount
            elif classification == "income_candidate" and amount > 0:
                income += amount
            elif classification == "refund_candidate" and amount > 0:
                refund += amount
            elif classification == "transfer_candidate":
                transfer += abs(amount)
                if amount < 0:
                    transfer_out += -amount
                else:
                    transfer_in += amount
            elif classification == "fee_candidate":
                fee += abs(amount)
            elif classification == "cash_withdrawal_candidate":
                cash += abs(amount)
            elif classification == "savings_candidate":
                savings += abs(amount)
                if amount < 0:
                    savings_out += -amount
                else:
                    savings_in += amount
            elif classification == "reversal_candidate":
                reversal += abs(amount)
            elif classification == "unknown":
                unknown += abs(amount)
                if amount < 0:
                    unexplained_debit += -amount
                else:
                    unexplained_credit += amount
        explained_debit = expense + fee + cash + savings_out + transfer_out + unexplained_debit
        explained_credit = (
            income + refund + reversal + savings_in + transfer_in + unexplained_credit
        )
        return LedgerReconciliation(
            start,
            end,
            parents,
            debit,
            credit,
            expense,
            income,
            refund,
            transfer,
            unknown,
            fee_minor=fee,
            cash_minor=cash,
            savings_minor=savings,
            reversal_minor=reversal,
            transfer_in_minor=transfer_in,
            transfer_out_minor=transfer_out,
            unexplained_debit_minor=max(0, debit - explained_debit),
            unexplained_credit_minor=max(0, credit - explained_credit),
        )

    def list_review_candidates(self, *, limit: int = 50) -> tuple[ReviewCandidate, ...]:
        """Return uncertain transactions for explicit local owner review."""

        if limit < 1 or limit > 500:
            raise ValueError("review limit must be between 1 and 500")
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT id, booking_date, amount_minor, merchant_candidate,
                          merchant_source, classification, classification_source,
                          category_key
                   FROM transactions
                   WHERE review_status = 'needs_review'
                      OR classification = 'unknown'
                   ORDER BY booking_date DESC, id
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return tuple(
            ReviewCandidate(
                transaction_id=row["id"],
                booking_date=date.fromisoformat(row["booking_date"]),
                amount_minor=int(row["amount_minor"]),
                merchant=row["merchant_candidate"],
                classification=row["classification"],
                category_key=row["category_key"],
                needs_merchant_review=row["merchant_source"] == "unreviewed",
                needs_classification_review=(
                    row["classification_source"] == "unreviewed"
                    or row["classification"] == "unknown"
                ),
            )
            for row in rows
        )

    def reprocess_classifications(self) -> int:
        """Reapply current generic rules without overwriting user decisions."""

        self.initialize()
        self.ensure_write_capacity()
        changed = 0
        with self.session() as connection:
            rows = connection.execute(
                """SELECT id, booking_date, value_date, booking_text, description,
                          counterparty, merchant_candidate, merchant_source,
                          amount_minor, currency, dedupe_key, dedupe_basis, payment_channel
                   FROM transactions
                   WHERE classification_source != 'user' AND category_source != 'user'
                     AND review_status != 'dismissed'"""
            ).fetchall()
            for row in rows:
                transaction = ParsedTransaction(
                    booking_date=date.fromisoformat(row["booking_date"]),
                    value_date=(
                        date.fromisoformat(row["value_date"]) if row["value_date"] else None
                    ),
                    booking_text=row["booking_text"],
                    purpose=row["description"],
                    counterparty=row["counterparty"],
                    merchant_candidate=row["merchant_candidate"],
                    amount_minor=int(row["amount_minor"]),
                    currency=row["currency"],
                    info="",
                    classification="unknown",
                    dedupe_key=row["dedupe_key"],
                    dedupe_basis=row["dedupe_basis"],
                    row_number=0,
                    payment_channel=row["payment_channel"],
                )
                merchant = self._resolve_merchant(connection, row["merchant_candidate"])
                resolution = self._resolve_classification(connection, transaction, merchant)
                review_status = "confirmed" if _auto_confirmed(resolution) else "needs_review"
                result = connection.execute(
                    """UPDATE transactions
                       SET classification = ?, classification_source = ?,
                           classification_confidence = ?, category_key = ?,
                           category_source = ?, category_confidence = ?,
                           review_status = ?, evidence = ?
                       WHERE id = ?
                         AND classification_source != 'user'
                         AND category_source != 'user'
                         AND review_status != 'dismissed'""",
                    (
                        resolution.classification,
                        resolution.classification_source,
                        resolution.classification_confidence,
                        resolution.category_key,
                        resolution.category_source,
                        resolution.category_confidence,
                        review_status,
                        resolution.evidence,
                        row["id"],
                    ),
                )
                changed += result.rowcount
        return changed

    # ------------------------------------------------------------------
    # Transaction correction and review
    # ------------------------------------------------------------------

    def _transaction_exists(self, connection: sqlite3.Connection, transaction_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
            is not None
        )

    def correct_transaction_classification(
        self,
        transaction_id: str,
        classification: str,
        category_key: str,
        *,
        note: str | None = None,
    ) -> None:
        """Store an explicit review decision for flow and category."""

        if classification not in _ALLOWED_CLASSIFICATIONS or not category_key:
            raise ValueError("classification and category are required")
        if category_key not in CATEGORY_REGISTRY:
            raise ValueError("category is not in the registry")
        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
        with self.session() as connection:
            if not self._transaction_exists(connection, transaction_id):
                raise ValueError("transaction was not found")
            connection.execute(
                """UPDATE transactions
                   SET classification = ?, classification_source = 'user',
                       classification_confidence = 1,
                       category_key = ?, category_source = 'user',
                       category_confidence = 1,
                       review_status = 'confirmed',
                       note = COALESCE(?, note)
                   WHERE id = ?""",
                (classification, category_key, note, transaction_id),
            )
            connection.execute(
                """INSERT INTO audit_events
                   (id, event_type, entity_type, entity_id, created_at)
                   VALUES (?, 'classification_correction', 'transaction', ?, ?)""",
                (str(uuid.uuid4()), transaction_id, now),
            )

    def correct_transaction_merchant(self, transaction_id: str, merchant: str) -> None:
        """Persist a user correction that outranks future alias resolution."""

        merchant = " ".join(merchant.split()).strip()
        if not merchant:
            raise ValueError("merchant correction is required")
        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
        with self.session() as connection:
            if not self._transaction_exists(connection, transaction_id):
                raise ValueError("transaction was not found")
            connection.execute(
                """INSERT INTO transaction_corrections (id, transaction_id, merchant, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(transaction_id) DO UPDATE SET
                     merchant = excluded.merchant,
                     created_at = excluded.created_at""",
                (str(uuid.uuid4()), transaction_id, merchant, now),
            )
            existing_entity = connection.execute(
                "SELECT 1 FROM merchant_entities WHERE canonical_name = ?", (merchant,)
            ).fetchone()
            if existing_entity is None:
                connection.execute(
                    "INSERT INTO merchant_entities (id, canonical_name, created_at) "
                    "VALUES (?, ?, ?)",
                    (str(uuid.uuid4()), merchant, now),
                )
            connection.execute(
                """UPDATE transactions
                   SET merchant_candidate = ?, merchant_source = 'user',
                       merchant_confidence = 1
                   WHERE id = ?""",
                (merchant, transaction_id),
            )
            connection.execute(
                """INSERT INTO audit_events
                   (id, event_type, entity_type, entity_id, created_at)
                   VALUES (?, 'merchant_correction', 'transaction', ?, ?)""",
                (str(uuid.uuid4()), transaction_id, now),
            )

    def set_transaction_note(self, transaction_id: str, note: str) -> None:
        note = " ".join(note.split()).strip()[:1000]
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            if not self._transaction_exists(connection, transaction_id):
                raise ValueError("transaction was not found")
            connection.execute(
                "UPDATE transactions SET note = ? WHERE id = ?", (note, transaction_id)
            )

    def confirm_transaction(self, transaction_id: str) -> None:
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            if not self._transaction_exists(connection, transaction_id):
                raise ValueError("transaction was not found")
            connection.execute(
                "UPDATE transactions SET review_status = 'confirmed' WHERE id = ?",
                (transaction_id,),
            )

    def dismiss_transaction(self, transaction_id: str) -> None:
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            if not self._transaction_exists(connection, transaction_id):
                raise ValueError("transaction was not found")
            connection.execute(
                "UPDATE transactions SET review_status = 'dismissed' WHERE id = ?",
                (transaction_id,),
            )

    def undo_transaction_correction(self, transaction_id: str) -> None:
        """Remove user overrides and reapply deterministic rules for one row."""

        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            row = connection.execute(
                """SELECT id, booking_date, value_date, booking_text, description,
                          counterparty, merchant_candidate, amount_minor, currency,
                          dedupe_key, dedupe_basis, payment_channel
                   FROM transactions WHERE id = ?""",
                (transaction_id,),
            ).fetchone()
            if row is None:
                raise ValueError("transaction was not found")
            connection.execute(
                "DELETE FROM transaction_corrections WHERE transaction_id = ?",
                (transaction_id,),
            )
            connection.execute(
                "DELETE FROM audit_events WHERE entity_type = 'transaction' AND entity_id = ?",
                (transaction_id,),
            )
            transaction = ParsedTransaction(
                booking_date=date.fromisoformat(row["booking_date"]),
                value_date=date.fromisoformat(row["value_date"]) if row["value_date"] else None,
                booking_text=row["booking_text"],
                purpose=row["description"],
                counterparty=row["counterparty"],
                merchant_candidate=row["merchant_candidate"],
                amount_minor=int(row["amount_minor"]),
                currency=row["currency"],
                info="",
                classification="unknown",
                dedupe_key=row["dedupe_key"],
                dedupe_basis=row["dedupe_basis"],
                row_number=0,
                payment_channel=row["payment_channel"],
            )
            merchant = self._resolve_merchant(connection, row["merchant_candidate"])
            resolution = self._resolve_classification(connection, transaction, merchant)
            connection.execute(
                """UPDATE transactions
                   SET merchant_candidate = ?, merchant_source = ?,
                       merchant_confidence = ?, classification = ?,
                       classification_source = ?, classification_confidence = ?,
                       category_key = ?, category_source = ?, category_confidence = ?,
                       review_status = ?, evidence = ?
                   WHERE id = ?""",
                (
                    merchant.merchant,
                    merchant.source,
                    merchant.confidence,
                    resolution.classification,
                    resolution.classification_source,
                    resolution.classification_confidence,
                    resolution.category_key,
                    resolution.category_source,
                    resolution.category_confidence,
                    "confirmed" if _auto_confirmed(resolution) else "needs_review",
                    resolution.evidence,
                    transaction_id,
                ),
            )

    def split_transaction(
        self,
        transaction_id: str,
        allocations: tuple[tuple[int, str, str], ...],
    ) -> None:
        """Store an exact category split without changing the source amount."""

        if not allocations or any(
            amount == 0 or category not in CATEGORY_REGISTRY for amount, category, _ in allocations
        ):
            raise ValueError("split allocations must contain non-zero amounts and categories")
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            row = connection.execute(
                "SELECT amount_minor FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
            if row is None:
                raise ValueError("transaction was not found")
            existing = connection.execute(
                "SELECT 1 FROM transaction_splits WHERE transaction_id = ? LIMIT 1",
                (transaction_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError("transaction already has a split")
            if sum(amount for amount, _, _ in allocations) != int(row["amount_minor"]):
                raise ValueError("split allocations must reconcile exactly to the transaction")
            now = datetime.now(UTC).isoformat()
            for amount, category, note in allocations:
                connection.execute(
                    """INSERT INTO transaction_splits
                       (id, transaction_id, amount_minor, category_key, note, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), transaction_id, amount, category, note, now),
                )
            connection.execute(
                "UPDATE transactions SET review_status = 'confirmed' WHERE id = ?",
                (transaction_id,),
            )

    def get_transaction_splits(self, transaction_id: str) -> tuple[TransactionSplit, ...]:
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT id, transaction_id, amount_minor, category_key, note
                   FROM transaction_splits WHERE transaction_id = ?
                   ORDER BY id""",
                (transaction_id,),
            ).fetchall()
        return tuple(
            TransactionSplit(
                split_id=row["id"],
                transaction_id=row["transaction_id"],
                amount_minor=int(row["amount_minor"]),
                category_key=row["category_key"],
                note=row["note"],
            )
            for row in rows
        )

    def delete_split(self, transaction_id: str) -> int:
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            if not self._transaction_exists(connection, transaction_id):
                raise ValueError("transaction was not found")
            deleted = connection.execute(
                "DELETE FROM transaction_splits WHERE transaction_id = ?",
                (transaction_id,),
            ).rowcount
            connection.execute(
                "UPDATE transactions SET review_status = 'needs_review' WHERE id = ?",
                (transaction_id,),
            )
        return deleted

    def link_transactions(
        self, transaction_id: str, linked_transaction_id: str, *, link_type: str
    ) -> None:
        if link_type not in {"refund", "reversal"}:
            raise ValueError("link type must be refund or reversal")
        if transaction_id == linked_transaction_id:
            raise ValueError("a transaction cannot link to itself")
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            if not self._transaction_exists(connection, transaction_id) or not (
                self._transaction_exists(connection, linked_transaction_id)
            ):
                raise ValueError("linked transactions were not found")
            connection.execute(
                """INSERT INTO transaction_links
                   (id, transaction_id, linked_transaction_id, link_type, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(transaction_id) DO UPDATE SET
                     linked_transaction_id = excluded.linked_transaction_id,
                     link_type = excluded.link_type""",
                (
                    str(uuid.uuid4()),
                    transaction_id,
                    linked_transaction_id,
                    link_type,
                    datetime.now(UTC).isoformat(),
                ),
            )

    # ------------------------------------------------------------------
    # Classification rules
    # ------------------------------------------------------------------

    def add_classification_rule(
        self,
        pattern: str,
        classification: str,
        category_key: str,
        *,
        confidence: float = 1.0,
        rule_version: str = "user-v1",
        priority: int = 100,
        match_type: str = "tokens",
        merchant_pattern: str | None = None,
        descriptor_pattern: str | None = None,
        payment_channel: str | None = None,
        direction: str = "any",
        payment_type: str | None = None,
        enabled: bool = True,
        label: str = "",
    ) -> None:
        """Store a user rule that takes precedence over deterministic rules."""

        pattern = " ".join(pattern.split()).strip()
        merchant_pattern = " ".join((merchant_pattern or "").split()).strip() or None
        descriptor_pattern = " ".join((descriptor_pattern or "").split()).strip() or None
        payment_type = " ".join((payment_type or "").split()).strip() or None
        if not (pattern or merchant_pattern or descriptor_pattern):
            raise ValueError("a rule needs a descriptor, merchant or pattern condition")
        if pattern and " " not in pattern and len(pattern) < 3:
            raise ValueError("a single-token rule needs at least three characters")
        if classification not in _ALLOWED_CLASSIFICATIONS:
            raise ValueError("unsupported classification")
        if category_key not in CATEGORY_REGISTRY:
            raise ValueError("category is not in the registry")
        if not 0 <= confidence <= 1:
            raise ValueError("classification confidence must be between 0 and 1")
        if priority < 0:
            raise ValueError("classification priority cannot be negative")
        if direction not in {"any", "debit", "credit"}:
            raise ValueError("direction must be any, debit or credit")
        if payment_channel and payment_channel not in _PAYMENT_CHANNELS:
            raise ValueError("unsupported payment channel")
        if match_type not in {"tokens", "phrase", "merchant"}:
            raise ValueError("unsupported match type")
        unique_pattern = pattern or descriptor_pattern or merchant_pattern or label
        assert unique_pattern is not None
        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
        with self.session() as connection:
            connection.execute(
                """INSERT INTO classification_rules
                   (id, pattern, classification, category_key, confidence, rule_version,
                    priority, created_at, updated_at, match_type, merchant_pattern,
                    descriptor_pattern, payment_channel, direction, payment_type,
                    enabled, label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(pattern) DO UPDATE SET
                     classification = excluded.classification,
                     category_key = excluded.category_key,
                     confidence = excluded.confidence,
                     rule_version = excluded.rule_version,
                     priority = excluded.priority,
                     match_type = excluded.match_type,
                     merchant_pattern = excluded.merchant_pattern,
                     descriptor_pattern = excluded.descriptor_pattern,
                     payment_channel = excluded.payment_channel,
                     direction = excluded.direction,
                     payment_type = excluded.payment_type,
                     enabled = excluded.enabled,
                     label = excluded.label,
                     updated_at = excluded.updated_at""",
                (
                    str(uuid.uuid4()),
                    unique_pattern,
                    classification,
                    category_key,
                    confidence,
                    rule_version,
                    priority,
                    now,
                    now,
                    match_type,
                    merchant_pattern,
                    descriptor_pattern,
                    payment_channel,
                    direction,
                    payment_type,
                    int(enabled),
                    label,
                ),
            )

    def list_classification_rules(self) -> tuple[ClassificationRuleInfo, ...]:
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT id, pattern, classification, category_key, confidence, priority,
                          match_type, merchant_pattern, descriptor_pattern, payment_channel,
                          direction, payment_type, enabled, rule_version, created_at, updated_at,
                          label
                   FROM classification_rules ORDER BY priority DESC, updated_at DESC"""
            ).fetchall()
        return tuple(
            ClassificationRuleInfo(
                rule_id=row["id"],
                pattern=row["pattern"],
                classification=row["classification"],
                category_key=row["category_key"],
                confidence=float(row["confidence"]),
                priority=int(row["priority"]),
                match_type=row["match_type"],
                merchant_pattern=row["merchant_pattern"],
                descriptor_pattern=row["descriptor_pattern"],
                payment_channel=row["payment_channel"],
                direction=row["direction"],
                payment_type=row["payment_type"],
                enabled=bool(row["enabled"]),
                rule_version=row["rule_version"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                label=row["label"],
            )
            for row in rows
        )

    def delete_classification_rule(self, rule_id: str) -> bool:
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            return (
                connection.execute(
                    "DELETE FROM classification_rules WHERE id = ?", (rule_id,)
                ).rowcount
                > 0
            )

    # ------------------------------------------------------------------
    # Merchant management
    # ------------------------------------------------------------------

    def add_merchant_alias(
        self,
        alias: str,
        canonical_name: str,
        *,
        confidence: float = 1.0,
        default_category_key: str | None = None,
    ) -> None:
        """Store a deterministic alias without changing existing corrections."""

        alias = " ".join(alias.split()).strip()
        canonical_name = " ".join(canonical_name.split()).strip()
        if not alias or not canonical_name:
            raise ValueError("merchant alias and canonical name are required")
        if not 0 <= confidence <= 1:
            raise ValueError("merchant confidence must be between 0 and 1")
        if default_category_key is not None and default_category_key not in CATEGORY_REGISTRY:
            raise ValueError("category is not in the registry")
        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
        normalized = normalize_alias_key(alias)
        with self.session() as connection:
            entity = connection.execute(
                "SELECT id FROM merchant_entities WHERE canonical_name = ?",
                (canonical_name,),
            ).fetchone()
            entity_id = entity["id"] if entity else str(uuid.uuid4())
            if entity is None:
                connection.execute(
                    "INSERT INTO merchant_entities (id, canonical_name, created_at) "
                    "VALUES (?, ?, ?)",
                    (entity_id, canonical_name, now),
                )
            if default_category_key is not None:
                connection.execute(
                    "UPDATE merchant_entities SET default_category_key = ? WHERE id = ?",
                    (default_category_key, entity_id),
                )
            connection.execute(
                """INSERT INTO merchant_aliases
                   (id, entity_id, alias, normalized_alias, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(normalized_alias) DO UPDATE SET
                     entity_id = excluded.entity_id,
                     alias = excluded.alias,
                     confidence = excluded.confidence""",
                (
                    str(uuid.uuid4()),
                    entity_id,
                    alias,
                    normalized,
                    confidence,
                    now,
                ),
            )

    def remove_merchant_alias(self, alias: str) -> int:
        self.initialize()
        self.ensure_write_capacity()
        normalized = normalize_alias_key(alias)
        with self.session() as connection:
            return connection.execute(
                "DELETE FROM merchant_aliases WHERE normalized_alias = ?", (normalized,)
            ).rowcount

    def set_merchant_default_category(self, canonical_name: str, category_key: str | None) -> None:
        if category_key is not None and category_key not in CATEGORY_REGISTRY:
            raise ValueError("category is not in the registry")
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            updated = connection.execute(
                "UPDATE merchant_entities SET default_category_key = ? WHERE canonical_name = ?",
                (category_key, canonical_name),
            ).rowcount
            if updated == 0:
                raise ValueError("merchant entity was not found")

    def merge_merchants(
        self, source_canonical: str, target_canonical: str, *, confirm: bool = False
    ) -> int:
        if not confirm:
            raise ValueError("merchant merge requires explicit confirmation")
        source_canonical = " ".join(source_canonical.split()).strip()
        target_canonical = " ".join(target_canonical.split()).strip()
        if not source_canonical or not target_canonical or source_canonical == target_canonical:
            raise ValueError("two distinct merchant names are required")
        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
        with self.session() as connection:
            target = connection.execute(
                "SELECT id FROM merchant_entities WHERE canonical_name = ?",
                (target_canonical,),
            ).fetchone()
            if target is None:
                raise ValueError("target merchant entity was not found")
            source = connection.execute(
                "SELECT id FROM merchant_entities WHERE canonical_name = ?",
                (source_canonical,),
            ).fetchone()
            if source is None:
                raise ValueError("source merchant entity was not found")
            moved = connection.execute(
                "UPDATE transactions SET merchant_candidate = ? WHERE merchant_candidate = ?",
                (target_canonical, source_canonical),
            ).rowcount
            connection.execute(
                "UPDATE merchant_aliases SET entity_id = ? WHERE entity_id = ?",
                (target["id"], source["id"]),
            )
            connection.execute(
                """INSERT INTO merchant_aliases
                   (id, entity_id, alias, normalized_alias, confidence, created_at)
                   VALUES (?, ?, ?, ?, 0.9, ?)
                   ON CONFLICT(normalized_alias) DO UPDATE SET entity_id = excluded.entity_id""",
                (
                    str(uuid.uuid4()),
                    target["id"],
                    source_canonical,
                    normalize_alias_key(source_canonical),
                    now,
                ),
            )
            connection.execute("DELETE FROM merchant_entities WHERE id = ?", (source["id"],))
            connection.execute(
                """INSERT INTO audit_events
                   (id, event_type, entity_type, entity_id, created_at)
                   VALUES (?, 'merchant_merge', 'merchant', ?, ?)""",
                (str(uuid.uuid4()), target["id"], now),
            )
        return int(moved)

    def list_merchant_entities(self) -> tuple[MerchantEntityInfo, ...]:
        self.initialize()
        with self.session() as connection:
            entities = connection.execute(
                """SELECT id, canonical_name, default_category_key
                   FROM merchant_entities ORDER BY canonical_name"""
            ).fetchall()
            result: list[MerchantEntityInfo] = []
            for entity in entities:
                aliases = tuple(
                    row["alias"]
                    for row in connection.execute(
                        "SELECT alias FROM merchant_aliases WHERE entity_id = ? ORDER BY alias",
                        (entity["id"],),
                    ).fetchall()
                )
                stats = connection.execute(
                    """SELECT COUNT(*) AS count, COALESCE(SUM(ABS(amount_minor)), 0) AS total
                       FROM transactions WHERE merchant_candidate = ?""",
                    (entity["canonical_name"],),
                ).fetchone()
                result.append(
                    MerchantEntityInfo(
                        entity_id=entity["id"],
                        canonical_name=entity["canonical_name"],
                        default_category_key=entity["default_category_key"],
                        aliases=aliases,
                        transaction_count=int(stats["count"]),
                        total_minor=int(stats["total"]),
                    )
                )
        return tuple(result)

    def find_merchant_names(self) -> tuple[str, ...]:
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT DISTINCT merchant_candidate FROM transactions
                   WHERE merchant_candidate != '' ORDER BY merchant_candidate"""
            ).fetchall()
        return tuple(row["merchant_candidate"] for row in rows)

    # ------------------------------------------------------------------
    # Budgets and recurring payments
    # ------------------------------------------------------------------

    def set_budget(self, month: str, category_key: str, limit_minor: int) -> None:
        if len(month) != 7 or month[4] != "-" or limit_minor < 0:
            raise ValueError("budget month and non-negative limit are required")
        if category_key not in CATEGORY_REGISTRY:
            raise ValueError("category is not in the registry")
        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
        with self.session() as connection:
            connection.execute(
                """INSERT INTO budgets (id, month, category_key, limit_minor, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(month, category_key) DO UPDATE SET
                     limit_minor = excluded.limit_minor""",
                (str(uuid.uuid4()), month, category_key, limit_minor, now),
            )

    def delete_budget(self, month: str, category_key: str) -> bool:
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            return (
                connection.execute(
                    "DELETE FROM budgets WHERE month = ? AND category_key = ?",
                    (month, category_key),
                ).rowcount
                > 0
            )

    def list_budgets(self, month: str) -> tuple[tuple[str, int], ...]:
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                "SELECT category_key, limit_minor FROM budgets WHERE month = ? "
                "ORDER BY category_key",
                (month,),
            ).fetchall()
        return tuple((row["category_key"], int(row["limit_minor"])) for row in rows)

    def _month_expense_totals(
        self, connection: sqlite3.Connection, month: str
    ) -> tuple[int, int, int]:
        start, end = _month_bounds(month)
        flows = self._flow_rows(connection, start, end)
        total = 0
        uncategorized = 0
        for row in flows:
            if row["classification"] == "expense_candidate" and int(row["amount_minor"]) < 0:
                amount = -int(row["amount_minor"])
                total += amount
                if row["category_key"] == "uncategorized":
                    uncategorized += amount
        return total, total - uncategorized, uncategorized

    def budget_status(
        self, month: str, category_key: str, *, as_of: date | None = None
    ) -> BudgetStatus:
        self.initialize()
        start, end = _month_bounds(month)
        today = as_of or date.today()
        effective_end = min(today, end)
        elapsed_days = max(0, (effective_end - start).days + (1 if effective_end < end else 0))
        total_days = (end - start).days
        with self.session() as connection:
            budget = connection.execute(
                "SELECT limit_minor FROM budgets WHERE month = ? AND category_key = ?",
                (month, category_key),
            ).fetchone()
            if budget is None:
                raise ValueError("budget was not found")
            flows = self._flow_rows(connection, start, end)
            preference = connection.execute(
                "SELECT threshold_percent FROM budget_alert_preferences WHERE category_key = ?",
                (category_key,),
            ).fetchone()
        limit = int(budget["limit_minor"])
        used = 0
        total_expenses = 0
        uncategorized = 0
        for row in flows:
            if row["classification"] != "expense_candidate" or int(row["amount_minor"]) >= 0:
                continue
            amount = -int(row["amount_minor"])
            total_expenses += amount
            if row["category_key"] == "uncategorized":
                uncategorized += amount
            if row["category_key"] == category_key:
                used += amount
        projected = None
        if elapsed_days > 0 and used > 0:
            projected = round(used * total_days / elapsed_days)
        percentage = round(used * 100 / limit) if limit > 0 else 0
        if used > limit:
            status = "exceeded"
        elif projected is not None and projected > limit:
            status = "projected_over_limit"
        else:
            status = "within_limit"
        return BudgetStatus(
            month=month,
            category_key=category_key,
            limit_minor=limit,
            used_minor=used,
            remaining_minor=limit - used,
            exceeded=used > limit,
            period_start=start,
            period_end=end,
            elapsed_days=elapsed_days,
            total_days=total_days,
            percentage_used=percentage,
            projected_minor=projected,
            uncategorized_expenses_minor=uncategorized,
            complete=uncategorized == 0,
            status=status,
            alert_threshold_percent=(
                int(preference["threshold_percent"]) if preference is not None else None
            ),
        )

    def list_budget_statuses(
        self, month: str, *, as_of: date | None = None
    ) -> tuple[BudgetStatus, ...]:
        """Return all configured budgets for a month with split-aware usage."""

        self.initialize()
        with self.session() as connection:
            categories = connection.execute(
                "SELECT category_key FROM budgets WHERE month = ? ORDER BY category_key",
                (month,),
            ).fetchall()
        return tuple(
            self.budget_status(month, row["category_key"], as_of=as_of) for row in categories
        )

    def budget_month_summary(self, month: str, *, as_of: date | None = None) -> BudgetMonthSummary:
        self.initialize()
        with self.session() as connection:
            total, categorized, uncategorized = self._month_expense_totals(connection, month)
        budgets = self.list_budget_statuses(month, as_of=as_of)
        if uncategorized:
            whole, fraction = divmod(uncategorized, 100)
            disclosure = (
                f"{whole}.{fraction:02d} EUR of expenditure is not yet categorised. "
                "Category budget status is incomplete."
            )
        else:
            disclosure = "All expenditure in this month is categorised."
        return BudgetMonthSummary(
            month=month,
            total_expenses_minor=total,
            categorized_expenses_minor=categorized,
            uncategorized_expenses_minor=uncategorized,
            budgets=budgets,
            complete=uncategorized == 0,
            disclosure=disclosure,
        )

    def category_month_observations(
        self, month: str, category_key: str, end_date: date | None = None
    ) -> tuple[int, int]:
        """Return classified expense cents and count for a month-to-date window."""

        self.initialize()
        start, month_end = _month_bounds(month)
        effective_end = end_date or month_end
        with self.session() as connection:
            flows = connection.execute(
                """SELECT amount_minor, transaction_id FROM transaction_flows
                   WHERE booking_date >= ? AND booking_date < ?
                     AND category_key = ?
                     AND classification = 'expense_candidate'
                     AND amount_minor < 0""",
                (start.isoformat(), effective_end.isoformat(), category_key),
            ).fetchall()
        return sum(-int(row["amount_minor"]) for row in flows), len(
            {row["transaction_id"] for row in flows}
        )

    def monthly_trends(self, months: tuple[str, ...]) -> tuple[MonthlyTrend, ...]:
        self.initialize()
        result: list[MonthlyTrend] = []
        for month in months:
            summary = self.monthly_summary(month)
            result.append(MonthlyTrend(month, summary["expenses_minor"], summary["income_minor"]))
        return tuple(result)

    def month_flow_observations(
        self, month: str, end_date: date | None = None
    ) -> tuple[int, int, int]:
        self.initialize()
        start, month_end = _month_bounds(month)
        effective_end = end_date or month_end
        with self.session() as connection:
            flows = self._flow_rows(connection, start, effective_end)
            parents = int(
                connection.execute(
                    "SELECT COUNT(*) FROM transactions "
                    "WHERE booking_date >= ? AND booking_date < ?",
                    (start.isoformat(), effective_end.isoformat()),
                ).fetchone()[0]
            )
        expenses = sum(
            -int(row["amount_minor"])
            for row in flows
            if row["classification"] == "expense_candidate" and int(row["amount_minor"]) < 0
        )
        income = sum(
            int(row["amount_minor"])
            for row in flows
            if row["classification"] == "income_candidate" and int(row["amount_minor"]) > 0
        )
        return expenses, income, parents

    def _recurring_groups(
        self,
    ) -> dict[str, list[tuple[date, int, str, str]]]:
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT id, merchant_candidate, booking_date, category_key,
                          -amount_minor AS amount_minor
                   FROM transactions
                   WHERE classification = 'expense_candidate'
                     AND amount_minor < 0
                     AND merchant_candidate NOT LIKE '%unclear%'
                   ORDER BY merchant_candidate, booking_date"""
            ).fetchall()
        groups: dict[str, list[tuple[date, int, str, str]]] = {}
        for row in rows:
            groups.setdefault(row["merchant_candidate"], []).append(
                (
                    date.fromisoformat(row["booking_date"]),
                    int(row["amount_minor"]),
                    row["id"],
                    row["category_key"],
                )
            )
        return groups

    @staticmethod
    def _stable_segment(amounts: list[int], tolerance: int) -> bool:
        return max(amounts) - min(amounts) <= tolerance

    @staticmethod
    def _split_amount_regimes(amounts: list[int]) -> tuple[int, int] | None:
        """Return indexes of the single largest amount jump when two regimes exist."""

        if len(amounts) < 4:
            return None
        jumps = [
            (abs(amounts[index + 1] - amounts[index]), index + 1)
            for index in range(len(amounts) - 1)
        ]
        magnitude, boundary = max(jumps)
        if boundary < 2 or len(amounts) - boundary < 2:
            return None
        if magnitude < 200:
            return None
        return boundary, magnitude

    @staticmethod
    def _cadence_with_gaps(intervals: list[int], median_interval: int, allowed_spread: int) -> bool:
        """Accept one missing-history gap but reject genuinely irregular cadence."""

        filtered = [
            interval
            for interval in intervals
            if not (median_interval * 1.5 <= interval <= median_interval * 3.0)
        ]
        if not filtered:
            filtered = intervals
        if len(intervals) - len(filtered) > 1:
            return False
        return max(abs(interval - median_interval) for interval in filtered) <= allowed_spread

    def recurring_candidates(
        self,
        *,
        minimum_observations: int = 3,
        tolerance_minor: int = 100,
        max_interval_days: int = 90,
    ) -> tuple[RecurringCandidate, ...]:
        """Find repeated expenses with cadence and amount evidence.

        A merchant becomes a candidate only when the observations have a
        plausible monthly-to-quarterly cadence and stable amounts (or exactly
        one stable price change). Sporadic multi-month purchases are rejected.
        """

        self.initialize()
        self.ensure_write_capacity()
        groups = self._recurring_groups()
        with self.session() as connection:
            decisions = {
                row["merchant"]: row["decision"]
                for row in connection.execute(
                    "SELECT merchant, decision FROM recurring_decisions"
                ).fetchall()
            }
        candidates: list[RecurringCandidate] = []
        for merchant, observations in groups.items():
            if len(observations) < minimum_observations:
                continue
            categories = {item[3] for item in observations}
            if len(categories) != 1 or next(iter(categories)) not in _RECURRING_CATEGORIES:
                continue
            amounts = [amount for _, amount, _, _ in observations]
            dates = [item[0] for item in observations]
            intervals = [
                (current - previous).days
                for previous, current in zip(dates, dates[1:], strict=False)
            ]
            if not intervals:
                continue
            ordered = sorted(intervals)
            median_interval = ordered[len(ordered) // 2]
            average_interval = round(sum(intervals) / len(intervals))
            if median_interval < 20 or median_interval > max_interval_days:
                continue
            allowed_spread = max(7, round(median_interval * 0.25))
            if not self._cadence_with_gaps(intervals, median_interval, allowed_spread):
                continue
            filtered_intervals = [
                interval
                for interval in intervals
                if not (median_interval * 1.5 <= interval <= median_interval * 3.0)
            ] or intervals
            interval_spread = max(
                abs(interval - median_interval) for interval in filtered_intervals
            )
            regimes = self._split_amount_regimes(amounts)
            previous_amount = latest_amount = None
            if self._stable_segment(amounts, tolerance_minor):
                confidence = "high" if len(observations) >= 3 and interval_spread <= 7 else "medium"
            elif regimes is not None:
                boundary, _ = regimes
                before = amounts[:boundary]
                after = amounts[boundary:]
                if not (
                    self._stable_segment(before, tolerance_minor)
                    and self._stable_segment(after, tolerance_minor)
                ):
                    continue
                previous_amount = round(sum(before) / len(before))
                latest_amount = round(sum(after) / len(after))
                confidence = "probable"
            else:
                continue
            decision = decisions.get(merchant)
            if decision == "dismissed":
                continue
            confirmed = decision == "confirmed"
            candidates.append(
                RecurringCandidate(
                    merchant=merchant,
                    observations=len(observations),
                    average_amount_minor=round(sum(amounts) / len(amounts)),
                    first_date=dates[0],
                    last_date=dates[-1],
                    average_interval_days=average_interval,
                    confidence=confidence,
                    confirmed=confirmed,
                    regularity="stable" if interval_spread <= 7 else "irregular",
                    latest_amount_minor=latest_amount or amounts[-1],
                    previous_amount_minor=previous_amount,
                    status="confirmed" if confirmed else confidence,
                    supporting_transaction_ids=tuple(item[2] for item in observations),
                )
            )
        return tuple(sorted(candidates, key=lambda candidate: candidate.merchant))

    def recurring_price_changes(self) -> tuple[RecurringPriceChange, ...]:
        groups = self._recurring_groups()
        changes: list[RecurringPriceChange] = []
        for candidate in self.recurring_candidates():
            if (
                candidate.previous_amount_minor is None
                or candidate.latest_amount_minor is None
                or candidate.previous_amount_minor == candidate.latest_amount_minor
            ):
                continue
            observations = groups.get(candidate.merchant, [])
            midpoint = (candidate.previous_amount_minor + candidate.latest_amount_minor) // 2
            changed_on = candidate.last_date
            observations_before = 0
            observations_after = 0
            for observation_date, amount, _, _ in observations:
                if amount < midpoint:
                    observations_before += 1
                else:
                    if observations_after == 0:
                        changed_on = observation_date
                    observations_after += 1
            changes.append(
                RecurringPriceChange(
                    merchant=candidate.merchant,
                    old_amount_minor=candidate.previous_amount_minor,
                    new_amount_minor=candidate.latest_amount_minor,
                    changed_on=changed_on,
                    observations_before=observations_before,
                    observations_after=observations_after,
                    confidence=candidate.confidence,
                    supporting_transaction_ids=candidate.supporting_transaction_ids,
                )
            )
        return tuple(changes)

    def set_recurring_decision(self, merchant: str, decision: str) -> None:
        if not merchant.strip() or decision not in {"confirmed", "dismissed"}:
            raise ValueError("merchant and recurring decision are required")
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            connection.execute(
                """INSERT INTO recurring_decisions (merchant, decision, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(merchant) DO UPDATE SET
                     decision = excluded.decision, updated_at = excluded.updated_at""",
                (merchant, decision, datetime.now(UTC).isoformat()),
            )

    def set_budget_alert_preference(
        self, category_key: str, threshold_percent: int, *, enabled: bool = True
    ) -> None:
        if not category_key or not 1 <= threshold_percent <= 100:
            raise ValueError("alert category and threshold must be valid")
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            connection.execute(
                """INSERT INTO budget_alert_preferences
                   (category_key, threshold_percent, enabled) VALUES (?, ?, ?)
                   ON CONFLICT(category_key) DO UPDATE SET
                     threshold_percent = excluded.threshold_percent,
                     enabled = excluded.enabled""",
                (category_key, threshold_percent, int(enabled)),
            )

    def budget_alert_due(self, month: str, category_key: str) -> bool:
        self.initialize()
        with self.session() as connection:
            preference = connection.execute(
                """SELECT threshold_percent, enabled
                   FROM budget_alert_preferences WHERE category_key = ?""",
                (category_key,),
            ).fetchone()
            if preference is None or not preference["enabled"]:
                return False
            budget = connection.execute(
                "SELECT limit_minor FROM budgets WHERE month = ? AND category_key = ?",
                (month, category_key),
            ).fetchone()
            if budget is None:
                return False
            start, end = _month_bounds(month)
            flows = self._flow_rows(connection, start, end)
            used = sum(
                -int(row["amount_minor"])
                for row in flows
                if row["category_key"] == category_key
                and row["classification"] == "expense_candidate"
                and int(row["amount_minor"]) < 0
            )
            threshold = preference["threshold_percent"]
            if (
                int(budget["limit_minor"]) == 0
                or used * 100 < int(budget["limit_minor"]) * threshold
            ):
                return False
            delivered = connection.execute(
                """SELECT 1 FROM budget_alert_deliveries
                   WHERE month = ? AND category_key = ? AND threshold_percent = ?""",
                (month, category_key, threshold),
            ).fetchone()
            if delivered is not None:
                return False
            connection.execute(
                """INSERT INTO budget_alert_deliveries
                   (id, month, category_key, threshold_percent, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), month, category_key, threshold, datetime.now(UTC).isoformat()),
            )
            return True

    # ------------------------------------------------------------------
    # Operational helpers
    # ------------------------------------------------------------------

    def data_coverage(self) -> dict[str, object]:
        self.initialize()
        with self.session() as connection:
            row = connection.execute(
                """SELECT MIN(booking_date) AS first_date, MAX(booking_date) AS last_date,
                          COUNT(*) AS transaction_count FROM transactions"""
            ).fetchone()
            import_count = int(connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0])
        return {
            "first_date": row["first_date"],
            "last_date": row["last_date"],
            "transaction_count": int(row["transaction_count"]),
            "import_count": import_count,
        }

    def integrity_report(self) -> dict[str, object]:
        self.initialize()
        with self.session() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
            split_violations = [
                tuple(row)
                for row in connection.execute(
                    """SELECT t.id, t.amount_minor, COALESCE(SUM(s.amount_minor), 0)
                       FROM transactions t
                       JOIN transaction_splits s ON s.transaction_id = t.id
                       GROUP BY t.id
                       HAVING t.amount_minor != COALESCE(SUM(s.amount_minor), 0)"""
                )
            ]
        return {
            "integrity": integrity,
            "foreign_key_violations": foreign_keys,
            "split_violations": split_violations,
        }

    def backup_to(self, destination: str | Path) -> Path:
        """Create a consistent SQLite backup using SQLite's online backup API."""

        self.initialize()
        self.ensure_write_capacity()
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.session() as source:
            backup = sqlite3.connect(target)
            try:
                source.backup(backup)
            finally:
                backup.close()
        with suppress(OSError):
            target.chmod(0o600)
        return target

    def health_status(self) -> dict[str, int | bool | str | None]:
        """Return operational facts without financial content."""

        self.initialize()
        with self.session() as connection:
            return {
                "schema_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
                "database_exists": self.path.exists(),
                "import_batches": int(
                    connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
                ),
                "transactions": int(
                    connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
                ),
                "unreviewed_transactions": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM transactions WHERE review_status = 'needs_review'"
                    ).fetchone()[0]
                ),
                "latest_booking_date": connection.execute(
                    "SELECT MAX(booking_date) FROM transactions"
                ).fetchone()[0],
                "free_bytes": shutil.disk_usage(self.path.parent).free,
            }

    def purge(self, *, confirm: bool = False) -> int:
        """Delete this database and SQLite sidecars after explicit confirmation."""

        if not confirm:
            raise ValueError("database purge requires explicit confirmation")
        removed = 0
        for path in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            removed += 1
        return removed
