# Categorisation and merchant rules

The classifier is deterministic, local and conservative. It never calls an
external model. Every label stores its source, confidence, rule version and the
evidence that matched.

## Precedence

1. Transaction-level user correction.
2. Explicit user rule (structured conditions, highest priority first).
3. Confirmed merchant alias with optional default category.
4. Built-in deterministic merchant pattern (strong evidence, confidence 0.9).
5. Conservative purpose/booking-text pattern (confidence 0.7–0.8).
6. Weak merchant or domain evidence (confidence 0.6–0.75, always reviewable).
7. `uncategorized`, `needs_review`.

A lower-priority rule can never overwrite a row whose classification or category
source is `user`.

## Fee recognition (DEF-01)

Fee recognition is token-aware and context-aware.

- Single-word markers such as `fee`, `gebühr`, `entgelt` and `provision` match on
  token boundaries. `coffee` therefore cannot match `fee`.
- German compounds such as `ENTGELTABSCHLUSS`, `Kontoführungsgebühr`,
  `Kartengebühr`, `Fremdwährungsgebühr` and `Auslandseinsatzentgelt` are matched
  as compounds.
- Consumer context wins. A restaurant, café, coffee shop, supermarket or other
  consumption merchant with a memo containing a service-charge fragment is not
  reclassified as a bank fee.
- Known bank-fee patterns and explicit fee descriptions are classified as
  `fee_candidate` / `financial.fees`.

Regression cases cover coffee, coffee shop, café coffee, card and digital-wallet
coffee purchases, service fees, account-management fees, German bank charges,
card fees, foreign-currency fees and restaurant memos mentioning a service fee.

## Merchant normalisation

- Display normalisation trims card terminal suffixes (`... 03`), converts safe
  hyphenation (`BISTRO-ALEX` → `Bistro Alex`), title-cases all-caps descriptors
  and preserves legal suffixes (`GmbH`, `AG`, `e.V.`).
- Built-in canonical patterns are an explicit allow-list and require an exact
  normalised token set. `Bistro Alex` and `BISTRO-ALEX` merge; `Bistro Alex
  Dortmund` does not, because similarity alone must never merge businesses.
- User aliases are stored as exact normalised keys. They outrank built-in
  patterns.
- PayPal pass-through extracts the merchant named in the purpose text. A masked
  descriptor with no merchant evidence remains `PayPal (merchant unclear)`.

## Consumer category baseline

| Category | Representative evidence |
|---|---|
| `housing.rent` | rent, miete, hausverwaltung, vermieter |
| `housing.utilities` | utilities, stadtwerke, strom, gas, wasser, internet, telecom |
| `food.groceries` | supermarkt, rewe, edeka, aldi, lidl, kaufland, grocery, lebensmittel |
| `food.restaurants` | restaurant, bistro, pizzeria, imbiss, gastronomie, cafe |
| `food.coffee` | coffee, kaffee, espresso |
| `food.delivery` | lieferando, delivery, lieferdienst |
| `transport.public_transit` | transit, public transport, bahn, bvg, hvv, öpnv |
| `transport.fuel` | tankstelle, fuel, aral, shell, esso, benzin, diesel |
| `transport.taxi` | taxi, uber, bolt ride |
| `shopping.online` | online shop, amazon, ebay, zalando, `.shop`/`.store` domains |
| `shopping.electronics` | electronics, elektronik, media markt, saturn |
| `shopping.clothing` | clothing, modehaus, h&m, zara |
| `subscriptions.digital` | streaming, netflix, spotify, cloud storage, software |
| `health.pharmacy` | apotheke, pharmacy |
| `health.medical` | arzt, medical, clinic, zahnarzt |
| `health.fitness` | gym, fitness, fitnessstudio |
| `insurance` | insurance, versicherung |
| `leisure` | cinema, kino, theater, freizeit |
| `travel` | travel, hotel, flight, airline, reise, urlaub |
| `education` | education, school, university, kurs, studium |
| `personal_care` | friseur, salon, personal care |
| `gifts_donations` | gift, donation, spende, geschenk |

Purpose-text rules are used only when merchant evidence is absent. They are
deliberately less confident than exact merchant patterns.

## Review policy

- Auto-confirmed: classification and category confidence ≥ 0.8 and a named
  category.
- Review: uncategorised, generic credits (`income.other`), reversals, weak
  merchant/domain evidence, or a classification rule that deliberately leaves
  the category uncertain.
- The independent QA fixture yields 21/182 rows for review (11.54%), with 100%
  high-confidence precision on the 161 high-confidence rows.

## User rules

A rule may combine:

- merchant pattern;
- descriptor tokens;
- exact descriptor pattern;
- payment channel;
- direction (`debit`, `credit`, `any`);
- payment type / booking text;
- priority.

A rule that contains no condition, or a single-token rule shorter than three
characters, is rejected. Rules are stored with a version and priority, and the
matching rule ID is recorded as evidence on the transaction.
