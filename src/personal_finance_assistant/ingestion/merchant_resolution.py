"""Conservative merchant-name extraction and safe normalisation.

This module extracts candidate names only. It does not decide spending
categories. Unknown or ambiguous cases remain visible for user review. Display
normalisation never merges distinct businesses: only explicit alias rows and
the exact built-in canonical patterns resolve two descriptors to one name.
"""

from __future__ import annotations

import re

_PAYPAL_PHRASES = re.compile(
    (
        r"(?:ihr\s+einkauf\s+bei|einkauf\s+bei|purchase\s+at|payment\s+to|"
        r"zahlung\s+an|merchant\s*:)\s*(.+)"
    ),
    re.IGNORECASE,
)
_DOMAIN = re.compile(r"(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9.-]*\.[a-z]{2,})", re.IGNORECASE)
_TERMINAL_SUFFIX = re.compile(r"\s+\d{2,4}$")
_LEGAL_SUFFIXES = {
    "gmbh": "GmbH",
    "mbh": "mbH",
    "ag": "AG",
    "se": "SE",
    "kg": "KG",
    "ohg": "OHG",
    "gbr": "GbR",
    "ug": "UG",
    "bv": "BV",
    "nv": "NV",
    "ltd": "Ltd",
    "plc": "PLC",
    "e.v.": "e.V.",
    "ev": "e.V.",
    "e.v": "e.V.",
}
_GENERIC_PAYPAL_MERCHANTS = frozenset(
    {
        "online shop",
        "shop",
        "merchant",
        "unknown",
        "unclear",
        "merchant unclear",
        "merchant omitted",
    }
)

# Canonical identities for descriptors that differ only by terminal suffix,
# hyphenation or casing. This is deliberately a small allow-list; it is not a
# fuzzy matcher that could merge unrelated businesses.
_CANONICAL_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("supermarkt", "mitte"), "Supermarkt Mitte"),
    (("bistro", "alex"), "Bistro Alex"),
    (("restaurant", "am", "markt"), "Restaurant am Markt"),
    (("coffee", "house", "nord"), "Coffee House Nord"),
)


def _clean_candidate(value: str) -> str:
    value = value.strip(" \t\r\n./|;-:")
    value = re.split(r"\s{2,}|\s(?:DEBITK\.|VISA|MASTERCARD)\b", value, maxsplit=1, flags=re.I)[0]
    value = re.sub(r"\s+", " ", value).strip()
    return value[:120]


def _titlecase_label(value: str) -> str:
    words: list[str] = []
    for word in value.split():
        folded = word.casefold()
        if folded in _LEGAL_SUFFIXES:
            words.append(_LEGAL_SUFFIXES[folded])
        elif word.isupper() and len(word) <= 3:
            words.append(word)
        else:
            words.append(word.capitalize())
    return " ".join(words)


def normalize_merchant_display(value: str) -> str:
    """Normalise a merchant label for display without changing its identity."""

    cleaned = _clean_candidate(value)
    cleaned = cleaned.replace("_", " ")
    cleaned = re.sub(r"(?<=\w)-(?=\w)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    # Terminal suffixes are card-acquirer artefacts, not part of a merchant name.
    without_terminal = _TERMINAL_SUFFIX.sub("", cleaned).strip()
    if without_terminal and re.search(r"[A-Za-zÄÖÜäöüß]", without_terminal):
        cleaned = without_terminal
    if cleaned.casefold().endswith("e.v") or cleaned.casefold().endswith("e. v"):
        cleaned = cleaned.rstrip(".") + "."
    if cleaned.isupper():
        return _titlecase_label(cleaned)
    return cleaned


def normalize_alias_key(value: str) -> str:
    """Return a stable lookup key for explicit merchant aliases."""

    folded = normalize_merchant_display(value).casefold()
    folded = re.sub(r"[^\wäöüß]+", " ", folded, flags=re.UNICODE)
    return " ".join(folded.split())


def canonical_merchant(value: str) -> str | None:
    """Return a built-in canonical identity for a known descriptor pattern."""

    tokens = tuple(normalize_alias_key(value).split())
    if not tokens:
        return None
    for required, canonical in _CANONICAL_PATTERNS:
        if tokens == required:
            return canonical
    return None


def _is_generic_paypal_candidate(value: str) -> bool:
    folded = normalize_alias_key(value)
    if not folded or folded in _GENERIC_PAYPAL_MERCHANTS:
        return True
    if any(
        marker in folded
        for marker in (
            "merchant omitted",
            "merchant unclear",
            "unknown merchant",
            "no merchant",
        )
    ):
        return True
    # A payment purpose is not a merchant name. Reject long reference-like
    # sentences rather than promoting them to an identity.
    return len(folded.split()) > 6


def extract_merchant_candidate(counterparty: str, purpose: str, booking_text: str = "") -> str:
    """Return a best-effort merchant candidate without inventing a category."""

    party = _clean_candidate(counterparty)
    memo = purpose.strip()

    if "paypal" in party.casefold():
        match = _PAYPAL_PHRASES.search(memo)
        if match:
            candidate = _clean_candidate(match.group(1))
            # Avoid treating a trailing location or a second reference segment as
            # part of the merchant label. The original memo remains available locally.
            candidate = candidate.split("/", 1)[0].strip()
            if candidate and not _is_generic_paypal_candidate(candidate):
                return candidate
        # Some PayPal exports place the merchant after the first slash without
        # a natural-language phrase. Do not promote a reference-only token.
        parts = [part.strip() for part in memo.split("/") if part.strip()]
        for part in parts:
            if not re.fullmatch(r"[A-Z0-9_-]{7,}", part, flags=re.I):
                candidate = _clean_candidate(part)
                if candidate and not _is_generic_paypal_candidate(candidate):
                    return candidate
        # A masked PayPal descriptor such as "PAYPAL *ONLINE SHOP" does not
        # identify a business. Keep it explicitly unresolved.
        star_suffix = party.split("*", 1)[1].strip() if "*" in party else ""
        if star_suffix and normalize_alias_key(star_suffix) not in _GENERIC_PAYPAL_MERCHANTS:
            candidate = normalize_merchant_display(star_suffix)
            if candidate and not _is_generic_paypal_candidate(candidate):
                return candidate
        return "PayPal (merchant unclear)"

    is_card = booking_text.upper().startswith(("KARTENZAHLUNG", "DIGITALE KARTE"))
    if is_card:
        abbreviated = re.match(r"^WWW\.([A-Z0-9-]+)\.\.", party, re.I)
        if abbreviated:
            return abbreviated.group(1).lower()

    domain_match = _DOMAIN.search(party)
    if domain_match:
        return domain_match.group(1).lower()

    # Card descriptors often contain merchant / terminal / city segments.
    if is_card:
        first_segment = party.split("/", 1)[0]
        return normalize_merchant_display(first_segment) or "Merchant unclear"

    return normalize_merchant_display(party) or "Counterparty unclear"
