from personal_finance_assistant.categories import CATEGORY_REGISTRY


def test_category_registry_contains_documented_flow_categories() -> None:
    assert CATEGORY_REGISTRY["food.groceries"] == "Groceries"
    assert CATEGORY_REGISTRY["income.refund"] == "Refund"
    assert CATEGORY_REGISTRY["transfers"] == "Transfers"
    assert CATEGORY_REGISTRY["uncategorized"] == "Uncategorised"
