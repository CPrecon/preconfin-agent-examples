# Preconfin OpenClaw Demo

OpenClaw can use Preconfin as the financial source of truth through a local zero-dependency Python adapter that calls only the Preconfin Agent API.

This repo does not connect directly to Stripe, Plaid, QuickBooks, banks, or Supabase. All finance reads go through:

```text
POST ${PRECONFIN_BASE_URL}/agent/tools/execute
```

with:

```json
{
  "tool_name": "<tool_name>",
  "arguments": {}
}
```

## Files

- `README.md`
- `.env.example`
- `cfo_agent.py`
- `demo_prompts.md`
- `skills/preconfin_finance/SKILL.md`
- `skills/preconfin_finance/skill.md`
- `skills/preconfin_finance/preconfin_tool.py`

## Environment

```bash
export PRECONFIN_BASE_URL="https://api.preconfin.com/api"
export PRECONFIN_AGENT_KEY="replace-me"
```

`PRECONFIN_BASE_URL` defaults to `https://api.preconfin.com/api`. `PRECONFIN_AGENT_KEY` must be set in the environment.

## Runtime auth caveat

Some OpenClaw installs may require separate provider auth before the runtime will execute workspace-local skills. Preconfin itself only requires `PRECONFIN_AGENT_KEY`.

If OpenClaw auth is the failure point, run the deterministic adapter directly:

```bash
python3 skills/preconfin_finance/preconfin_tool.py "what is my burn rate"
```

Or use the wrapper demo script:

```bash
python3 cfo_agent.py "what is my burn rate"
```

## Available Preconfin tools

- `get_people_snapshot`
- `get_people_charts`
- `get_financial_state`
- `get_system_activity`
- `get_sources`

## Deterministic routing

- Burn, runway, cash, balance, MRR, ARR, revenue: `get_people_snapshot`
- Expenses, spend, vendors, merchants, categories: `get_financial_state`
- Charts, trends, monthly history: `get_people_charts`
- Activity, recent changes, failures, sync status: `get_system_activity`
- Sources, integrations, stale connections: `get_sources`
- Needs attention: `get_sources` + `get_system_activity` + `get_people_snapshot`

## CLI usage

```bash
python3 skills/preconfin_finance/preconfin_tool.py "what is my burn rate"
python3 skills/preconfin_finance/preconfin_tool.py --raw "what is my burn rate"
python3 skills/preconfin_finance/preconfin_tool.py --report
```

## OpenClaw registration

This environment's OpenClaw install supports workspace-local skills. The active workspace skill is discovered from:

```text
skills/preconfin_finance/SKILL.md
```

From this repo:

```bash
openclaw skills list
openclaw skills check
openclaw skills info preconfin_finance
```

If OpenClaw is running in this directory as the workspace, no extra plugin registration is required. The lowercase `skill.md` is included for compatibility with tools that look for that filename, but OpenClaw here detects `SKILL.md`.

## Verification

```bash
python3 -m py_compile skills/preconfin_finance/preconfin_tool.py
python3 skills/preconfin_finance/preconfin_tool.py "what is my burn rate"
```

The second command requires `PRECONFIN_AGENT_KEY`. Without it, the adapter fails cleanly and does not print secrets.
