# Preconfin Agent API Quickstart

Preconfin exposes a thin, organization-scoped agent layer on top of the canonical system contracts.

You can get an external agent reading state and executing actions in a few minutes:

1. Create an Agent App in `Settings -> Agent API`.
2. Choose `read` if the agent only needs state access.
3. Choose `write` if the agent must also execute system actions.
4. Save the key immediately. Preconfin stores only the hash and will not show the full key again.
5. If the caller is a browser frontend, enable browser access and add the exact origin you control.
6. Export the environment variables shown below.
7. Call `/agent/tools` to discover available tools.
8. Call `/agent/tools/execute`, `/agent/query`, or `/agent/action` with the same bearer key.

## Base URL and auth

Production API base:

```bash
export PRECONFIN_BASE_URL="https://api.preconfin.com/api"
export PRECONFIN_AGENT_KEY="your_agent_key_here"
```

Browser apps should use:

```bash
VITE_PRECONFIN_BASE_URL="https://api.preconfin.com/api"
```

Frontend app URLs and backend API URLs are different. Do not use `https://staging.preconfin.com/api` unless that frontend host is explicitly configured as a backend proxy.

If you have a separate staging backend, set `PRECONFIN_BASE_URL` to that backend URL directly. Do not point it at the staging frontend host.

All agent calls require:

```http
Authorization: Bearer <agent_api_key>
```

Agent requests are scoped to the organization that owns the key. There is no cross-organization access.

## Deployment modes

### 1. Browser demo mode

Use this for prototypes and internal demos:

- `read` key
- `browser_access_enabled = true`
- exact allowed origin configured on the Agent App
- ideal for Bolt, Lovable, Cursor, or Vercel demos against demo or staging orgs

Architecture:

```text
Browser frontend -> Preconfin Agent API
```

Browser requests require:

- valid API key
- matching organization scope
- permission scope
- exact allowed origin match

### 2. Production mode

Use this for real customer-facing apps:

- keep the Preconfin key on your backend or agent server
- do not ship the key to the browser
- leave browser write access disabled unless you explicitly need it

Architecture:

```text
Browser frontend -> customer backend / agent server -> Preconfin Agent API
```

## Permissions

- `read`
  Can call `GET /agent/tools`, `POST /agent/tools/execute` for read tools, and `POST /agent/query`.
- `write`
  Can do everything `read` can do, plus `POST /agent/action` and `POST /agent/tools/execute` for `execute_system_action`.

Browser-origin write calls are blocked by default unless the Agent App explicitly enables browser write access.

## 1. Discover tools

```bash
curl -s \
  -H "Authorization: Bearer $PRECONFIN_AGENT_KEY" \
  "$PRECONFIN_BASE_URL/agent/tools"
```

Response items include:

- `type`
- `name`
- `description`
- `parameters`
- `permission_required`
- `example_arguments`
- `example_response`

The schema is OpenAI-compatible: each tool definition includes `type: "function"` plus a JSON Schema `parameters` object.

## 2. Execute a structured read tool

Example: dashboard overview KPIs.

```bash
curl -s \
  -H "Authorization: Bearer $PRECONFIN_AGENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "get_people_snapshot",
    "arguments": {}
  }' \
  "$PRECONFIN_BASE_URL/agent/tools/execute"
```

Overview field mapping:

- Cash Balance -> `data.people_snapshot.cash_balance`
- Burn Rate -> `data.people_snapshot.burn_rate`
- Runway -> `data.people_snapshot.cash_runway`
- Active Subscribers -> `data.people_snapshot.active_subscribers`
- Warning -> `data.people_snapshot.runway_warning`

For dashboard cards and external app overviews, call `get_people_snapshot` directly. Do not use `get_financial_state`, `get_system_snapshot`, or `/agent/query` as a substitute for these fields.

Example: recent system activity.

```bash
curl -s \
  -H "Authorization: Bearer $PRECONFIN_AGENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "get_system_activity",
    "arguments": {
      "source": "stripe",
      "family": "connection",
      "limit": 10
    }
  }' \
  "$PRECONFIN_BASE_URL/agent/tools/execute"
```

## 3. Use deterministic query routing

`POST /agent/query` is not an LLM endpoint. It routes simple natural-language requests to existing system contracts.

```bash
curl -s \
  -H "Authorization: Bearer $PRECONFIN_AGENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show recent activity",
    "context": {
      "source": "stripe",
      "family": "connection",
      "limit": 10
    }
  }' \
  "$PRECONFIN_BASE_URL/agent/query"
```

Typical routing:

- `financial`, `runway`, `burn` -> financial state surface
- `activity`, `events` -> system event ledger
- `sources`, `connections` -> source and system snapshot surface

Use `/agent/query` for deterministic routing help. For known structured overview reads, prefer calling `get_people_snapshot` directly.

## 4. Execute an action

This requires a `write` key.

```bash
curl -s \
  -H "Authorization: Bearer $PRECONFIN_AGENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action_type": "refresh_source",
    "target_type": "source",
    "target_id": "plaid",
    "parameters": {
      "force": true
    }
  }' \
  "$PRECONFIN_BASE_URL/agent/action"
```

This returns the existing `system_action_result.v1` payload.

## 5. Audit usage

`Settings -> Agent API` shows:

- last used timestamp
- recent calls
- endpoint path
- tool name when `/agent/tools/execute` was used
- action name when `/agent/action` or `execute_system_action` was used

## Runnable examples

- Python CFO agent: [examples/python/cfo_agent.py](../examples/python/cfo_agent.py)
- TypeScript example: [examples/typescript/preconfin_agent_example.ts](../examples/typescript/preconfin_agent_example.ts)
- Cursor prompt: [examples/cursor/cursor_agent_prompt.md](../examples/cursor/cursor_agent_prompt.md)
