"""SQLite persistence with explicit transaction boundaries and minimal data retention."""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, date, datetime
from pathlib import Path

from personal_finance_assistant.domain import (
    BudgetStatus,
    CategoryTotal,
    ClassificationResolution,
    DuplicateReason,
    DuplicateReview,
    FinancialOverview,
    ImportBatchInfo,
    ImportResult,
    LedgerReconciliation,
    MerchantResolution,
    MerchantTotal,
    MonthlyTrend,
    ParsedTransaction,
    ParseResult,
    PeriodReport,
    RecurringCandidate,
    ReviewCandidate,
    TransactionRecord,
    WeeklyTrend,
)
from personal_finance_assistant.ingestion.classification import classify_transaction

SCHEMA_VERSION = 5


class StorageCapacityError(RuntimeError):
    """Raised when a write would risk exhausting the local filesystem."""


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
            # Some filesystems do not implement POSIX permission bits.
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
        with self.session() as connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {current_version} is newer than this app "
                    f"supports ({SCHEMA_VERSION}). Upgrade the application before opening it."
                )
            if current_version == SCHEMA_VERSION:
                return
            if current_version not in {0, 1, 2, 3}:
                raise RuntimeError(
                    f"No migration path exists from database schema {current_version}."
                )

            if current_version == 0:
                connection.executescript(
                    """
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

                CREATE INDEX IF NOT EXISTS idx_transactions_booking_date
                    ON transactions(booking_date);
                CREATE INDEX IF NOT EXISTS idx_transactions_merchant
                    ON transactions(merchant_candidate);
                CREATE INDEX IF NOT EXISTS idx_transactions_category
                    ON transactions(category_key);
                CREATE INDEX IF NOT EXISTS idx_transactions_dedupe
                    ON transactions(account_alias, dedupe_key);

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
                    threshold_percent INTEGER NOT NULL CHECK(
                        threshold_percent BETWEEN 1 AND 100
                    ),
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

                PRAGMA user_version = 4;
                """
                )
                current_version = 4
            elif current_version == 1:
                connection.executescript(
                    """
                    ALTER TABLE transactions ADD COLUMN merchant_source TEXT NOT NULL
                        DEFAULT 'unreviewed';
                    ALTER TABLE transactions ADD COLUMN merchant_confidence REAL NOT NULL
                        DEFAULT 0;
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
                    PRAGMA user_version = 2;
                    """
                )
                current_version = 2
            if current_version == 2:
                connection.executescript(
                    """
                    ALTER TABLE transactions ADD COLUMN classification_source TEXT NOT NULL
                        DEFAULT 'unreviewed';
                    ALTER TABLE transactions ADD COLUMN classification_confidence REAL NOT NULL
                        DEFAULT 0;
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
                    PRAGMA user_version = 3;
                    """
                )
                current_version = 3
            if current_version == 3:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS budget_alert_preferences (
                        category_key TEXT PRIMARY KEY,
                        threshold_percent INTEGER NOT NULL CHECK(
                            threshold_percent BETWEEN 1 AND 100
                        ),
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
                    PRAGMA user_version = 4;
                    """
                )
                current_version = 4
            if current_version == 4:
                connection.executescript(
                    """
                    ALTER TABLE transactions ADD COLUMN payment_channel TEXT NOT NULL
                        DEFAULT 'unknown';
                    ALTER TABLE transactions ADD COLUMN review_status TEXT NOT NULL
                        DEFAULT 'needs_review';
                    ALTER TABLE transactions ADD COLUMN subcategory_key TEXT;
                    ALTER TABLE classification_rules ADD COLUMN priority INTEGER NOT NULL
                        DEFAULT 0;
                    CREATE INDEX IF NOT EXISTS idx_transactions_review_status
                        ON transactions(review_status);
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
                    PRAGMA user_version = 5;
                    """
                )

    def import_file(
        self,
        parsed: ParseResult,
        *,
        account_alias: str = "primary",
        accept_possible_duplicates: bool = False,
    ) -> ImportResult:
        """Persist an import atomically.

        Re-importing identical file bytes is an exact no-op. Reference-backed
        duplicates are skipped. Content-only matches are treated as possible
        duplicates because two legitimate purchases can be identical.
        """

        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
        import_id = str(uuid.uuid4())
        inserted = 0
        exact_duplicates = 0
        possible_duplicates = 0
        seen_reference: set[str] = set()
        seen_content: set[str] = set()

        with self.session() as connection:
            existing_file = connection.execute(
                "SELECT id FROM imports WHERE file_sha256 = ?", (parsed.file_sha256,)
            ).fetchone()
            if existing_file:
                return ImportResult(
                    import_id=existing_file["id"],
                    inserted=0,
                    exact_duplicates=len(parsed.transactions),
                    possible_duplicates=0,
                    already_imported_file=True,
                )

            connection.execute(
                """INSERT INTO imports
                   (id, file_sha256, source_format, encoding, transaction_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
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

                resolution = self._resolve_merchant(connection, transaction.merchant_candidate)
                classification = self._resolve_classification(connection, transaction)
                connection.execute(
                    """INSERT INTO transactions (
                        id, import_id, account_alias, booking_date, value_date,
                        booking_text, description, counterparty, merchant_candidate,
                        merchant_source, merchant_confidence, amount_minor, currency,
                        classification, classification_source, classification_confidence,
                        category_key, category_source, category_confidence,
                        dedupe_key, dedupe_basis, created_at, payment_channel, review_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        import_id,
                        account_alias,
                        transaction.booking_date.isoformat(),
                        transaction.value_date.isoformat() if transaction.value_date else None,
                        transaction.booking_text,
                        transaction.purpose,
                        transaction.counterparty,
                        resolution.merchant,
                        resolution.source,
                        resolution.confidence,
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
                        (
                            "confirmed"
                            if classification.category_source == "user"
                            or classification.classification_source == "user"
                            else "needs_review"
                        ),
                    ),
                )
                inserted += 1

            connection.execute(
                """UPDATE imports SET inserted_count = ?, exact_duplicate_count = ?,
                   possible_duplicate_count = ? WHERE id = ?""",
                (inserted, exact_duplicates, possible_duplicates, import_id),
            )

        return ImportResult(
            import_id=import_id,
            inserted=inserted,
            exact_duplicates=exact_duplicates,
            possible_duplicates=possible_duplicates,
        )

    @staticmethod
    def _resolve_merchant(connection: sqlite3.Connection, candidate: str) -> MerchantResolution:
        normalized = " ".join(candidate.casefold().split())
        row = connection.execute(
            """SELECT e.canonical_name, a.confidence
               FROM merchant_aliases a
               JOIN merchant_entities e ON e.id = a.entity_id
               WHERE a.normalized_alias = ?""",
            (normalized,),
        ).fetchone()
        if row is None:
            confidence = 0.0 if "unclear" in candidate.casefold() else 0.5
            return MerchantResolution(candidate, "unreviewed", confidence)
        return MerchantResolution(row["canonical_name"], "alias", row["confidence"])

    @staticmethod
    def _resolve_classification(
        connection: sqlite3.Connection, transaction: ParsedTransaction
    ) -> ClassificationResolution:
        resolution = classify_transaction(transaction)
        text = " ".join(
            (
                transaction.booking_text,
                transaction.purpose,
                transaction.counterparty,
            )
        ).casefold()
        rules = connection.execute(
            """SELECT pattern, classification, category_key, confidence, rule_version
               FROM classification_rules ORDER BY priority DESC, updated_at DESC"""
        ).fetchall()
        for rule in rules:
            if rule["pattern"].casefold() in text:
                return ClassificationResolution(
                    rule["classification"],
                    "user",
                    rule["confidence"],
                    rule["category_key"],
                    "user",
                    rule["confidence"],
                    rule["rule_version"],
                )
        return resolution

    def add_classification_rule(
        self,
        pattern: str,
        classification: str,
        category_key: str,
        *,
        confidence: float = 1.0,
        rule_version: str = "user-v1",
        priority: int = 100,
    ) -> None:
        """Store a user rule that takes precedence over deterministic rules."""

        pattern = " ".join(pattern.split()).strip()
        if not pattern or not category_key:
            raise ValueError("classification pattern and category are required")
        if classification not in {
            "expense_candidate",
            "income_candidate",
            "transfer_candidate",
            "refund_candidate",
            "reversal_candidate",
            "fee_candidate",
            "cash_withdrawal_candidate",
            "savings_candidate",
            "unknown",
        }:
            raise ValueError("unsupported classification")
        if not 0 <= confidence <= 1:
            raise ValueError("classification confidence must be between 0 and 1")
        if priority < 0:
            raise ValueError("classification priority cannot be negative")
        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
        with self.session() as connection:
            connection.execute(
                """INSERT INTO classification_rules
                   (id, pattern, classification, category_key, confidence, rule_version,
                    priority, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(pattern) DO UPDATE SET
                     classification = excluded.classification,
                     category_key = excluded.category_key,
                     confidence = excluded.confidence,
                     rule_version = excluded.rule_version,
                     priority = excluded.priority,
                     updated_at = excluded.updated_at""",
                (
                    str(uuid.uuid4()),
                    pattern,
                    classification,
                    category_key,
                    confidence,
                    rule_version,
                    priority,
                    now,
                    now,
                ),
            )

    def correct_transaction_classification(
        self, transaction_id: str, classification: str, category_key: str
    ) -> None:
        """Store an explicit review decision for flow and category."""

        allowed = {
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
        if classification not in allowed or not category_key:
            raise ValueError("classification and category are required")
        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
        with self.session() as connection:
            transaction = connection.execute(
                "SELECT 1 FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
            if transaction is None:
                raise ValueError("transaction was not found")
            connection.execute(
                """UPDATE transactions
                   SET classification = ?, classification_source = 'user',
                       classification_confidence = 1,
                       category_key = ?, category_source = 'user',
                       category_confidence = 1,
                       review_status = 'confirmed'
                   WHERE id = ?""",
                (classification, category_key, transaction_id),
            )
            connection.execute(
                """INSERT INTO audit_events
                   (id, event_type, entity_type, entity_id, created_at)
                   VALUES (?, 'classification_correction', 'transaction', ?, ?)""",
                (str(uuid.uuid4()), transaction_id, now),
            )

    def split_transaction(
        self,
        transaction_id: str,
        allocations: tuple[tuple[int, str, str], ...],
    ) -> None:
        """Store an exact category split without changing the source amount."""

        if not allocations or any(
            amount == 0 or not category for amount, category, _ in allocations
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

    def add_merchant_alias(
        self, alias: str, canonical_name: str, *, confidence: float = 1.0
    ) -> None:
        """Store a deterministic alias without changing existing corrections."""

        alias = " ".join(alias.split()).strip()
        canonical_name = " ".join(canonical_name.split()).strip()
        if not alias or not canonical_name:
            raise ValueError("merchant alias and canonical name are required")
        if not 0 <= confidence <= 1:
            raise ValueError("merchant confidence must be between 0 and 1")
        self.initialize()
        self.ensure_write_capacity()
        now = datetime.now(UTC).isoformat()
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
                    " ".join(alias.casefold().split()),
                    confidence,
                    now,
                ),
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
            transaction = connection.execute(
                "SELECT 1 FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
            if transaction is None:
                raise ValueError("transaction was not found")
            connection.execute(
                """INSERT INTO transaction_corrections (id, transaction_id, merchant, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(transaction_id) DO UPDATE SET
                     merchant = excluded.merchant,
                     created_at = excluded.created_at""",
                (str(uuid.uuid4()), transaction_id, merchant, now),
            )
            connection.execute(
                """UPDATE transactions
                   SET merchant_candidate = ?, merchant_source = 'user',
                       merchant_confidence = 1
                   WHERE id = ?""",
                (merchant, transaction_id),
            )

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

    def list_imports(self) -> tuple[ImportBatchInfo, ...]:
        """Return safe aggregate information for all persisted import batches."""

        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT id, file_sha256, source_format, encoding, transaction_count,
                          inserted_count, exact_duplicate_count, possible_duplicate_count,
                          created_at
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
            )
            for row in rows
        )

    def undo_import(self, import_id: str, *, confirm: bool = False) -> int:
        """Delete one import batch transactionally after explicit confirmation."""

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
            deleted = connection.execute(
                "DELETE FROM transactions WHERE import_id = ?", (import_id,)
            ).rowcount
            connection.execute("DELETE FROM imports WHERE id = ?", (import_id,))
        return deleted

    def monthly_summary(self, month: str) -> dict[str, int]:
        """Return candidate expense/income totals for YYYY-MM, in euro cents."""

        self.initialize()
        start = date.fromisoformat(month + "-01")
        if start.month == 12:
            end = date(start.year + 1, 1, 1)
        else:
            end = date(start.year, start.month + 1, 1)
        with self.session() as connection:
            row = connection.execute(
                """SELECT
                     COALESCE(SUM(CASE WHEN classification = 'expense_candidate'
                                       AND amount_minor < 0 THEN -amount_minor ELSE 0 END), 0)
                         AS expenses,
                     COALESCE(SUM(CASE WHEN classification = 'income_candidate'
                                       AND amount_minor > 0 THEN amount_minor ELSE 0 END), 0)
                         AS income,
                     COUNT(*) AS transaction_count
                   FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?""",
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return {
            "expenses_minor": int(row["expenses"]),
            "income_minor": int(row["income"]),
            "transaction_count": int(row["transaction_count"]),
        }

    def period_report(self, start: date, end: date) -> PeriodReport:
        """Return reproducible classified totals for a half-open date period."""

        if end <= start:
            raise ValueError("report end date must be after start date")
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT classification, category_key, amount_minor
                   FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?
                   ORDER BY booking_date, id""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        expenses: dict[str, int] = {}
        expenses_minor = income_minor = refunds_minor = transfers_minor = 0
        uncategorized = 0
        for row in rows:
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
            transaction_count=len(rows),
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
            rows = connection.execute(
                """SELECT merchant_candidate, ABS(amount_minor) AS amount_minor, id
                   FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?
                     AND classification = 'expense_candidate'
                     AND amount_minor < 0
                   ORDER BY booking_date, id""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        totals: dict[str, list[int]] = {}
        for row in rows:
            merchant = row["merchant_candidate"] or "Unresolved merchant"
            bucket = totals.setdefault(merchant, [0, 0])
            bucket[0] += int(row["amount_minor"])
            bucket[1] += 1
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
            rows = connection.execute(
                """SELECT booking_date, amount_minor, classification
                   FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?
                   ORDER BY booking_date, id""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        totals: dict[date, list[int]] = {}
        for row in rows:
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
        """Return deterministic cash-flow metrics for a period and optional baseline."""

        if end <= start:
            raise ValueError("overview end date must be after start date")
        if (baseline_start is None) != (baseline_end is None):
            raise ValueError("baseline start and end must be provided together")
        if baseline_start is not None and (baseline_end is None or baseline_end <= baseline_start):
            raise ValueError("baseline end date must be after baseline start date")
        report = self.period_report(start, end)
        fees = 0
        with self.session() as connection:
            fee_row = connection.execute(
                """SELECT COALESCE(SUM(ABS(amount_minor)), 0)
                   FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?
                     AND classification = 'fee_candidate'""",
                (start.isoformat(), end.isoformat()),
            ).fetchone()
            unresolved = connection.execute(
                """SELECT COUNT(*) FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?
                     AND (review_status != 'confirmed' OR classification = 'unknown')""",
                (start.isoformat(), end.isoformat()),
            ).fetchone()[0]
            fees = int(fee_row[0])
        net = report.income_minor + report.refunds_minor - report.expenses_minor - fees
        savings_rate = round(net * 100 / report.income_minor) if report.income_minor else None
        quality = "complete" if int(unresolved) == 0 else "review_needed"
        return FinancialOverview(
            start,
            end,
            baseline_start,
            baseline_end,
            report.income_minor,
            report.expenses_minor,
            report.refunds_minor,
            report.transfers_minor,
            fees,
            net,
            savings_rate,
            report.transaction_count,
            quality,
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
        limit: int = 100,
    ) -> tuple[TransactionRecord, ...]:
        """Return a bounded owner-visible transaction list for local interfaces."""

        if end <= start or limit < 1 or limit > 500:
            raise ValueError("invalid transaction query bounds")
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
        parameters.append(limit)
        with self.session() as connection:
            rows = connection.execute(
                f"""SELECT id, booking_date, amount_minor, currency, merchant_candidate,
                           counterparty, description, classification, category_key,
                           review_status, payment_channel
                    FROM transactions
                    WHERE {" AND ".join(clauses)}
                    ORDER BY booking_date DESC, id DESC
                    LIMIT ?""",
                parameters,
            ).fetchall()
        return tuple(
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
            )
            for row in rows
        )

    def category_transaction_ids(
        self, start: date, end: date, category_key: str, *, limit: int = 10
    ) -> tuple[str, ...]:
        """Return bounded evidence IDs without exposing row content in logs."""

        if end <= start or limit < 1 or limit > 50:
            raise ValueError("invalid evidence query bounds")
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT id FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?
                     AND category_key = ?
                     AND classification = 'expense_candidate'
                   ORDER BY ABS(amount_minor) DESC, booking_date DESC
                   LIMIT ?""",
                (start.isoformat(), end.isoformat(), category_key, limit),
            ).fetchall()
        return tuple(row["id"] for row in rows)

    def reconcile_period(self, start: date, end: date) -> LedgerReconciliation:
        """Return signed-ledger aggregates alongside classified flow totals."""

        if end <= start:
            raise ValueError("reconciliation end date must be after start date")
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT amount_minor, classification
                   FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        debit = credit = expense = income = refund = transfer = unknown = 0
        for row in rows:
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
            elif classification == "unknown":
                unknown += abs(amount)
        return LedgerReconciliation(
            start,
            end,
            len(rows),
            debit,
            credit,
            expense,
            income,
            refund,
            transfer,
            unknown,
        )

    def list_review_candidates(self, *, limit: int = 50) -> tuple[ReviewCandidate, ...]:
        """Return uncertain transactions for explicit local owner review."""

        if limit < 1 or limit > 100:
            raise ValueError("review limit must be between 1 and 100")
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT id, booking_date, amount_minor, merchant_candidate,
                          merchant_source, classification, classification_source,
                          category_key
                   FROM transactions
                   WHERE merchant_source = 'unreviewed'
                      OR classification_source = 'unreviewed'
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
                          counterparty, merchant_candidate, amount_minor, currency,
                          dedupe_key, dedupe_basis, payment_channel
                   FROM transactions
                   WHERE classification_source != 'user' OR category_source != 'user'"""
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
                resolution = self._resolve_classification(connection, transaction)
                updates: list[object] = [
                    resolution.classification,
                    resolution.classification_confidence,
                    resolution.category_key,
                    resolution.category_confidence,
                    row["id"],
                ]
                result = connection.execute(
                    """UPDATE transactions
                       SET classification = ?, classification_confidence = ?,
                           category_key = ?, category_confidence = ?
                       WHERE id = ?
                         AND classification_source != 'user'
                         AND category_source != 'user'""",
                    updates,
                )
                changed += result.rowcount
        return changed

    def set_budget(self, month: str, category_key: str, limit_minor: int) -> None:
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

    def budget_status(self, month: str, category_key: str) -> BudgetStatus:
        self.initialize()
        with self.session() as connection:
            budget = connection.execute(
                "SELECT limit_minor FROM budgets WHERE month = ? AND category_key = ?",
                (month, category_key),
            ).fetchone()
            if budget is None:
                raise ValueError("budget was not found")
            used = connection.execute(
                """SELECT COALESCE(SUM(-amount_minor), 0) AS used
                   FROM transactions
                   WHERE substr(booking_date, 1, 7) = ?
                     AND category_key = ?
                     AND classification = 'expense_candidate'
                     AND amount_minor < 0""",
                (month, category_key),
            ).fetchone()["used"]
        limit = int(budget["limit_minor"])
        used_minor = int(used)
        return BudgetStatus(
            month,
            category_key,
            limit,
            used_minor,
            limit - used_minor,
            used_minor > limit,
        )

    def list_budget_statuses(self, month: str) -> tuple[BudgetStatus, ...]:
        """Return all configured budgets for a month with classified usage."""

        self.initialize()
        with self.session() as connection:
            categories = connection.execute(
                "SELECT category_key FROM budgets WHERE month = ? ORDER BY category_key",
                (month,),
            ).fetchall()
        return tuple(self.budget_status(month, row["category_key"]) for row in categories)

    def category_month_observations(
        self, month: str, category_key: str, end_date: date | None = None
    ) -> tuple[int, int]:
        """Return classified expense cents and count for a month-to-date window."""

        self.initialize()
        start = date.fromisoformat(f"{month}-01")
        if end_date is None:
            end_date = date(
                start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1
            )
        with self.session() as connection:
            row = connection.execute(
                """SELECT COALESCE(SUM(-amount_minor), 0) AS used, COUNT(*) AS observations
                   FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?
                     AND category_key = ?
                     AND classification = 'expense_candidate'
                     AND amount_minor < 0""",
                (start.isoformat(), end_date.isoformat(), category_key),
            ).fetchone()
        return int(row["used"]), int(row["observations"])

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
        start = date.fromisoformat(f"{month}-01")
        if end_date is None:
            end_date = date(
                start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1
            )
        with self.session() as connection:
            row = connection.execute(
                """SELECT
                     COALESCE(SUM(CASE WHEN classification = 'expense_candidate'
                       AND amount_minor < 0 THEN -amount_minor ELSE 0 END), 0) AS expenses,
                     COALESCE(SUM(CASE WHEN classification = 'income_candidate'
                       AND amount_minor > 0 THEN amount_minor ELSE 0 END), 0) AS income,
                     COUNT(*) AS observations
                   FROM transactions
                   WHERE booking_date >= ? AND booking_date < ?""",
                (start.isoformat(), end_date.isoformat()),
            ).fetchone()
        return int(row["expenses"]), int(row["income"]), int(row["observations"])

    def recurring_candidates(
        self, *, minimum_observations: int = 3, tolerance_minor: int = 100
    ) -> tuple[RecurringCandidate, ...]:
        self.initialize()
        self.ensure_write_capacity()
        with self.session() as connection:
            rows = connection.execute(
                """SELECT merchant_candidate, booking_date, -amount_minor AS amount_minor
                   FROM transactions
                   WHERE classification = 'expense_candidate'
                     AND amount_minor < 0
                     AND merchant_candidate NOT LIKE '%unclear%'
                   ORDER BY merchant_candidate, booking_date"""
            ).fetchall()
        groups: dict[str, list[tuple[date, int]]] = {}
        for row in rows:
            groups.setdefault(row["merchant_candidate"], []).append(
                (date.fromisoformat(row["booking_date"]), int(row["amount_minor"]))
            )
        candidates: list[RecurringCandidate] = []
        for merchant, observations in groups.items():
            if len(observations) < minimum_observations:
                continue
            amounts = [amount for _, amount in observations]
            if max(amounts) - min(amounts) > tolerance_minor:
                continue
            intervals = [
                (current[0] - previous[0]).days
                for previous, current in zip(observations, observations[1:], strict=False)
            ]
            average_interval = round(sum(intervals) / len(intervals))
            interval_spread = max(intervals) - min(intervals)
            confidence = "high" if len(observations) >= 3 and interval_spread <= 7 else "medium"
            regularity = "stable" if interval_spread <= 7 else "irregular"
            with self.session() as decision_connection:
                decision = decision_connection.execute(
                    "SELECT decision FROM recurring_decisions WHERE merchant = ?",
                    (merchant,),
                ).fetchone()
            if decision is not None and decision["decision"] == "dismissed":
                continue
            candidates.append(
                RecurringCandidate(
                    merchant=merchant,
                    observations=len(observations),
                    average_amount_minor=round(sum(amounts) / len(amounts)),
                    first_date=observations[0][0],
                    last_date=observations[-1][0],
                    average_interval_days=average_interval,
                    confidence=confidence,
                    confirmed=decision is not None and decision["decision"] == "confirmed",
                    regularity=regularity,
                )
            )
        return tuple(sorted(candidates, key=lambda candidate: candidate.merchant))

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
            used = connection.execute(
                """SELECT COALESCE(SUM(-amount_minor), 0)
                   FROM transactions
                   WHERE substr(booking_date, 1, 7) = ?
                     AND category_key = ?
                     AND classification = 'expense_candidate'
                     AND amount_minor < 0""",
                (month, category_key),
            ).fetchone()[0]
            threshold = preference["threshold_percent"]
            if (
                int(budget["limit_minor"]) == 0
                or int(used) * 100 < int(budget["limit_minor"]) * threshold
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

    def health_status(self) -> dict[str, int | bool]:
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
