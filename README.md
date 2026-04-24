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
3. Export the environment variables:

```bash
export PRECONFIN_BASE_URL="https://api.preconfin.com/api"
export PRECONFIN_AGENT_KEY="your_agent_key_here"
```

4. Run the Python example:

```bash
python3 examples/python/cfo_agent.py
```

5. Run the TypeScript example:

```bash
npm install --save-dev typescript tsx
npx tsx examples/typescript/preconfin_agent_example.ts
```

## Notes

- The Python example uses only the Python standard library.
- The TypeScript example uses only built-in `fetch` at runtime.
- If you only want to typecheck the TypeScript file, run:

```bash
npx tsc --noEmit --target ES2022 --module NodeNext --moduleResolution NodeNext --lib ES2022,DOM examples/typescript/preconfin_agent_example.ts
```
