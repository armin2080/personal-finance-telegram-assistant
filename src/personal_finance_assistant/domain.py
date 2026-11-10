"""Small domain objects shared by import, storage and application layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

DedupeBasis = Literal["reference", "content"]
Classification = Literal[
    "expense_candidate",
    "income_candidate",
    "transfer_candidate",
    "refund_candidate",
    "reversal_candidate",
    "fee_candidate",
    "cash_withdrawal_candidate",
    "savings_candidate",
    "unknown",
]

ReviewStatus = Literal["needs_review", "confirmed", "dismissed"]


@dataclass(frozen=True, slots=True)
class ParsedTransaction:
    """A transaction extracted from a source file.

    Bank account identifiers, counterparty IBANs, BICs, creditor IDs and mandate
    references are deliberately not part of this model. The parser may use a
    source reference transiently to calculate a digest, but does not retain it.
    """

    booking_date: date
    value_date: date | None
    booking_text: str
    purpose: str
    counterparty: str
    merchant_candidate: str
    amount_minor: int
    currency: str
    info: str
    classification: Classification
    dedupe_key: str
    dedupe_basis: DedupeBasis
    row_number: int
    payment_channel: str = "unknown"


@dataclass(frozen=True, slots=True)
class ParseResult:
    source_format: str
    file_sha256: str
    transactions: tuple[ParsedTransaction, ...]
    encoding: str


@dataclass(frozen=True, slots=True)
class ImportBatchPreview:
    """Safe aggregate facts for reviewing an import before it is committed."""

    source_format: str
    file_sha256: str
    transaction_count: int
    first_booking_date: date
    last_booking_date: date
    currency_counts: tuple[tuple[str, int], ...]
    positive_count: int
    negative_count: int
    payment_type_counts: tuple[tuple[str, int], ...]
    reference_dedupe_count: int
    content_dedupe_count: int


DuplicateReason = Literal[
    "content_duplicate_in_file",
    "content_match_existing",
    "reference_match_existing",
]


@dataclass(frozen=True, slots=True)
class DuplicateReview:
    """Safe duplicate findings for an import review."""

    exact_file_match: bool
    reference_matches: int
    possible_duplicates: tuple[tuple[int, DuplicateReason], ...]


@dataclass(frozen=True, slots=True)
class ImportBatchInfo:
    """Safe aggregate information about a persisted import batch."""

    import_id: str
    file_sha256: str
    source_format: str
    encoding: str
    transaction_count: int
    inserted_count: int
    exact_duplicate_count: int
    possible_duplicate_count: int
    created_at: str


MerchantSource = Literal["unreviewed", "deterministic", "alias", "user"]


@dataclass(frozen=True, slots=True)
class MerchantResolution:
    """A merchant label with explicit provenance and confidence."""

    merchant: str
    source: MerchantSource
    confidence: float


ClassificationSource = Literal["deterministic", "user", "unreviewed"]


@dataclass(frozen=True, slots=True)
class ClassificationResolution:
    """A flow classification and category with auditable provenance."""

    classification: Classification
    classification_source: ClassificationSource
    classification_confidence: float
    category_key: str
    category_source: ClassificationSource
    category_confidence: float
    rule_version: str


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    category_key: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class PeriodReport:
    start_date: date
    end_date: date
    expenses_minor: int
    income_minor: int
    refunds_minor: int
    transfers_minor: int
    uncategorized_expenses_minor: int
    category_expenses: tuple[CategoryTotal, ...]
    transaction_count: int


@dataclass(frozen=True, slots=True)
class FinancialOverview:
    """Deterministic overview metrics for a selected period and baseline."""

    start_date: date
    end_date: date
    baseline_start_date: date | None
    baseline_end_date: date | None
    income_minor: int
    expenses_minor: int
    refunds_minor: int
    transfers_minor: int
    fees_minor: int
    net_cash_flow_minor: int
    savings_rate_percent: int | None
    transaction_count: int
    data_quality: str


@dataclass(frozen=True, slots=True)
class LedgerReconciliation:
    start_date: date
    end_date: date
    transaction_count: int
    debit_minor: int
    credit_minor: int
    expense_minor: int
    income_minor: int
    refund_minor: int
    transfer_minor: int
    unknown_minor: int


@dataclass(frozen=True, slots=True)
class BudgetForecast:
    month: str
    category_key: str
    as_of: date
    observed_days: int
    observations: int
    used_minor: int
    projected_minor: int | None
    limit_minor: int | None
    confidence: str
    sparse_data: bool


@dataclass(frozen=True, slots=True)
class MonthlyTrend:
    month: str
    expenses_minor: int
    income_minor: int


@dataclass(frozen=True, slots=True)
class CashFlowForecast:
    month: str
    as_of: date
    observed_days: int
    observations: int
    net_observed_minor: int
    projected_net_minor: int | None
    confidence: str
    sparse_data: bool


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    month: str
    category_key: str
    limit_minor: int
    used_minor: int
    remaining_minor: int
    exceeded: bool


@dataclass(frozen=True, slots=True)
class RecurringCandidate:
    merchant: str
    observations: int
    average_amount_minor: int
    first_date: date
    last_date: date
    average_interval_days: int
    confidence: str
    confirmed: bool = False
    regularity: str = "stable"


@dataclass(frozen=True, slots=True)
class ReviewCandidate:
    transaction_id: str
    booking_date: date
    amount_minor: int
    merchant: str
    classification: Classification
    category_key: str
    needs_merchant_review: bool
    needs_classification_review: bool


@dataclass(frozen=True, slots=True)
class ImportResult:
    import_id: str | None
    inserted: int
    exact_duplicates: int
    possible_duplicates: int
    already_imported_file: bool = False
