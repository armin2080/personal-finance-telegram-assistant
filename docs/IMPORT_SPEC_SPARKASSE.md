# Sparkasse import specification — observed CSV-CAMT V8-style export

## Source classification

The sample supplied for project design was a file with a `...camt52v8.CSV`-style name. Its actual body was CSV, not XML. It used:

- UTF-8-compatible text;
- semicolon (`;`) field delimiter;
- double-quoted fields;
- 17 German-language headers;
- dates in `DD.MM.YY` format;
- EUR amounts using a decimal comma;
- booked transaction status (`Umsatz gebucht`).

The adapter ID is `sparkasse_csv_camt_v8`. Do not label it as a generic ISO 20022 CAMT XML parser. A separate CAMT XML adapter may be added later after a real XML sample and a separate specification are available.

## Observed headers

| Header | Required | Handling |
|---|---:|---|
| `Auftragskonto` | No | Ignore; never persist account identifier. |
| `Buchungstag` | Yes | Parse as booking date. |
| `Valutadatum` | No | Parse as value date if present. |
| `Buchungstext` | Yes | Store normalised transaction type/text. |
| `Verwendungszweck` | No | Store scrubbed purpose text; never log raw value. |
| `Glaeubiger ID` | No | Ignore; do not persist. |
| `Mandatsreferenz` | No | Ignore in MVP; it identifies a mandate, not a unique booking. |
| `Kundenreferenz (End-to-End)` | No | Preferred transient dedupe input; never persist raw. |
| `Sammlerreferenz` | No | Ignore in MVP. |
| `Lastschrift Ursprungsbetrag` | No | Ignore until a documented use case exists. |
| `Auslagenersatz Ruecklastschrift` | No | Ignore until a documented use case exists. |
| `Beguenstigter/Zahlungspflichtiger` | No | Store scrubbed counterparty label. |
| `Kontonummer/IBAN` | No | Ignore; never persist. |
| `BIC (SWIFT-Code)` | No | Ignore; never persist. |
| `Betrag` | Yes | Parse locale-aware decimal into integer EUR cents. |
| `Waehrung` | Yes | MVP accepts EUR only. Reject other currencies explicitly. |
| `Info` | No | Store a short normalised status label. |

The parser validates the four required headers: `Buchungstag`, `Buchungstext`, `Betrag`, and `Waehrung`. Optional columns can be blank. If a regional Sparkasse export changes the header spelling or structure, add an explicit alias with tests; do not silently guess.

## Transaction patterns observed

The inspected export demonstrated transaction descriptions for several common booking types, including:

- follow-up direct debits (`FOLGELASTSCHRIFT`);
- Android digital-card transactions (`DIGITALE KARTE (ANDROID)`);
- card transactions (`KARTENZAHLUNG`);
- transfer/credit types, including online and instant transfers;
- a payroll/salary credit (`LOHN GEHALT`).

This description contains aggregate format observations only. The real CSV is not included in this repository.

## Merchant extraction rules

1. Start with `Beguenstigter/Zahlungspflichtiger` as the counterparty candidate.
2. If the counterparty is PayPal, inspect the purpose for explicit phrases such as `Ihr Einkauf bei`, `Einkauf bei`, `purchase at`, `payment to`, or `Zahlung an`.
3. Some PayPal descriptions put a reference before a slash and the merchant after it. A reference-only token is not a merchant.
4. For card-payment rows, descriptors may contain a web domain followed by terminal/location data. Extract only the domain candidate where unambiguous.
5. Otherwise preserve the counterparty label as a candidate.
6. If evidence is insufficient, return an explicit unclear label. Never invent the underlying shop.
7. Merchant resolution and category assignment are separate operations.

## Dates and money

- Parse `DD.MM.YY`, `DD.MM.YYYY`, and ISO `YYYY-MM-DD` dates.
- Keep booking date and value date separately.
- Never use float. Parse with `Decimal` and store integer cents.
- Accept German `1.234,56`, plain German `17,04`, and unambiguous decimal-dot forms such as `17.04`.
- Reject malformed or non-EUR rows with row number and a safe error message.
- The import is atomic: if one required row is invalid, do not partially import the file.

## Privacy and retention

- Never persist `Auftragskonto`, `Kontonummer/IBAN`, `BIC`, creditor ID, mandate reference, or batch reference.
- Transient source references may be used to calculate a digest for duplicate detection; do not persist the raw reference.
- Scrub obvious IBAN and card-number patterns from memo/counterparty text before persistence.
- Do not keep the original CSV in the app data directory after import unless the owner separately chooses a secure archival policy.
- Do not upload CSV exports to Telegram in MVP.

## Required tests before changing this adapter

- UTF-8 with/without BOM and Windows-1252 fallback;
- quoted semicolon and quoted newline handling;
- date parsing and invalid dates;
- German decimal comma, thousands separator, decimal dot, negative and positive amount;
- unsupported currency;
- missing/renamed header;
- blank optional fields;
- PayPal merchant extraction and unresolved PayPal case;
- card descriptor merchant extraction;
- reference-backed duplicates and content-only duplicate warning;
- proof that IBAN/BIC/mandate/creditor IDs are not persisted;
- atomic failure when a row is invalid.
