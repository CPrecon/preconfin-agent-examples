# Preconfin AI Agent Developer Guide

This is the full public-safe developer guide for building against the Preconfin Agent API.

If you want the fast path, start with the [quickstart](./agent-api-quickstart.md). If you want the full model, tool map, auth rules, and integration patterns, read this file.

## What Preconfin Provides to Agents

Preconfin is the financial truth layer for agents.

It gives agents:

- org-scoped Agent API keys
- canonical tools on top of backend-owned system contracts
- people snapshot KPIs
- people charts
- financial state
- system activity
- source health
- write actions through `execute_system_action`

Preconfin is not the model. It is not an LLM. It provides the finance truth, state, and action layer that your app or agent can reason over.

## Product Model

Preconfin is one running financial system.

Connected sources feed that system. Preconfin ingests and seeds data, normalizes it into consistent state, and exposes that state to both people and agents.

The same system powers:

- People mode in the app UI
- AI mode through the Agent API

Agents should ask Preconfin instead of connecting directly to Plaid, Stripe, QuickBooks, or bank systems.

## Architecture

```text
User / Agent / App
        |
        v
Preconfin Agent API
        |
        v
Canonical system contracts
        |
        v
Connected sources
```

In practice:

- Preconfin is the truth layer.
- Your model is optional.
- Your agent provides interface, orchestration, and reasoning.
- Preconfin provides state, auditability, and controlled actions.

## Base URLs

Frontend app URL and backend API URL are not the same thing.

Use these distinctions consistently:

- Frontend app URL: the browser app host you log into
- Backend API URL: the host your agent calls

Current backend Agent API base:

```text
https://api.preconfin.com/api
```

Do not use:

```text
https://staging.preconfin.com/api
```

unless that frontend host is intentionally configured as a backend proxy.

## Authentication

Agent access is controlled with org-scoped Agent App keys created in `Settings -> Agent API`.

Current behavior:

- The raw secret is shown once on create or rotate.
- The key ID is for tracking only. It is not the secret.
- Keys are scoped to the owning organization.
- Permissions are `read` or `write`.
- Keys can be rotated and revoked.
- Browser requests require browser access to be enabled.
- Browser write requests require both `write` permission and browser write to be enabled.
- Allowed tools can be restricted per key.
- Allowed origins are enforced exactly.
- Usage is audited with route, tool, action, query source, status, and timestamp.

Important fields you should expect when managing a key:

- `permissions`
- `environment`
- `browser_access_enabled`
- `browser_write_enabled`
- `allowed_origins`
- `allowed_tools`

## CORS and Browser Demos

Browser-origin calls are checked against the request `Origin` header.

Use:

```ts
const origin = window.location.origin;
```

The allowed origin must match exactly.

Expected outcomes:

- Wrong or missing key returns `401` with `invalid_api_key`.
- Malformed browser origin returns `403`.
- Browser requests are denied if browser access is disabled.
- Browser requests are denied if the origin is not on the allowlist.
- Browser write requests are denied if browser write is disabled.
- Wrong request body shape returns `422`.

Also note:

- `/api` on a frontend host is not automatically the backend Agent API.
- Use the real backend API base URL unless you intentionally own and configured a proxy.

## Canonical System Routes Behind the Agent Layer

These route names exist behind the tool layer and explain how the app is structured:

- `GET /system/snapshot`
- `GET /system/people-charts`
- `GET /system/boot-state`
- `GET /system/sources`
- `GET /system/events`
- `GET /system/financial-state-summary`
- `GET /system/financial-state-surface`
- `GET /finance/ops/surface`
- `POST /system/actions/execute`

The Agent API wraps these with thinner, safer tool and query surfaces.

## Tools

Current tool names:

- `get_financial_state`
- `get_people_charts`
- `get_people_snapshot`
- `get_system_activity`
- `get_sources`
- `execute_system_action`

### Correct Request Schema

Preferred tool execution request:

```json
{
  "tool_name": "get_people_snapshot",
  "arguments": {}
}
```

