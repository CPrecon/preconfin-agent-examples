from __future__ import annotations

import unittest

import codex_cfo_agent as subject


class ExpenseSectionTests(unittest.TestCase):
    def test_expense_section_uses_outflow_categories_only(self) -> None:
        payload = {
            "data": {
                "evidence": {
                    "inflow_breakdown": {
                        "category": [
                            {"category": "Revenue / Customer Payments", "amount_cents": 900_000},
                        ]
                    },
                    "outflow_breakdown": {
                        "category": [
                            {"category": "Uncategorized Expense", "amount_cents": 450_000},
                            {"category": "AI / Model Spend", "amount_cents": 125_000},
                            {"category": "SaaS Tools", "amount_cents": 0},
                        ]
                    },
                }
            }
        }

        heading, rows = subject.expense_section_details(payload)

        self.assertEqual(heading, "Top Expenses")
        self.assertEqual(
            [row["Expense"] for row in rows],
            ["Uncategorized Expense", "AI / Model Spend"],
        )

    def test_expense_section_falls_back_to_merchants(self) -> None:
        payload = {
            "data": {
                "evidence": {
                    "outflow_breakdown": {
                        "merchant": [
                            {"merchant": "Cloudflare", "amount_cents": 0},
                            {"merchant": "OpenAI", "amount_cents": 275_000},
                        ]
                    }
                }
            }
        }

        heading, rows = subject.expense_section_details(payload)

        self.assertEqual(heading, "Top Expense Merchants")
        self.assertEqual([row["Expense"] for row in rows], ["OpenAI"])

    def test_zero_rows_are_kept_only_when_no_nonzero_rows_exist(self) -> None:
        payload = {
            "data": {
                "evidence": {
                    "outflow_breakdown": {
                        "merchant": [
                            {"merchant": "AWS", "amount_cents": 0},
                            {"merchant": "Anthropic", "amount_cents": 0},
                        ]
                    }
                }
            }
        }

        heading, rows = subject.expense_section_details(payload)

        self.assertEqual(heading, "Top Expense Merchants")
        self.assertEqual([row["Expense"] for row in rows], ["AWS", "Anthropic"])


class RunwayWarningTests(unittest.TestCase):
    def test_runway_warning_prefers_one_sentence(self) -> None:
        warning = {
            "title": "Runway is critically low",
            "reason": "Runway is critically short due to current burn rate",
        }

        self.assertEqual(
            subject.runway_warning_summary(warning),
            "Runway is critically short due to current burn rate.",
        )


if __name__ == "__main__":
    unittest.main()
