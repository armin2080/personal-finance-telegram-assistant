"""Conservative, deterministic transaction classification.

The rules are deliberately explainable. A flow type (expense, income, transfer,
refund, reversal, fee, cash, savings) and a spending category are separate.
Token-aware matching prevents ordinary words such as ``coffee`` from matching a
bank-fee marker, and consumer context always outranks a stray fee fragment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from personal_finance_assistant.categories import CONSUMER_CATEGORIES
from personal_finance_assistant.domain import (
    ClassificationResolution,
    ParsedTransaction,
)

RULE_VERSION = "deterministic-v2"

_SALARY_MARKERS = ("lohn", "gehalt", "salary", "payroll")
_REFUND_MARKERS = (
    "refund",
    "rückerstattung",
    "rueckerstattung",
    "retoure",
    "erstattung",
    "credit note",
)
_REVERSAL_MARKERS = (
    "storno",
    "rückbuchung",
    "rueckbuchung",
    "reversal",
    "chargeback",
)
_CASH_MARKERS = ("bargeld", "geldautomat", "cash withdrawal", "atm", "abhebung")
_SAVINGS_MARKERS = (
    "sparplan",
    "tagesgeld",
    "festgeld",
    "depot",
    "investment",
    "savings plan",
    "etf",
    "aktien",
)
_TRANSFER_MARKERS = (
    "ueberweisung",
    "überweisung",
    "echtzeit-überweisung",
    "echtzeitueberweisung",
    "online-ueberweisung",
    "onlineueberweisung",
    "dauerauftrag",
)
_OWN_ACCOUNT_MARKERS = (
    "own-account",
    "own account",
    "eigenes konto",
    "eigene konten",
    "kontoübertrag",
    "kontouebertrag",
    "konto uebertrag",
    "transfer between",
    "savings account",
    "current account",
    "übertrag auf",
    "uebertrag auf",
)
_FEE_COMPOUNDS = (
    "entgeltabschluss",
    "kontofuehrungsgebuehr",
    "kontoführungsgebühr",
    "gebuehrenabrechnung",
    "gebührenabrechnung",
    "abschlussentgelt",
    "kartenentgelt",
    "kartengebuehr",
    "kartengebühr",
    "fremdwaehrungsgebuehr",
    "fremdwährungsgebühr",
    "auslandseinsatzentgelt",
    "dispoentgelt",
    "serviceentgelt",
    "kontogebuehr",
    "kontogebühr",
)
_FEE_TOKENS = (
    "fee",
    "fees",
    "gebühr",
    "gebuehr",
    "gebühren",
    "gebuehren",
    "entgelt",
    "provision",
    "service charge",
    "annual fee",
    "card fee",
    "foreign currency fee",
    "monthly fee",
)

# Ordered merchant patterns. The first match wins, so specific food types are
# checked before broader restaurant and shopping terms.
_MERCHANT_RULES: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("food.coffee", 0.9, ("coffee", "kaffee", "espresso", "starbucks")),
    (
        "food.groceries",
        0.9,
        (
            "supermarkt",
            "supermarket",
            "rewe",
            "edeka",
            "aldi",
            "lidl",
            "kaufland",
            "penny",
            "netto",
            "grocery",
            "lebensmittel",
            "dm drogerie",
            "rossmann",
        ),
    ),
    ("food.delivery", 0.9, ("lieferando", "delivery", "lieferdienst")),
    (
        "food.restaurants",
        0.9,
        (
            "restaurant",
            "bistro",
            "pizzeria",
            "imbiss",
            "mcdonald",
            "burger king",
            "kantine",
            "gastronomie",
            "cafe",
            "café",
        ),
    ),
    (
        "transport.fuel",
        0.9,
        ("tankstelle", "fuel", "aral", "shell", "esso", "jet", "benzin", "diesel"),
    ),
    (
        "transport.public_transit",
        0.9,
        (
            "transit",
            "public transport",
            "bvg",
            "hvv",
            "deutsche bahn",
            "db bahn",
            "öpnv",
            "oepnv",
        ),
    ),
    ("transport.taxi", 0.9, ("taxi", "uber", "bolt ride")),
    (
        "shopping.electronics",
        0.9,
        ("electronics", "elektronik", "media markt", "saturn"),
    ),
    ("shopping.online", 0.9, ("online shop", "amazon", "ebay", "zalando", "otto")),
    ("shopping.clothing", 0.9, ("clothing", "modehaus", "h&m", "zara")),
    (
        "subscriptions.digital",
        0.9,
        (
            "streaming",
            "netflix",
            "spotify",
            "disney",
            "cloud storage",
            "software",
            "digital subscription",
        ),
    ),
    ("health.pharmacy", 0.9, ("apotheke", "pharmacy")),
    ("health.medical", 0.9, ("arzt", "medical", "clinic", "zahnarzt", "dental")),
    ("health.fitness", 0.9, ("gym", "fitness", "fitnessstudio")),
    (
        "housing.rent",
        0.9,
        ("rent", "miete", "hausverwaltung", "wohnung", "vermieter"),
    ),
    (
        "housing.utilities",
        0.9,
        (
            "utilities",
            "stadtwerke",
            "strom",
            "energie",
            "gas",
            "wasser",
            "internet",
            "telekom",
            "vodafone",
        ),
    ),
    ("insurance", 0.9, ("insurance", "versicherung")),
    ("leisure", 0.9, ("cinema", "kino", "theater", "freizeit", "leisure")),
    ("travel", 0.9, ("travel", "hotel", "flight", "airline", "reise", "urlaub")),
    ("education", 0.9, ("education", "school", "university", "kurs", "schule", "studium")),
    ("personal_care", 0.9, ("friseur", "salon", "personal care")),
    ("gifts_donations", 0.9, ("gift", "donation", "spende", "geschenk")),
)

# Weaker merchant evidence stays reviewable and never drives a high-confidence
# precision claim.
_WEAK_MERCHANT_RULES: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("transport.other", 0.6, ("mobility", "mobilitaet", "mobilität")),
    ("shopping.online", 0.75, (".shop", ".store", ".online")),
)

_DESCRIPTION_RULES: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("food.coffee", 0.75, ("coffee", "kaffee", "espresso")),
    ("food.groceries", 0.75, ("grocery", "groceries", "supermarket", "lebensmittel")),
    ("food.restaurants", 0.7, ("restaurant meal", "dining", "restaurant", "bistro", "cafe")),
    ("food.delivery", 0.75, ("food delivery", "takeaway", "lieferdienst")),
    ("transport.fuel", 0.75, ("fuel purchase", "fuel", "petrol", "tanken", "benzin")),
    (
        "transport.public_transit",
        0.75,
        ("public transport", "transit pass", "bus ticket", "train ticket", "öpnv", "oepnv"),
    ),
    ("health.pharmacy", 0.75, ("pharmacy purchase", "pharmacy", "apotheke")),
    ("health.fitness", 0.75, ("gym membership", "fitness")),
    ("housing.rent", 0.8, ("monthly housing payment", "rent payment", "miete")),
    ("housing.utilities", 0.8, ("monthly utilities", "utilities", "strom", "gas", "wasser")),
    ("insurance", 0.8, ("insurance", "versicherung")),
    (
        "subscriptions.digital",
        0.75,
        ("cloud storage monthly plan", "monthly plan", "subscription", "streaming", "abo"),
    ),
    ("shopping.online", 0.75, ("online purchase", "online shopping")),
    ("shopping.electronics", 0.75, ("electronics purchase", "electronics")),
    ("leisure", 0.75, ("cinema", "kino", "theater")),
    ("travel", 0.75, ("flight", "hotel", "travel", "urlaub")),
    ("education", 0.75, ("education", "school", "university", "kurs")),
    ("personal_care", 0.75, ("personal care", "friseur", "salon")),
    ("gifts_donations", 0.75, ("gift", "donation", "spende", "geschenk")),
)


@dataclass(frozen=True, slots=True)
class CategoryDecision:
    category_key: str
    confidence: float
    evidence: str
    source: str = "deterministic"


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


def _ascii_fold(value: str) -> str:
    return (
        value.casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )


def _forms(value: str) -> tuple[str, str]:
    lowered = _fold(value)
    return lowered, _ascii_fold(lowered)


def _phrase_present(text: str, phrase: str) -> bool:
    """Match a phrase on token boundaries; multi-word patterns use a phrase."""

    phrase = _fold(phrase)
    if not phrase:
        return False
    if " " in phrase or "-" in phrase:
        return phrase in text
    return re.search(rf"(?<![\w]){re.escape(phrase)}(?![\w])", text) is not None


def _has_phrase(text: str, markers: tuple[str, ...]) -> bool:
    lowered, ascii_lowered = _forms(text)
    return any(
        _phrase_present(lowered, marker) or _phrase_present(ascii_lowered, marker)
        for marker in markers
    )


def _has_fee_evidence(text: str) -> bool:
    lowered, ascii_lowered = _forms(text)
    if any(compound in lowered or compound in ascii_lowered for compound in _FEE_COMPOUNDS):
        return True
    return any(
        _phrase_present(lowered, token) or _phrase_present(ascii_lowered, token)
        for token in _FEE_TOKENS
    )


def _match_rules(
    text: str, rules: tuple[tuple[str, float, tuple[str, ...]], ...]
) -> tuple[str, float, str] | None:
    lowered, _ = _forms(text)
    for category, confidence, markers in rules:
        for marker in markers:
            if _phrase_present(lowered, marker):
                return category, confidence, f"pattern:{marker}"
    return None


def _merchant_category(merchant: str) -> CategoryDecision | None:
    if not merchant:
        return None
    match = _match_rules(merchant, _MERCHANT_RULES)
    if match is not None:
        category, confidence, evidence = match
        return CategoryDecision(category, confidence, f"merchant {evidence}")
    match = _match_rules(merchant, _WEAK_MERCHANT_RULES)
    if match is not None:
        category, confidence, evidence = match
        return CategoryDecision(category, confidence, f"merchant {evidence}")
    folded = merchant.casefold()
    if folded.endswith((".shop", ".store", ".online")):
        return CategoryDecision("shopping.online", 0.75, "merchant pattern:online domain")
    return None


def _description_category(text: str) -> CategoryDecision | None:
    match = _match_rules(text, _DESCRIPTION_RULES)
    if match is not None:
        category, confidence, evidence = match
        return CategoryDecision(category, confidence, f"description {evidence}")
    return None


def _is_own_account(text: str) -> bool:
    return _has_phrase(text, _OWN_ACCOUNT_MARKERS)


def _is_transfer_booking(booking_text: str) -> bool:
    return _has_phrase(booking_text, _TRANSFER_MARKERS)


def _fee_context_is_consumer(context: CategoryDecision | None) -> bool:
    return context is not None and context.category_key in CONSUMER_CATEGORIES


def _context_category(
    transaction: ParsedTransaction,
    merchant: str,
    merchant_default_category: str | None,
) -> CategoryDecision | None:
    if merchant_default_category:
        return CategoryDecision(
            merchant_default_category,
            0.95,
            "merchant alias default category",
            source="alias",
        )
    merchant_decision = _merchant_category(merchant)
    if merchant_decision is not None:
        return merchant_decision
    description = " ".join((transaction.purpose, transaction.booking_text))
    return _description_category(description)


def _resolution(
    *,
    classification: str,
    classification_confidence: float,
    category: CategoryDecision,
    classification_source: str = "deterministic",
    evidence: str = "",
) -> ClassificationResolution:
    return ClassificationResolution(
        classification=classification,  # type: ignore[arg-type]
        classification_source=classification_source,  # type: ignore[arg-type]
        classification_confidence=classification_confidence,
        category_key=category.category_key,
        category_source=category.source,  # type: ignore[arg-type]
        category_confidence=category.confidence,
        rule_version=RULE_VERSION,
        evidence=evidence or category.evidence,
    )


def classify_transaction(
    transaction: ParsedTransaction,
    *,
    merchant: str | None = None,
    merchant_default_category: str | None = None,
) -> ClassificationResolution:
    """Classify direction and category conservatively.

    ``merchant`` is the resolved merchant label when storage has one. The
    optional ``merchant_default_category`` comes from an explicit user alias and
    therefore outranks built-in deterministic patterns.
    """

    merchant_label = merchant or transaction.merchant_candidate
    text = " ".join(
        (transaction.booking_text, transaction.purpose, transaction.counterparty, merchant_label)
    )
    booking_text = transaction.booking_text
    context = _context_category(transaction, merchant_label, merchant_default_category)

    if _has_phrase(text, _REVERSAL_MARKERS):
        return _resolution(
            classification="reversal_candidate",
            classification_confidence=0.9,
            category=CategoryDecision("uncategorized", 0.0, "reversal needs review"),
            evidence="reversal marker",
        )

    if transaction.amount_minor > 0 and _has_phrase(text, _REFUND_MARKERS):
        return _resolution(
            classification="refund_candidate",
            classification_confidence=0.9,
            category=CategoryDecision("income.refund", 0.9, "refund marker"),
            evidence="refund marker",
        )

    if _has_phrase(text, _CASH_MARKERS):
        return _resolution(
            classification="cash_withdrawal_candidate",
            classification_confidence=0.9,
            category=CategoryDecision("cash.withdrawal", 0.9, "cash marker"),
            evidence="cash marker",
        )

    if transaction.amount_minor > 0 and _has_phrase(booking_text, _SALARY_MARKERS):
        return _resolution(
            classification="income_candidate",
            classification_confidence=0.98,
            category=CategoryDecision("income.salary", 0.98, "payroll booking text"),
            evidence="payroll booking text",
        )

    # Fee evidence must survive consumer context. "Coffee and pastry" never
    # matches the token "fee"; a restaurant memo mentioning a service charge is
    # still a restaurant payment, not a bank charge.
    if _has_fee_evidence(text) and not _fee_context_is_consumer(context):
        return _resolution(
            classification="fee_candidate",
            classification_confidence=0.95,
            category=CategoryDecision("financial.fees", 0.95, "bank fee evidence"),
            evidence="bank fee marker",
        )

    # A transfer to a known merchant category is ordinary spending or income.
    # Only own-account movements and unresolved transfers are held outside
    # consumption totals.
    if (_is_own_account(text) or _is_transfer_booking(booking_text)) and (
        _is_own_account(text) or context is None
    ):
        return _resolution(
            classification="transfer_candidate",
            classification_confidence=0.9,
            category=CategoryDecision("transfers", 0.9, "own-account transfer"),
            evidence="transfer marker",
        )

    if _has_phrase(text, _SAVINGS_MARKERS):
        return _resolution(
            classification="savings_candidate",
            classification_confidence=0.85,
            category=CategoryDecision("savings.investments", 0.85, "savings marker"),
            evidence="savings marker",
        )

    if transaction.amount_minor < 0:
        category = context or CategoryDecision(
            "uncategorized", 0.0, "no reliable merchant or descriptor evidence"
        )
        return _resolution(
            classification="expense_candidate",
            classification_confidence=0.8,
            category=category,
        )

    if transaction.amount_minor > 0:
        return _resolution(
            classification="income_candidate",
            classification_confidence=0.6,
            category=CategoryDecision(
                "income.other", 0.5, "generic credit without payroll evidence"
            ),
            evidence="generic credit",
        )

    return _resolution(
        classification="unknown",
        classification_confidence=1.0,
        category=CategoryDecision("uncategorized", 0.0, "zero amount"),
    )
