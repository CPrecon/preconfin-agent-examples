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


class ReportFormattingTests(unittest.TestCase):
    def test_report_needs_attention_and_chart_markdown_are_clean(self) -> None:
        snapshot_payload = {
            "data": {
                "people_snapshot": {
                    "cash_balance": {"amount_cents": 1_220},
                    "burn_rate": {"amount_cents": 23_400},
                    "cash_runway": {"months": 0.1},
                    "active_subscribers": {"count": 5},
                    "runway_warning": {
                        "reason": "Runway is critically short at 0.1 months. Reduce burn or raise capital immediately."
                    },
                }
            }
        }
        financial_payload = {
            "data": {
                "net_state": {"net_amount": -1_278.41},
                "readiness": {"status": "ready"},
                "evidence": {
                    "outflow_breakdown": {
                        "category": [
                            {"category": "Uncategorized Expense", "amount_cents": 337_039, "txn_count": 34},
                            {"category": "AI / Model Spend", "amount_cents": 30_312, "txn_count": 13},
                        ]
                    }
                },
            }
        }

        markdown = subject.build_report_markdown(
            snapshot_payload,
            financial_payload,
            {"data": {"activity": []}},
            {"data": {"sources": []}},
            {},
            [
                "charts/cashflow.png",
                "charts/operating_performance.png",
                "charts/recurring_revenue.png",
            ],
        )

        self.assertIn("- Critical runway: Runway is critically short at 0.1 months. Reduce burn or raise capital immediately.", markdown)
        self.assertIn("- Low cash balance: $12.20", markdown)
        self.assertIn("- Negative net: -$1,278.41", markdown)
        self.assertIn("- High uncategorized expense: Uncategorized Expense at $3,370.39", markdown)

        self.assertIn("### Cashflow\n![Cashflow](charts/cashflow.png)", markdown)
        self.assertIn(
            "### Operating Performance\n![Operating Performance](charts/operating_performance.png)",
            markdown,
        )
        self.assertIn(
            "### Recurring Revenue\n![Recurring Revenue](charts/recurring_revenue.png)",
            markdown,
        )
        self.assertNotIn("- [Cashflow](charts/cashflow.png)", markdown)
        self.assertEqual(markdown.count("![Cashflow](charts/cashflow.png)"), 1)
        self.assertEqual(markdown.count("![Operating Performance](charts/operating_performance.png)"), 1)
        self.assertEqual(markdown.count("![Recurring Revenue](charts/recurring_revenue.png)"), 1)


if __name__ == "__main__":
    unittest.main()
