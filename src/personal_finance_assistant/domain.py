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
class ImportRowPreview:
    """One parsed row with deterministic suggestions for the import review UI."""

    row_number: int
    booking_date: date
    value_date: date | None
    booking_text: str
    purpose: str
    counterparty: str
    amount_minor: int
    currency: str
    payment_channel: str
    merchant: str
    merchant_source: str
    merchant_confidence: float
    classification: str
    classification_source: str
    classification_confidence: float
    category_key: str
    category_source: str
    category_confidence: float
    review_required: bool
    duplicate_reason: str | None
    evidence: str
    merchant_learnable: bool = True
    descriptor_pattern: str = ""


@dataclass(frozen=True, slots=True)
class ImportRowOverride:
    """Explicit user edits applied to one row during import commit."""

    merchant: str | None = None
    classification: str | None = None
    category_key: str | None = None
    note: str | None = None
    remember: Literal["merchant", "descriptor"] | None = None


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
    status: str = "completed"


@dataclass(frozen=True, slots=True)
class MerchantEntityInfo:
    entity_id: str
    canonical_name: str
    default_category_key: str | None
    aliases: tuple[str, ...]
    transaction_count: int
    total_minor: int


@dataclass(frozen=True, slots=True)
class ClassificationRuleInfo:
    rule_id: str
    pattern: str
    classification: str
    category_key: str
    confidence: float
    priority: int
    match_type: str
    merchant_pattern: str | None
    descriptor_pattern: str | None
    payment_channel: str | None
    direction: str
    payment_type: str | None
    enabled: bool
    rule_version: str
    created_at: str
    updated_at: str
    label: str = ""


@dataclass(frozen=True, slots=True)
class TransactionSplit:
    split_id: str
    transaction_id: str
    amount_minor: int
    category_key: str
    note: str


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    """A deterministic answer with the period and calculation context."""

    text: str
    intent: str
    start_date: date
    end_date: date
    metric: str
    category_keys: tuple[str, ...] = ()
    merchant: str | None = None
    confidence: str = "high"
    uncertainty: str | None = None


MerchantSource = Literal["unreviewed", "deterministic", "alias", "user"]


@dataclass(frozen=True, slots=True)
class MerchantResolution:
    """A merchant label with explicit provenance and confidence."""

    merchant: str
    source: MerchantSource
    confidence: float
    default_category_key: str | None = None


ClassificationSource = Literal["deterministic", "user", "unreviewed", "alias"]


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
    evidence: str = ""
    rule_id: str | None = None


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
    fees_minor: int = 0
    cash_withdrawals_minor: int = 0
    savings_minor: int = 0
    reversals_minor: int = 0

    @property
    def categorized_expenses_minor(self) -> int:
        return self.expenses_minor - self.uncategorized_expenses_minor


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
    uncategorized_expenses_minor: int = 0
    categorized_expenses_minor: int = 0
    reversals_minor: int = 0
    cash_withdrawals_minor: int = 0
    savings_minor: int = 0


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    """User-visible transaction data for the local dashboard."""

    transaction_id: str
    booking_date: date
    amount_minor: int
    currency: str
    merchant: str
    counterparty: str
    description: str
    classification: Classification
    category_key: str
    review_status: ReviewStatus
    payment_channel: str
    merchant_source: MerchantSource = "unreviewed"
    merchant_confidence: float = 0.0
    classification_source: ClassificationSource = "unreviewed"
    classification_confidence: float = 0.0
    category_source: ClassificationSource = "unreviewed"
    category_confidence: float = 0.0
    evidence: str = ""
    note: str = ""
    has_split: bool = False
    split_categories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Insight:
    """Evidence-backed, deterministic insight for a selected period."""

    insight_id: str
    title: str
    explanation: str
    relevance: str
    start_date: date
    end_date: date
    confidence: str
    supporting_transaction_ids: tuple[str, ...]
    next_action: str | None


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
    fee_minor: int = 0
    cash_minor: int = 0
    savings_minor: int = 0
    reversal_minor: int = 0
    transfer_in_minor: int = 0
    transfer_out_minor: int = 0
    unexplained_debit_minor: int = 0
    unexplained_credit_minor: int = 0


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
class MerchantTotal:
    merchant: str
    amount_minor: int
    transaction_count: int


@dataclass(frozen=True, slots=True)
class WeeklyTrend:
    week_start: date
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
    period_start: date | None = None
    period_end: date | None = None
    elapsed_days: int = 0
    total_days: int = 0
    percentage_used: int = 0
    projected_minor: int | None = None
    uncategorized_expenses_minor: int = 0
    complete: bool = True
    status: str = "within_limit"
    alert_threshold_percent: int | None = None


@dataclass(frozen=True, slots=True)
class BudgetMonthSummary:
    month: str
    total_expenses_minor: int
    categorized_expenses_minor: int
    uncategorized_expenses_minor: int
    budgets: tuple[BudgetStatus, ...]
    complete: bool
    disclosure: str


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
    latest_amount_minor: int | None = None
    previous_amount_minor: int | None = None
    status: str = "possible"
    supporting_transaction_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecurringPriceChange:
    merchant: str
    old_amount_minor: int
    new_amount_minor: int
    changed_on: date
    observations_before: int
    observations_after: int
    confidence: str
    supporting_transaction_ids: tuple[str, ...]


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
    status: str = "completed"
