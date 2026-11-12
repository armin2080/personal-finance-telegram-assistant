"""Stable category keys for deterministic classification and user review."""

from __future__ import annotations

CATEGORY_REGISTRY: dict[str, str] = {
    "housing.rent": "Rent",
    "housing.utilities": "Utilities",
    "housing.internet": "Internet",
    "housing.household": "Household",
    "food.groceries": "Groceries",
    "food.restaurants": "Restaurants",
    "food.delivery": "Delivery",
    "food.coffee": "Coffee",
    "transport.public_transit": "Public transit",
    "transport.taxi": "Taxi",
    "transport.fuel": "Fuel",
    "transport.other": "Other transport",
    "shopping.online": "Online shopping",
    "shopping.clothing": "Clothing",
    "shopping.electronics": "Electronics",
    "shopping.general": "General shopping",
    "subscriptions.digital": "Digital subscriptions",
    "subscriptions.memberships": "Memberships",
    "health.pharmacy": "Pharmacy",
    "health.medical": "Medical",
    "health.fitness": "Fitness",
    "education": "Education",
    "insurance": "Insurance",
    "fees": "Fees",
    "leisure": "Leisure",
    "travel": "Travel",
    "income.salary": "Salary",
    "income.refund": "Refund",
    "income.other": "Other income",
    "transfers": "Transfers",
    "financial.fees": "Financial fees",
    "cash.withdrawal": "Cash",
    "savings.investments": "Savings and investments",
    "personal_care": "Personal care",
    "gifts_donations": "Gifts and donations",
    "uncategorized": "Uncategorised",
}

# Categories that describe ordinary consumption. A text fragment like "fee"
# inside a restaurant or coffee descriptor is not evidence of a bank charge.
CONSUMER_CATEGORIES: frozenset[str] = frozenset(
    {
        "food.groceries",
        "food.restaurants",
        "food.delivery",
        "food.coffee",
        "transport.public_transit",
        "transport.taxi",
        "transport.fuel",
        "transport.other",
        "shopping.online",
        "shopping.clothing",
        "shopping.electronics",
        "shopping.general",
        "subscriptions.digital",
        "subscriptions.memberships",
        "health.pharmacy",
        "health.medical",
        "health.fitness",
        "education",
        "insurance",
        "leisure",
        "travel",
        "personal_care",
        "gifts_donations",
        "housing.rent",
        "housing.utilities",
        "housing.internet",
        "housing.household",
    }
)

# Categories treated as committed / fixed costs for insight purposes only.
FIXED_COST_CATEGORIES: frozenset[str] = frozenset(
    {
        "housing.rent",
        "housing.utilities",
        "housing.internet",
        "insurance",
        "subscriptions.digital",
        "subscriptions.memberships",
    }
)


def category_label(key: str) -> str:
    """Return a human-readable label without exposing internal keys."""

    return CATEGORY_REGISTRY.get(key, key)
