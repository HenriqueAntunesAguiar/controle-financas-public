from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from ..agent import FinancialDataAgent
from .smoke_test import FakeMonthlyValuesReader
from ..tools import MonthlyValues, create_compare_monthly_values_tool, create_get_expense_by_id_tool, create_get_monthly_values_tool
from ..tools.compare_monthly_values.comparison import calculate_monthly_comparison


class GetMonthlyValuesToolTest(TestCase):
    def setUp(self) -> None:
        self.reader = FakeMonthlyValuesReader()

    def test_returns_totals_with_source_status_and_categories(self) -> None:
        tool = create_get_monthly_values_tool(self.reader)

        result = tool.invoke({
            "months": ["2026-08"],
            "data_kind": "projected",
        })

        month = result["months"][0]
        self.assertEqual(month["total"], "1800.00")
        self.assertEqual(month["sources"]["credit_card"], {
            "data_kind": "projected",
            "status": "projected",
            "data_found": True,
            "total": "1500.00",
            "categories": {"supermercado": "1500.00"},
        })
        self.assertEqual(month["sources"]["other_transactions"]["total"], "300.00")

    def test_unknown_data_uses_null_instead_of_zero(self) -> None:
        tool = create_get_monthly_values_tool(self.reader)

        result = tool.invoke({
            "months": ["2025-01"],
            "data_kind": "actual",
        })

        month = result["months"][0]
        self.assertIsNone(month["total"])
        self.assertIsNone(month["sources"]["credit_card"]["total"])
        self.assertEqual(
            month["sources"]["credit_card"]["status"],
            "data_unavailable",
        )


class GetExpenseByIdToolTest(TestCase):
    def test_returns_an_expense_with_its_id(self) -> None:
        class Reader:
            def get_expense_by_id(self, expense_id: int) -> dict:
                return {
                    "id": expense_id,
                    "month": "2026-07",
                    "description": "Parcela carro",
                    "amount": Decimal("12"),
                    "category_slug": "carro",
                    "category_name": "Carro",
                    "payment_method": "debito",
                    "expense_type": "actual",
                    "recurrence_mode": None,
                    "recurrence_end_month": None,
                }

        result = create_get_expense_by_id_tool(Reader()).invoke({"expense_id": 42})

        self.assertTrue(result["found"])
        self.assertEqual(result["expense_id"], 42)
        self.assertEqual(result["expense"]["id"], 42)
        self.assertEqual(result["expense"]["amount"], "12.00")
        self.assertEqual(result["expense"]["recurrence_mode"], "none")

    def test_returns_not_found_without_inventing_fields(self) -> None:
        class Reader:
            def get_expense_by_id(self, expense_id: int) -> None:
                return None

        result = create_get_expense_by_id_tool(Reader()).invoke({"expense_id": 99})

        self.assertEqual(result, {"expense_id": 99, "found": False, "expense": None})


class FinancialDataAgentAccessTest(TestCase):
    @patch("financial_data_agent.agent.get_financial_data_model")
    @patch("financial_data_agent.agent.create_agent")
    def test_exposes_the_same_instance_as_agent_and_tool(self, create_agent_mock, get_model_mock) -> None:
        get_model_mock.return_value = object()
        create_agent_mock.return_value.invoke.return_value = {"messages": []}

        component = FinancialDataAgent(FakeMonthlyValuesReader())

        tools = create_agent_mock.call_args.kwargs["tools"]
        self.assertEqual([item.name for item in tools], ["get_monthly_values", "compare_monthly_values", "get_expense_by_id"])
        self.assertIs(component.as_agent(), create_agent_mock.return_value)
        self.assertIs(component.as_tool(), component.as_tool())


class CompareMonthlyValuesToolTest(TestCase):
    def setUp(self) -> None:
        self.tool = create_compare_monthly_values_tool(
            FakeMonthlyValuesReader()
        )

    def test_compares_credit_card_without_mixing_other_transactions(self) -> None:
        result = self.tool.invoke({
            "previous_month": "2026-07",
            "current_month": "2026-08",
            "source": "credit_card",
            "data_kind": "actual_and_projected",
            "limit": 20,
        })

        self.assertTrue(result["comparison_available"])
        self.assertEqual(result["previous"]["total"], "1800.00")
        self.assertEqual(result["current"]["total"], "1500.00")
        self.assertEqual(result["difference"], "-300.00")
        self.assertEqual(
            {change["source"] for change in result["category_changes"]},
            {"credit_card"},
        )

    def test_source_and_data_kind_are_required_by_the_tool_schema(self) -> None:
        required = set(self.tool.args_schema.model_json_schema()["required"])

        self.assertIn("source", required)
        self.assertIn("data_kind", required)

    def test_all_scope_consolidates_categories_and_preserves_breakdown(self) -> None:
        result = self.tool.invoke({
            "previous_month": "2026-07",
            "current_month": "2026-08",
            "source": "all",
            "data_kind": "actual_and_projected",
            "limit": 20,
        })

        self.assertEqual(result["previous"]["total"], "2000.00")
        self.assertEqual(result["current"]["total"], "1800.00")
        self.assertEqual(
            {change["source"] for change in result["category_changes"]},
            {"all"},
        )
        supermercado = next(
            change
            for change in result["category_changes"]
            if change["category"] == "supermercado"
        )
        self.assertEqual(supermercado["previous_total"], "1200.00")
        self.assertEqual(supermercado["current_total"], "1500.00")
        self.assertEqual(supermercado["difference"], "300.00")
        self.assertEqual(
            {item["source"] for item in supermercado["source_breakdown"]},
            {"credit_card"},
        )

    def test_unavailable_period_does_not_generate_a_false_difference(self) -> None:
        result = self.tool.invoke({
            "previous_month": "2025-01",
            "current_month": "2026-08",
            "source": "credit_card",
            "data_kind": "actual",
        })

        self.assertFalse(result["comparison_available"])
        self.assertIsNone(result["difference"])
        self.assertEqual(result["category_changes"], [])

    def test_category_moving_between_sources_is_compared_as_one_category(self) -> None:
        def month(value_month: str, card: str, other: str) -> MonthlyValues:
            return MonthlyValues.model_validate({
                "month": value_month,
                "data_kind": "actual_and_projected",
                "reference_month": "2026-07",
                "total": Decimal(card) + Decimal(other),
                "sources": {
                    "credit_card": {
                        "data_kind": "actual",
                        "status": "available",
                        "data_found": Decimal(card) != 0,
                        "total": Decimal(card),
                        "categories": {"carro": Decimal(card)} if Decimal(card) else {},
                    },
                    "other_transactions": {
                        "data_kind": "projected",
                        "status": "projected",
                        "data_found": Decimal(other) != 0,
                        "total": Decimal(other),
                        "categories": {"carro": Decimal(other)} if Decimal(other) else {},
                    },
                },
            })

        result = calculate_monthly_comparison(
            previous=month("2026-07", "598.00", "0"),
            current=month("2026-08", "0", "2032.35"),
            source="all",
            data_kind="actual_and_projected",
            limit=5,
        )

        carro = result["category_changes"][0]
        self.assertEqual(carro["previous_total"], "598.00")
        self.assertEqual(carro["current_total"], "2032.35")
        self.assertEqual(carro["difference"], "1434.35")
        self.assertEqual(
            {item["source"] for item in carro["source_breakdown"]},
            {"credit_card", "other_transactions"},
        )
