# Preconfin Agent Examples

Use Preconfin as the financial backend for AI agents.

This repository contains public-safe Agent API docs and examples that can live outside the private app repositories. The examples stay thin and org-scoped: they call the public Agent API and do not depend on internal frontend or backend source.

## Contents

- [Quickstart](./docs/agent-api-quickstart.md)
- [Python CFO agent](./examples/python/cfo_agent.py)
- [TypeScript example](./examples/typescript/preconfin_agent_example.ts)
- [Cursor prompt](./examples/cursor/cursor_agent_prompt.md)
- [Environment template](./.env.example)

## Setup

1. Open Preconfin and create an Agent API key in `Settings -> Agent API`.
2. Choose a `read` key for state access or a `write` key if the agent must execute actions.
3. For browser demos, enable browser access on the Agent App and add the exact frontend origin you control.
4. For production, keep the key server-side and proxy through your own backend or agent server.
5. Export the environment variables:

```bash
export PRECONFIN_BASE_URL="https://api.preconfin.com/api"
export PRECONFIN_AGENT_KEY="your_agent_key_here"
```

For browser apps such as Bolt or Lovable, set:

```bash
VITE_PRECONFIN_BASE_URL="https://api.preconfin.com/api"
```

6. Run the Python example:

```bash
python3 examples/python/cfo_agent.py
```

7. Run the TypeScript example:

```bash
npm install --save-dev typescript tsx
npx tsx examples/typescript/preconfin_agent_example.ts
```

## Notes

- Browser demo mode:
  Use a read-only Agent App with `browser_access_enabled = true` and an exact allowed origin. This is appropriate for prototypes in Bolt, Lovable, Cursor, or Vercel against demo or staging orgs.
- For dashboard overview cards in Bolt or Lovable:
  Call `get_people_snapshot` for Cash Balance, Burn Rate, Runway, Active Subscribers, and runway warnings.
- For dashboard trend lines and charts in Bolt or Lovable:
  Call `get_people_charts` for cashflow, operating performance, and recurring revenue/subscriber series.
- The Python CFO example:
  Uses `get_people_snapshot` for overview KPIs and `get_financial_state` for net/readiness context.
- Production mode:
  Frontend -> your backend or agent server -> Preconfin Agent API. Keep `PRECONFIN_AGENT_KEY` out of the browser and leave browser write access disabled unless you have an explicit reason to enable it.
- Frontend and backend URLs are different:
  Use `https://api.preconfin.com/api` for the Agent API. Do not use `https://staging.preconfin.com/api` unless that frontend host is explicitly configured as a backend proxy.
- The Python example uses only the Python standard library.
- The TypeScript example uses only built-in `fetch` at runtime.
- If you only want to typecheck the TypeScript file, run:

```bash
npx tsc --noEmit --target ES2022 --module NodeNext --moduleResolution NodeNext --lib ES2022,DOM examples/typescript/preconfin_agent_example.ts
```
