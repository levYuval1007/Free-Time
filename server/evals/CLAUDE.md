# Evals (these cost money)

`run_evals.py` runs the comparison in `comparison.py`: fixed trips through the real agent (**real Claude, Google Places and OpenRouteService**), then the rule-based planner on the same places. A scenario is roughly two Places searches plus a few thousand model tokens (about 10 cents), and the set also uses part of the free routing quota. Spending is capped by `--max-usd` (default 0.30) and enforced before each paid call. The same comparison can run on the deployed server through `/api/admin/evals` (see `server/CLAUDE.md`).

- **Never run it without the owner's explicit approval.** It refuses to run without `--yes`; that flag is not a formality.
- It needs `ANTHROPIC_API_KEY`, `GOOGLE_MAPS_API_KEY` and `ORS_API_KEY` in `server/.env` or the environment. The Anthropic key may exist only on Render; do not look for it or ask for it in chat.
- From `server/`: `.venv\Scripts\python.exe evals\run_evals.py --yes [--only "text"] [--max-usd 0.30]`. The report is printed and saved to `server/evals/results/` (git-ignored).

## What it checks (by code, not by eye)

At most three stops, stops in time order, arrival before the deadline minus the safety margin, no stops when there is no free time, no leaked prompt or tool names in the output, and for the long-route scenario at least one stop far from both ends. The report puts both planners side by side: valid or not, whether a stop matches the preference (by place type, `wants` on the scenario), spare minutes at arrival, stops, rating, extra driving, time and cost.

## Adding a scenario

Add a `Scenario(...)` to `SCENARIOS` in `comparison.py` (put `wants` place types if a preference can be checked by type) and, if it needs a new kind of check, extend `check()` and cover that check in `tests/test_evals.py` (the checker itself is unit-tested offline). Keep the set small: every scenario costs money each time it runs.

To compare models or settings, change `AGENT_MODEL` / `AGENT_EFFORT` in the environment, run the same scenarios, and compare the printed rounds, tokens and time. Say clearly what was measured and on how few runs.