Wrong:

```json
{
  "tool": "get_people_snapshot",
  "args": {}
}
```

Endpoint:

```text
POST /agent/tools/execute
```

### `get_people_snapshot`

Purpose: overview KPIs for People mode and top-level dashboard cards.

Permission required: `read`

Request body:

```json
{
  "tool_name": "get_people_snapshot",
  "arguments": {}
}
```

Response summary:

- `schema_version`
- `captured_at`
- `organization`
- `people_snapshot.cash_balance`
- `people_snapshot.cash_runway`
- `people_snapshot.burn_rate`
- `people_snapshot.active_subscribers`
- `people_snapshot.runway_warning`

Example use cases:

- overview KPI cards
- ask "what is my burn rate?"
- show cash, runway, and subscriber snapshot together

Common UI mapping:

- Cash Balance
- Burn Rate
- Cash Runway
- Active Subscribers
- Runway Warning

### `get_people_charts`

Purpose: people-facing chart series built from canonical cashflow, operating performance, and recurring revenue services.

Permission required: `read`

Arguments:

- `start` optional `YYYY-MM-DD`
- `end` optional `YYYY-MM-DD`
- `granularity` optional `day`, `week`, or `month`

Request body:

```json
{
  "tool_name": "get_people_charts",
  "arguments": {
    "granularity": "month"
  }
}
```

Response summary:

- `period`
- `charts.cashflow.rows`
- `charts.operating_performance.rows`
- `charts.recurring_revenue.rows`

Example use cases:

- overview charts
- cashflow lines
- recurring revenue and subscriber trends

Common UI mapping:

- Cashflow chart
- Operating performance chart
- Recurring revenue chart

### `get_financial_state`

Purpose: deeper financial evidence, readiness, source coverage, inflow, outflow, net, and traceability.

Permission required: `read`

Arguments:

- `start` optional `YYYY-MM-DD`
- `end` optional `YYYY-MM-DD`
- `source` optional `plaid`, `quickbooks`, `stripe`, or `manual`
- `exclude_transfers` optional boolean, defaults to `true`

Request body:

```json
{
  "tool_name": "get_financial_state",
  "arguments": {
    "start": "2026-01-01",
    "end": "2026-03-31",
    "exclude_transfers": true
  }
}
```

Response summary:

- `readiness`
- `freshness`
- `traceability`
- `source_coverage`
- `inflow_state`
- `outflow_state`
- `net_state`
- `evidence.state_history`
- `evidence.inflow_breakdown`
- `evidence.outflow_breakdown`
- `evidence.ledger_structure`
- `evidence.source_linked_events`

Example use cases:

- expense analysis
- top vendors or merchants
- traceability and blocked-state explanation
- financial evidence pages

Common UI mapping:

- Financial State page
- expense charts
- merchant/category breakdowns
- ledger evidence

### `get_system_activity`

Purpose: recent source, action, approval, and connection events.

Permission required: `read`

Arguments:

- `source` optional `plaid`, `quickbooks`, `stripe`, `airtable`, or `slack`
- `family` optional `source`, `action`, `approval`, or `connection`
- `status` optional string
- `limit` optional integer `1-100`

Request body:

```json
{
  "tool_name": "get_system_activity",
  "arguments": {
    "source": "stripe",
    "family": "connection",
    "limit": 10
  }
}
```

Response summary:

- `filters`
- `events`
- each event includes title, detail, status, traceability, impact summary, next step, and source link information

Example use cases:

- activity feeds
- support timelines
- source health evidence

Common UI mapping:

- System activity feed
- recent source events
- what changed recently

### `get_sources`

Purpose: connected source inventory and current source/system snapshot state.

Permission required: `read`

Request body:

```json
{
  "tool_name": "get_sources",
  "arguments": {}
}
```

Response summary:

- full `system_snapshot.v1`
- `sources.connected_count`
- `sources.items`
- `system_status`
- `normalized_states`
- `outputs`

Example use cases:

