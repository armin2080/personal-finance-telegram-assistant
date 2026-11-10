from personal_finance_assistant.ingestion.merchant_resolution import extract_merchant_candidate


def test_extracts_paypal_underlying_merchant() -> None:
    result = extract_merchant_candidate(
        "PayPal Example Payments Ltd",
        "ORDER-TEST-01 / Ihr Einkauf bei Test Mobility GmbH",
        "FOLGELASTSCHRIFT",
    )
    assert result == "Test Mobility GmbH"


def test_extracts_card_merchant_domain() -> None:
    result = extract_merchant_candidate(
        "WWW.EXAMPLE.SHOP/TERMINAL-01/BERLIN/DE",
        "card payment",
        "KARTENZAHLUNG",
    )
    assert result == "example.shop"


def test_does_not_guess_paypal_merchant_without_evidence() -> None:
    result = extract_merchant_candidate(
        "PayPal Synthetic Account", "reference-only-token-12345678", "FOLGELASTSCHRIFT"
    )
    assert result == "PayPal (merchant unclear)"


def test_extracts_abbreviated_sparkasse_card_descriptor() -> None:
    result = extract_merchant_candidate(
        "WWW.TESTSTORE.. TERMINAL-XYZ/Street/COUNTRY",
        "card payment",
        "KARTENZAHLUNG",
    )
    assert result == "teststore"
