---
name: preconfin_finance
description: Use Preconfin as the only financial source of truth for CFO and finance questions.
---

# Preconfin Finance

Use this skill for burn, runway, cash, revenue, spend, vendor, source-health, or finance activity questions.

## Rules

- Preconfin is the only financial source of truth.
- Never connect directly to Stripe, Plaid, QuickBooks, banks, Supabase, or any other finance backend.
- Only call the Preconfin Agent API through the local adapter.
- Never print `PRECONFIN_AGENT_KEY` or any authorization header.
- Treat `0` as a valid value, not missing data.

## Local command

Run:

```bash
python3 skills/preconfin_finance/preconfin_tool.py "<finance question>"
```

For a multi-section summary:

```bash
python3 skills/preconfin_finance/preconfin_tool.py --report
```

For sanitized JSON output:

```bash
python3 skills/preconfin_finance/preconfin_tool.py --raw "<finance question>"
```

## Routing

- Burn, runway, cash, balance, revenue, MRR, ARR: `get_people_snapshot`
- Expenses, spend, vendors, merchants, categories: `get_financial_state`
- Charts, trends, monthly history: `get_people_charts`
- Activity, recent changes, failures, sync status: `get_system_activity`
- Sources, integrations, stale connections: `get_sources`
- Needs attention: `get_sources` + `get_system_activity` + `get_people_snapshot`

Treat the adapter output as authoritative unless it explicitly says data is unavailable.