- sources page
- connection health
- readiness checks

Common UI mapping:

- Connections page
- source health badges
- source status summaries

### `execute_system_action`

Purpose: write path for system actions such as connecting, refreshing, skipping, or resolving state-linked items.

Permission required: `write`

Arguments:

- `action_type` required
- `target_type` required
- `target_id` required
- `parameters` optional object

Request body:

```json
{
  "tool_name": "execute_system_action",
  "arguments": {
    "action_type": "refresh_source",
    "target_type": "source",
    "target_id": "plaid",
    "parameters": {
      "force": true
    }
  }
}
```

Response summary:

- `system_action_result.v1`
- action status
- state summary
- next system state hint
- affected entities
- optional handshake details for connect flows

Example use cases:

- refresh a source
- connect a source
- skip a source during onboarding
- resolve or acknowledge an exception

Common UI mapping:

- source refresh buttons
- onboarding connect and skip actions
- actions surface decisions

A direct `POST /agent/action` route also exists in the backend, but use the tool-shaped request above as the main integration path.

## Query Endpoint

Endpoint:

```text
POST /agent/query
```

What it does:

- deterministic routing only
- no built-in LLM reasoning
- routes plain-language requests to existing system contracts

Typical routing:

- activity and events requests route to system event data
- sources and connections requests route to source contracts
- chart and trend requests route to people charts
- financial or expense requests route to financial state
- cash balance, runway, burn rate, and active subscribers requests route to people snapshot
- revenue, MRR, ARR, subscribers, and recurring requests route to people charts
- unmatched queries fall back to the full system snapshot

Use `/agent/query` when:

- you are building an Ask page
- you want simple deterministic routing from user text
- you want a short answer plus structured data

Use tools directly when:

- you already know which UI surface you are rendering
- you need predictable field shapes
- you are building dashboard cards or charts

## Recommended Tool Usage by UI

Use this mapping:

- Overview KPIs -> `get_people_snapshot`
- Overview charts -> `get_people_charts`
- Expenses and deep financial evidence -> `get_financial_state`
- Activity feed -> `get_system_activity`
- Sources page -> `get_sources`
- Ask page -> `POST /agent/query`

Do not use `get_financial_state` or the full snapshot as a substitute for overview KPI cards when `get_people_snapshot` already provides the direct fields.

## Example Integrations

### Lovable

Use a read-only key, enable browser access, and add the exact deployed origin.

Set:

```bash
VITE_PRECONFIN_BASE_URL=https://api.preconfin.com/api
```

Call:

- `GET /agent/tools`
- `POST /agent/tools/execute`
- `POST /agent/query` for Ask-style pages

Avoid:

- write keys in the browser
- using the staging frontend host as the API host

### Bolt

Same setup as Lovable.

Best fit:

- overview cards with `get_people_snapshot`
- charts with `get_people_charts`
- source health with `get_sources`

Avoid:

- inferring overview KPIs from `get_financial_state`

### Claude Code

Use server-side environment variables and call the Agent API from scripts, shell commands, or your own wrapper.

Set:

```bash
PRECONFIN_BASE_URL=https://api.preconfin.com/api
PRECONFIN_AGENT_KEY=replace_with_your_key
```

Good starting point:

- [examples/python/cfo_agent.py](../examples/python/cfo_agent.py)

Avoid:

- storing secrets in repo files
- assuming `/agent/query` is an LLM endpoint

### Codex

Use the same env vars as Claude Code.

Current demo file:

- [examples/python/codex_cfo_agent.py](../examples/python/codex_cfo_agent.py)

The current Codex demo calls `POST /agent/tools/execute` directly with `tool_name` and `arguments`.

### Grok

Use the same env vars as Codex.

Current demo file:

- [examples/python/grok_cfo_agent.py](../examples/python/grok_cfo_agent.py)

The current Grok demo is a lightweight wrapper around the Codex CLI flow.

### OpenClaw

No dedicated OpenClaw adapter was found in this repo scan.

