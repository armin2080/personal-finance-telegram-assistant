"""Conservative merchant-name extraction from Sparkasse descriptions.

This module extracts candidate names only. It does not decide spending categories.
Unknown or ambiguous cases remain visible for user review.
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


def _clean_candidate(value: str) -> str:
    value = value.strip(" \t\r\n./|;-:")
    value = re.split(r"\s{2,}|\s(?:DEBITK\.|VISA|MASTERCARD)\b", value, maxsplit=1, flags=re.I)[0]
    value = re.sub(r"\s+", " ", value).strip()
    return value[:120]


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
            if candidate:
                return candidate
        # Some PayPal exports place the merchant after the first slash without
        # a natural-language phrase. Do not promote a reference-only token.
        parts = [part.strip() for part in memo.split("/") if part.strip()]
        for part in parts:
            if not re.fullmatch(r"[A-Z0-9_-]{7,}", part, flags=re.I):
                candidate = _clean_candidate(part)
                if candidate:
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
        return _clean_candidate(first_segment) or "Merchant unclear"

    return party or "Counterparty unclear"
