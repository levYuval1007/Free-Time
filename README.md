# Leeway

*Make the most of the time before you have to be there.*

You are somewhere, you have to be somewhere else at a given time, and you have spare time in between. Enter where you are, where you need to be, and when. Leeway works out how much free time you have after the direct drive, and an AI agent proposes up to three worthwhile stops on the way (parks, viewpoints, museums, cafes) that fit that time, respect opening hours, and never make you late.

- **Mobile first.** On a phone the plan is a map with a swipeable card carousel (overview, each stop, destination) that zooms the map to the card you are on. On a desktop the plan is a column next to the map.
- **Tell it what you like.** An optional free-text preference ("quiet places, coffee first", "with kids") steers the choice.
- **It explains itself.** Every stop has a one-line reason, and the plan has a short summary.
- **Open in Google Maps** hands the finished plan, stops included, to navigation.

## How it works

```
  Browser (React)                       Server (FastAPI)                         Outside
  ───────────────                       ────────────────                         ───────
  type an address ─────────────────────▶ /api/suggest ──────────────────────────▶ Google Places (autocomplete)
  pick one        ─────────────────────▶ /api/places/resolve ───────────────────▶ Google Places (details)
  "Plan my trip"  ─┬───────────────────▶ /api/route ────────────────────────────▶ OpenRouteService (directions)
                   └───────────────────▶ POST /api/plans  → job starts in the background
  poll every 1.5s ─────────────────────▶ GET /api/plans/{id}
                                          job:  free-time budget
                                                agent loop ◀──────────────────▶ Claude
                                                  ├ search_places / search_along_route ─▶ Google Places
                                                  └ submit_itinerary ─▶ validator (code decides)
                                                fallback: rule-based planner
                                                final route ───────────────────▶ OpenRouteService
```

### The principle: the model proposes, the code decides

An LLM is an unreliable component, so it is boxed in:

1. **It only chooses.** Which places to search for, which to visit, in what order, and how long to stay. It never writes a time.
2. **Every time is computed by the server** from real driving times (`validator.py`). The model's own arithmetic is not used.
3. **Everything it proposes is checked.** A stop must come from a search in the same run, there are at most three, each visit lasts 20 to 180 minutes, the place is open for the whole visit plus a 15-minute margin, a stop adds at most 20 minutes of driving compared with going straight, and arrival is before the deadline minus a safety margin. A plan up to 15 minutes late is fixed by shortening visits; anything else is rejected with the exact problems so the model can correct itself (three submissions at most).
4. **There is always a fallback.** If Claude is unavailable, refuses, runs out of budget, or never submits a valid plan, a deterministic planner produces the plan and the app says it is a basic plan.
5. **Hard limits everywhere:** 8 model rounds, 3 searches, 3 submissions, 60,000 tokens per plan, 75 seconds, plus per-address and daily limits (see [Cost and abuse protection](#cost-and-abuse-protection)).

### Free-time budget

`free time = minutes until the deadline − direct drive − safety margin`, where the margin is the larger of 15 minutes and 10% of the drive. With less than 45 free minutes Leeway just shows the direct route and does not call the agent or search for places at all.

### Using the spare time

Leeway aims to get you to the destination 15 to 40 minutes before the deadline. The agent is told so. If a plan, from the agent or from the rule-based planner, would still leave more than 40 minutes, the server lengthens the visits: five minutes at a time, shared between the stops, up to twice the typical visit for that kind of place (never more than 180 minutes), and only while every stop stays open for the whole longer visit and the arrival stays before the deadline minus the safety margin. Driving times do not change, so no new routing request is needed. When the stops cannot grow any further the plan simply stays as it is.

### The agent's tools

| Tool | Purpose |
|---|---|
| `search_places` | Places near a point (radius 300 to 5000 m, optional types such as park, museum, cafe). The point must be within 15 km of the start or the destination. |
| `search_along_route` | Free-text search ("scenic viewpoint", "bakery") along the whole direct route, using Google's search along route. |
| `submit_itinerary` | The final plan: stops in order with an optional visit length and a short reason, plus a summary. Runs the validator. |

Searches return at most 12 places, best quality first, after removing places that are not operational, have unknown opening hours, are poorly rated (below 3.6 stars or fewer than 15 reviews), are bars and similar, or would add more than the detour limit. Each place carries `detour_minutes`, `minutes_from_start`, `minutes_to_destination` and today's opening hours, so the model can estimate the schedule without asking.

### The rule-based planner

The same candidates, no AI: a depth-first search over up to three stops from the 40 best candidates, scored by `(rating − 3.5) × log10(1 + reviews)`, honouring opening hours. It is the fallback when the agent fails, and `GET /api/plan` exposes it directly.

## Repository layout

```
server/                 FastAPI backend (Python)
  main.py               HTTP API, error shape, static hosting of the built client
  planning.py           one plan end to end: budget, agent, fallback
  agent.py              the Claude tool loop, prompt, model and effort settings
  agent_tools.py        the tools the model can call, and what each returns
  validator.py          the authority: checks and schedules a proposed itinerary
  planner.py            rule-based planner and candidate filtering
  fill.py               lengthens visits to use spare time (agent and planner plans alike)
  budget.py, hours.py   free-time budget, opening-hours maths
  travel.py, geo.py     per-plan travel-time memory, route geometry and polyline encoding
  jobs.py, jobtrace.py  in-memory job store and runner, job id on every log line
  limits.py             rate limits, token budget, cost log lines, log redaction
  places.py, ors.py     Google Places and OpenRouteService clients
  http_client.py        pooled keep-alive HTTPS client
  config.py             .env loader (environment variables win)
  tests/                unit tests, all offline (see tests/CLAUDE.md)
  comparison.py         AI agent vs planner on fixed trips, inside a spending cap, and its report
  evalservice.py        runs a comparison in the background of the server (admin endpoint)
  reportstore.py        where finished comparison reports are saved
  evals/run_evals.py    command line for the comparison (costs money)
  travel_time.py        small legacy command line tool: two places, one drive time
client/                 React 18 + TypeScript + Vite 5
  src/App.tsx           state and the plan flow
  src/components/       form fields, map, timeline, phone carousel
  src/lib/              pure helpers (arrival slots, polling, carousel maths) with vitest tests
```

## Setup

Requirements: Python 3.10 or newer (developed on 3.14) and Node.js (developed on 21; Vite 5).

**API keys** (never commit them):

| Variable | Used for |
|---|---|
| `GOOGLE_MAPS_API_KEY` | Google Places (autocomplete, place details, nearby and route search) |
| `ANTHROPIC_API_KEY` | The planning agent (Claude). Without it plans use the rule-based planner |
| `ORS_API_KEY` | OpenRouteService routing (free key from openrouteservice.org) |

Put them in `server/.env` (copy `server/.env.example`; the file is git-ignored), or set environment variables. Environment variables take priority over `.env`. In PowerShell, for the current window only:

```powershell
$env:GOOGLE_MAPS_API_KEY = "your-key"
```

**Optional settings** (environment variables; the defaults are fine to start with):

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_MODEL` | `claude-sonnet-5` | Claude model for the planning agent. If a model is unavailable or rejects a setting, the plan falls back to the basic planner |
| `AGENT_EFFORT` | the model's default | How hard the model thinks: `low`, `medium`, `high`, `xhigh` or `max`. Not every model accepts it |
| `ADMIN_TOKEN` | unset | Secret for the admin endpoints that run the comparison on the server. Unset means those endpoints do not exist |
| `EVAL_RESULTS_DIR` | `server/evals/results` | Where comparison reports are saved. On a host whose disk is wiped on restart, point it at a persistent disk or read the report from the endpoint or the log |
| `PLANS_PER_IP_PER_HOUR` | 8 | Plans one address may start per hour (then 429) |
| `PLANS_PER_DAY` | 150 | Plans per day for everyone (then 429) |
| `AGENT_DAILY_TOKENS` | 2,000,000 | Agent tokens per day; after that plans use the basic planner |
| `ANTHROPIC_PRICE_*_PER_MTOK` | unset | `INPUT`, `OUTPUT`, `CACHE_READ` and `CACHE_WRITE` prices in USD per million tokens, for a cost estimate in the log. Update them when you change the model |

**Server:**

```powershell
cd server
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Client:**

```powershell
cd client
npm install
```

## Run

**Development** (hot reload; Vite proxies `/api` to the server). Terminal 1:

```powershell
cd server
.venv\Scripts\python.exe -m uvicorn main:app --port 8000 --reload
```

Terminal 2, then open http://127.0.0.1:5173:

```powershell
cd client
npm run dev
```

**Single process** (FastAPI serves the built client if `client/dist` exists when the server starts, so restart the server after building). Open http://127.0.0.1:8000:

```powershell
cd client
npm run build
```

API docs are at http://127.0.0.1:8000/docs.

## API

All errors are JSON: `{"error": "message"}`.

| Endpoint | What it does |
|---|---|
| `GET /api/suggest?q&session[&lat&lon]` | Address and place suggestions from Google (falls back to OpenRouteService), biased towards the user's location |
| `GET /api/places/resolve?place_id&session` | Coordinates and address of a chosen suggestion |
| `GET /api/route?from_lon&from_lat&to_lon&to_lat[&arrive_by]` | The direct route (geometry, steps) and, with `arrive_by`, the free-time budget |
| `GET /api/plan?...&arrive_by` | The rule-based plan in one request (no AI) |
| `POST /api/plans` | Starts a planning job (agent with fallback) and returns `202` with a `job_id`. Send an `Idempotency-Key` header to make retries and double clicks safe: the same key and body return the same job |
| `GET /api/plans/{job_id}` | `status` is `queued`, `running`, `succeeded`, `degraded` (the agent failed and the basic planner answered; see `degraded_reason`) or `failed`, with the progress `stage` and the `result` |

Status codes: `400` invalid request, `404` unknown or expired job, `409` idempotency key reused with a different request, `429` plan limit reached (with `Retry-After`), `502` a provider failed, `503` too many plans running (with `Retry-After`).

## Test

```powershell
cd server
.venv\Scripts\python.exe -m unittest discover -s tests
```

```powershell
cd client
npm run typecheck
npm test
```

Server tests never touch the network: Claude, Google and OpenRouteService are replaced by fakes. The real services are exercised only by the comparison (next section), which costs money.

## Comparing the AI with the planner

Does the agent actually choose better than the rule-based planner? The comparison answers that on fixed trips (a quiet coffee, with kids, museums, a long route, no preference, a prompt-injection attempt, and a trip with no free time). Each scenario runs the real agent once; the planner then runs on **the same places the agent found**, so both choose from identical candidates and the planner adds no Places cost. The planner cannot read the preference text, which is the point. The report shows, side by side: whether each plan passes every check, whether a stop matches the stated preference (by place type), spare minutes at arrival, number of stops, average rating, extra driving, and time and estimated cost.

**Cost is capped in code.** `max_usd` defaults to $0.30 (the server accepts $0.05 to $1.00). A search is refused if it would pass the cap, a model call is refused if it could, and a scenario is skipped when too little is left. A scenario costs roughly 10 cents, so 30 cents is two or three scenarios (the order puts the most informative first, and the trip with no free time is always free). The figure is an estimate: Places at list price and Claude from `ANTHROPIC_PRICE_*`, or assumed list prices, which the report states.

**On the server** (where the keys are). Set `ADMIN_TOKEN` to a long random secret in the service's environment (without it the endpoints return 404), then, in PowerShell:

```powershell
$h = @{ Authorization = "Bearer YOUR_ADMIN_TOKEN" }
$run = Invoke-RestMethod -Method Post -Uri "https://YOUR-APP.onrender.com/api/admin/evals" -Headers $h `
  -ContentType application/json -Body '{"max_usd": 0.30}'
$run.id
# a minute or two later
(Invoke-WebRequest -Uri "https://YOUR-APP.onrender.com/api/admin/evals/$($run.id)?format=md" -Headers $h).Content
```

`GET /api/admin/evals/{id}` returns the status, progress and the full report as JSON (`?format=md` for the readable version) and `GET /api/admin/evals` lists recent runs. Only one comparison runs at a time. Each finished report is saved as `<id>.md` and `<id>.json` in the results folder **and written to the log line by line** (search the log for `report |`). A free Render service wipes its disk on every restart, so the saved files are lost then; the log and the endpoint (while the process lives) are what to rely on, unless `EVAL_RESULTS_DIR` points at a persistent disk.

**Locally**, with all three keys in `server/.env`:

```powershell
cd server
.venv\Scripts\python.exe evals\run_evals.py --yes --max-usd 0.30
```

Treat one run as a sample, not a verdict: the model varies between runs and there are few scenarios.

## Deploying

The server serves the built client, so one web service is enough. `client/dist` is not committed, so the build step has to produce it. On Render, for example:

- **Build:** install the Python requirements and build the client (`pip install -r server/requirements.txt`, then `npm install && npm run build` inside `client/`).
- **Start:** run `uvicorn main:app --host 0.0.0.0 --port $PORT` from the `server/` directory.
- **Environment:** the three API keys and any optional settings above.

Run **one worker process**. Jobs, rate limits and the daily budget live in memory, so a restart (or a free instance going to sleep) loses running jobs and resets the counters. The page shows "plan again" when its job is gone.

## Cost and abuse protection

The deployment is public, so spending is bounded in code:

- Per-address and daily plan limits answer `429` with `Retry-After`.
- A daily token budget switches the agent off in favour of the rule-based planner; one plan may use at most 60,000 tokens.
- With no free time to fill, neither Places nor Claude is called.
- Every agent run writes a `cost` log line (tokens, searches, and dollars if the `ANTHROPIC_PRICE_*` prices are set).

Also set a monthly budget and alerts at each provider. Google Maps Platform quotas are often fixed and cannot be lowered, so a budget alert is the practical guard there, and prepaid Anthropic credit without auto-reload is a hard ceiling.

Recent production runs (2 model rounds, 2 searches) used roughly 7,000 to 8,000 tokens per plan. Treat figures like that as illustrative: they depend on the model, the settings and the trip, and prices change. Check each provider's pricing page.

## Logs and troubleshooting

Every line produced while planning carries the job id: `... agent [FbG5p04UQ4milMXU] round=2 ...`. Search the logs for that id to follow one plan from start to finish: each model round (time, tokens, which tools it called), the search funnel (`google=20 quality_ok=17 near_route=17`, `detour check places=17 shown=12 hidden=2 capped=3`), routing calls with timings, the validator outcome, the final stops and the cost line. Access logs have coordinates and search text removed.

| Symptom | Likely cause |
|---|---|
| Plan fails with "The routing service is not responding" | OpenRouteService timed out (10 s) or returned a gateway error; it is retried once for 502, 503 and 504. When it is down, plans fail on purpose instead of guessing times |
| "The routing service has reached its usage limit" | OpenRouteService daily or per-minute quota |
| Result says "basic plan" | The agent failed; the reason is in the response (`degraded_reason`) and in the log |
| `429` from `/api/plans` | Per-address or daily plan limit |

## Notes and limits

- Driving only, starting now. Times come from OpenRouteService and have no live traffic, hence the safety margin.
- Google Places content is never stored beyond `place_id` (policy), and results show Google attribution. Opening hours can change, so the app asks users to check before they go.
- Map tiles are from OpenStreetMap, shown with attribution.
- Not yet built: round trips (start and end at the same place), time-of-day preferences (a 24-hour park can be suggested at night), place photos, swapping one stop, a Hebrew interface, traffic-aware times, and storage that survives restarts.