Recommended fallback:

- use the same HTTP pattern as the TypeScript example
- or proxy through your own backend

Do not document an OpenClaw-specific adapter as available unless a real adapter file is added.

### Plain Python CLI

Canonical folder:

```text
examples/python
```

Current runnable commands:

```bash
python3 examples/python/cfo_agent.py "what is my burn rate"
python3 examples/python/codex_cfo_agent.py "what is my burn rate"
python3 examples/python/grok_cfo_agent.py "what is my burn rate"
```

### TypeScript Browser Demo

Current example file:

- [examples/typescript/preconfin_agent_example.ts](../examples/typescript/preconfin_agent_example.ts)

Use:

```bash
VITE_PRECONFIN_BASE_URL=https://api.preconfin.com/api
PRECONFIN_AGENT_KEY=replace_with_your_key
```

For real browser deployments, also configure the exact allowed origin on the Agent App.

### Production Backend Proxy

Recommended production architecture:

```text
Browser app -> your backend or agent server -> Preconfin Agent API
```

Why:

- the browser should not hold long-lived secrets
- you can add your own auth, caching, rate limits, and policy
- you can keep write keys server-side

## Error Guide

### `400`

Usually means:

- unknown tool name
- invalid tool argument value
- invalid date format
- unsupported source or family filter

Common examples:

- `Unsupported tool: ...`
- `arguments.start must be on or before arguments.end.`
- `arguments.limit must be between 1 and 100.`

### `401 invalid_api_key`

Caused by:

- missing bearer token
- wrong bearer token
- revoked key
- using the key ID instead of the raw secret

### `403`

Possible causes:

- origin not allowed
- browser access disabled
- write attempted with a read key
- browser write disabled for a browser-origin write request
- tool not in the key allowlist

Common detail codes:

- `agent_permission_denied`
- `agent_origin_denied`
- `agent_tool_not_allowed`
- `agent_browser_write_disabled`

### `422`

Usually means the request body shape is wrong.

Examples:

- missing `tool_name`
- sending `tool` instead of `tool_name`
- sending `args` instead of `arguments`
- wrong JSON type for `arguments`

### CORS and Preflight Issues

Check:

- browser access is enabled
- the exact origin is allowlisted
- you are calling the backend API host, not the frontend app host by mistake

### Missing Raw Key After Refresh

This is expected. The raw secret is shown once on create or rotate. After that, only the key ID and metadata remain visible.

### Key ID vs Secret Key

The key ID is not the bearer token. Use the raw secret, not the visible tracking ID.

## Security Guide

- Use read-only keys for demos whenever possible.
- Do not put write keys in browser apps unless you explicitly need browser-origin write behavior.
- Prefer a backend proxy for production.
- Never log raw keys.
- Never include raw keys in screenshots.
- Keep keys org-scoped and least-privilege.
- Use tool allowlists when you only need a subset of tools.
- Do not build cross-org assumptions into your agent.

## Demo Scripts

Canonical public examples folder:

```text
examples/python
```

Current scripts found:

- `cfo_agent.py`
- `codex_cfo_agent.py`
- `grok_cfo_agent.py`

Current runnable commands:

```bash
python3 examples/python/cfo_agent.py "what is my burn rate"
python3 examples/python/codex_cfo_agent.py "what is my burn rate"
python3 examples/python/grok_cfo_agent.py "what is my burn rate"
```

OpenClaw optional adapter status:

- not found in this repo

Multi-agent comparison command status:

- not found in this repo

Do not publish docs that imply those scripts exist until files are actually added.

## Public Repo Policy

This repo is intended to be the public-facing examples repo.

Recommended policy:

- keep it public-facing
- keep examples runnable with placeholder env vars only
- keep `.env.example` in the repo
- mirror core docs changes from the private app repos when the public contract changes
- never commit secrets

Current repo scan status:

- `.env.example` exists
- the examples are thin HTTP clients over the public Agent API
- no dedicated OpenClaw adapter or multi-agent comparison script was found
