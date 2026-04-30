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
                "source_coverage": {"connected_count": 2, "total_count": 3},
                "freshness": {"freshness_status": "stale"},
                "traceability": {
                    "traceability_status": "partial",
                    "not_ready_reason": "Billing sync requires approval before vendor detail can be traced.",
                },
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
        sources_payload = {
            "data": {
                "sources": [
                    {"name": "Mercury", "status": "connected"},
                    {"name": "Stripe", "ingest_status": "ready"},
                    {"name": "Ramp", "status": "blocked"},
                ]
            }
        }

        markdown = subject.build_report_markdown(
            snapshot_payload,
            financial_payload,
            {"data": {"activity": []}},
            sources_payload,
            {},
            [
                "charts/cashflow.png",
                "charts/operating_performance.png",
                "charts/recurring_revenue.png",
            ],
        )

        self.assertIn("## 🔴 Immediate Takeaway", markdown)
        self.assertIn("- Cash is critically tight: runway is 0.1 months and cash balance is $12.20.", markdown)
        self.assertIn("Net position is -$1,278.41, so cut nonessential spend and lock a funding or collections plan this week.", markdown)

        self.assertIn(
            "- Critical runway: Runway is critically short at 0.1 months. Reduce burn or raise capital immediately. → Finalize a same-week cash preservation plan and confirm funding or collections timing.",
            markdown,
        )
        self.assertIn(
            "- Low cash balance: $12.20 → Pause nonessential spend and verify the next 7 days of cash commitments.",
            markdown,
        )
        self.assertIn(
            "- Negative net: -$1,278.41 → Cut the fastest discretionary costs and match this week's outflows to confirmed cash in.",
            markdown,
        )
        self.assertIn(
            "- High uncategorized expense: Uncategorized Expense at $3,370.39 → Review and recategorize this line so cost controls target the right bucket.",
            markdown,
        )

        self.assertIn("## This Week’s Priorities", markdown)
        self.assertIn("- Cut or defer spend immediately to extend runway beyond 0.1 months.", markdown)
        self.assertIn("- Build a 7-day cash plan around the current $12.20 balance.", markdown)
        self.assertIn("- Close the -$1,278.41 net gap by matching spend to confirmed cash in.", markdown)
        self.assertIn(
            "- Review the $3,370.39 Uncategorized Expense line and recategorize or stop anything nonessential.",
            markdown,
        )
        self.assertIn("- Review AI / Model Spend at $303.12 and confirm it is required this month.", markdown)

        self.assertIn("### Cashflow\n![Cashflow](charts/cashflow.png)", markdown)
        self.assertIn(
            "### Operating Performance\n![Operating Performance](charts/operating_performance.png)",
            markdown,
        )
        self.assertIn(
            "### Recurring Revenue\n![Recurring Revenue](charts/recurring_revenue.png)",
            markdown,
        )
        self.assertIn("## System Status", markdown)
        self.assertIn("- Sources connected: 2 / 3", markdown)
        self.assertIn("- Data freshness: stale", markdown)
        self.assertIn("- Traceability: partial", markdown)
        self.assertIn(
            "- Traceability note: Billing sync requires approval before vendor detail can be traced.",
            markdown,
        )
        self.assertNotIn("- [Cashflow](charts/cashflow.png)", markdown)
        self.assertEqual(markdown.count("![Cashflow](charts/cashflow.png)"), 1)
        self.assertEqual(markdown.count("![Operating Performance](charts/operating_performance.png)"), 1)
        self.assertEqual(markdown.count("![Recurring Revenue](charts/recurring_revenue.png)"), 1)
        self.assertLess(markdown.index("## 🔴 Immediate Takeaway"), markdown.index("## Executive Summary"))
        self.assertLess(markdown.index("## Executive Summary"), markdown.index("## Cash / Burn / Runway Snapshot"))
        self.assertLess(markdown.index("## Cash / Burn / Runway Snapshot"), markdown.index("## System Status"))
        self.assertLess(markdown.index("## System Status"), markdown.index("## Top Expenses"))
        self.assertLess(markdown.index("## Top Expenses"), markdown.index("## Recent Activity"))
        self.assertLess(markdown.index("## Recent Activity"), markdown.index("## Needs Attention"))
        self.assertLess(markdown.index("## Needs Attention"), markdown.index("## This Week’s Priorities"))
        self.assertLess(markdown.index("## This Week’s Priorities"), markdown.index("## Charts"))

    def test_system_status_falls_back_to_get_sources_counts(self) -> None:
        markdown = subject.build_report_markdown(
            {"data": {"people_snapshot": {}}},
            {
                "data": {
                    "freshness": {"freshness_status": "current"},
                    "traceability": {"traceability_status": "full"},
                }
            },
            {"data": {"activity": []}},
            {
                "data": {
                    "sources": [
                        {"name": "Mercury", "status": "connected"},
                        {"name": "Stripe", "connection_status": "ready"},
                        {"name": "Ramp", "ingest_status": "seeding"},
                        {"name": "NetSuite", "status": "blocked"},
                    ]
                }
            },
            {},
            [],
        )

        self.assertIn("- Sources connected: 3 / 4", markdown)
        self.assertIn("- Data freshness: current", markdown)
        self.assertIn("- Traceability: full", markdown)
        self.assertIn("- Traceability note: Unknown", markdown)


if __name__ == "__main__":
    unittest.main()
