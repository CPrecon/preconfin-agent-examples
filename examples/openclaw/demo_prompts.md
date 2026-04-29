# Demo Prompts

Try these from the workspace root:

```bash
python3 cfo_agent.py "what is my burn rate"
python3 cfo_agent.py "how much runway do I have"
python3 cfo_agent.py "show cash and subscribers"
python3 cfo_agent.py "show my top expenses"
python3 cfo_agent.py "break down spend by vendors"
python3 cfo_agent.py "show monthly trend charts"
python3 cfo_agent.py "what changed recently"
python3 cfo_agent.py "any recent failures"
python3 cfo_agent.py "which sources are stale"
python3 cfo_agent.py "what needs attention"
```

## Routing Notes

- `burn`, `runway`, `cash`, `subscribers` route to `get_people_snapshot`
- `expenses`, `spend`, `merchants`, `vendors` route to `get_financial_state`
- `trend`, `chart`, `monthly` route to `get_people_charts`
- `recent`, `changed`, `failures` route to `get_system_activity`
- `sources`, `integrations`, `stale` route to `get_sources`
- `needs attention` fans out to `get_sources`, `get_system_activity`, and `get_people_snapshot`

For debugging only:

```bash
python3 cfo_agent.py --raw "what is my burn rate"
```
