# Backend (FastAPI)

## Request flow

`POST /api/plans` (`main.py`) validates the body, applies `limits.guard` (429), creates a job in `jobs.JobStore` and runs `planning.execute_plan` on a worker thread. The client polls `GET /api/plans/{id}`.

`planning.execute_plan`: direct route (`ors.route_coords`, cached and shared with `/api/route`) → free-time budget (`budget.py`; under 45 free minutes it returns the direct route and calls nothing else) → daily token budget check → agent (`agent.run_agent` with `agent_tools.ToolBox`) → on success format the plan, on failure `baseline_plan` using the places the agent already found → final route through the stops (`ors.route_through`).

## Modules

| Module | Role |
|---|---|
| `main.py` | API, pydantic response models, errors as `{"error": ...}`, static hosting of `client/dist` |
| `planning.py` | One plan end to end; `Deps` bundles every external call so tests can swap them |
| `agent.py` | System prompt, `AGENT_MODEL` / `AGENT_EFFORT`, the manual tool loop, limits, per-round logging |
| `agent_tools.py` | Tool schemas (`TOOLS`), `ToolBox` (runs tools, enforces limits, filters and describes places), `describe_call` for logs |
| `validator.py` | The authority: `validate_itinerary` checks and schedules a proposal, fixes up to 15 minutes of delay by shortening visits, enforces the detour limit |
| `planner.py` | Candidate filtering (`select_candidates`) and the rule-based planner |
| `fill.py` | Lengthens visits when more than 40 spare minutes would be left at arrival (checks opening hours, never passes the deadline minus the margin); used on agent and planner plans |
| `comparison.py` | AI-vs-planner comparison on fixed trips with a spending cap (`Spend`, `BudgetedClient`, `PlaceRecorder`), measurements and the markdown report |
| `evalservice.py`, `reportstore.py`, `adminpage.py` | Runs a comparison in the background (one at a time) for the admin endpoints; saves (Postgres when `DATABASE_URL` is set, else files), logs and serves the report, including after a restart; the small admin page |
| `travel.py` | `TravelTimes`: per-plan memory of driving times, one matrix request fills every known pair |
| `geo.py` | Haversine, distance to a route, thinning, Google polyline encoding |
| `places.py`, `ors.py` | Provider clients; they raise `PlacesError` / `RouteError` with user-safe messages |
| `http_client.py` | Pooled keep-alive client; a timeout is not retried, a dropped connection is retried once |
| `jobs.py`, `jobtrace.py` | In-memory job state machine, idempotency, backpressure; job id on every log line |
| `limits.py` | Rate limits, daily token budget, cost log line, access-log redaction |
| `budget.py`, `hours.py` | Free-time maths; opening hours across weekdays, midnight and 24-hour places |

## Conventions

- Provider errors carry a message that is safe to show. Never put a response body, key or URL with a key into an exception message; log details instead.
- Log one line per event, no coordinates and no user text. `jobtrace` adds the job id automatically inside a job.
- Tunable numbers are named constants at the top of their module. Settings that an operator may change are environment variables read through `config.get`; document each in `README.md` and `.env.example`.
- Everything that talks to the network is injected (`planning.Deps`, `ToolBox(search_nearby, travel_matrix, search_along_route)`), which is what keeps the tests offline.
- Times are timezone-aware datetimes; convert only at the edges. Google opening-hour days start on Sunday = 0.
- Jobs, limits and caches are in memory: the app must run as a single worker process.

## Checklists

**Add or change an agent tool:** schema in `TOOLS`, handler in `ToolBox.run`, add it to `describe_call`, mention it in `SYSTEM_PROMPT` (a test checks that every tool the prompt names exists), keep results small (they are re-sent every round; compact JSON, only fields the model needs), count it against a limit, test it with the fakes.

**Change what the model sees or may do:** the validator must still enforce every rule independently; the prompt only asks nicely.

**Add a setting:** read it with `config.get` at call time (tests patch `os.environ`), validate it, ignore bad values with a warning, then update `.env.example` and the README table.

**Switching model:** prices in `ANTHROPIC_PRICE_*` must be updated too (the comparison has a `LIST_PRICES` table in `comparison.py` for models it knows; add the new model there). A model call stopped by the comparison cap ends the agent with reason `budget`, not `llm_unavailable`. Thinking blocks are replayed unchanged on purpose; do not filter or rewrite assistant content.

**Reconsideration:** `ToolBox._submit_itinerary` holds a valid itinerary once (`_held`) when `fill` could not use up most of the spare time and another stop is possible; the reply is an error-flagged tool result asking the model to reconsider, and the submission is refunded. `ToolBox.settle()` (called at the end of `run_agent`) falls back to the held plan. `agent_tools.RECONSIDER` switches it off; the shared test fixtures in `test_agent.py` do, and `test_reconsider.py` turns it on.

## Admin endpoints

`/api/admin/evals` (start, list, read) spends real money. It exists only when `ADMIN_TOKEN` is set and needs it as a bearer token; the budget is validated (0.05 to 1.00). Never log or echo the token or `DATABASE_URL`, and keep them out of URLs and error messages (the storage check returns only the kind of error). The admin page puts everything on screen as text (no `innerHTML`), keeps the token only in memory, and is served with a strict Content-Security-Policy; tests guard each of these. Database queries are parameterised and psycopg is imported lazily, so tests use a fake connection and no database is needed. Do not call these endpoints or run the comparison without the owner's approval.

## Gotchas

- `TravelTimes` keys places by rounded coordinates, so two places at identical coordinates are one node. Fakes need distinct coordinates.
- `search_places` results are cut to 12 after the detour check, but all checked places stay in `ctx.known_places`.
- The Places field mask includes rating and opening hours, which bills at the higher Enterprise tier. Do not add fields casually.
- `ors.route_coords` caches for 120 s and remembers a failure for 5 s so concurrent requests share one outcome.
- Typical visit lengths live in `planner.VISIT_MINUTES` (the model sees them, and `fill.py` lets a visit grow to one and a half times its typical length); give new place types a realistic value so a cafe is not stretched into an hour and a half.
