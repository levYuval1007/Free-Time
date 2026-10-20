# Leeway

Enter where you are, where you need to be, and when. Leeway shows the route and, when there is free time before the deadline, suggests up to three places to visit on the way (Google Places), scheduled around opening hours and driving times. Places are chosen with Google autocomplete (falling back to OpenRouteService), the layout is mobile-first (map on top with the plan below; side by side on desktop), and "Open in Google Maps" hands the plan to navigation.

```
server/   FastAPI backend (Python)      client/   React + TypeScript UI (Vite)
```

## Setup

**API keys** (never commit them):

| Variable | Used for |
|---|---|
| `GOOGLE_MAPS_API_KEY` | Google Places (autocomplete, place details, nearby search) |
| `ANTHROPIC_API_KEY` | The planning agent (Claude) |
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

**Single process** (FastAPI serves the built client; restart the server after building). Open http://127.0.0.1:8000:

```powershell
cd client
npm run build
```

API docs are at http://127.0.0.1:8000/docs.

## Test

```powershell
cd server
.venv\Scripts\python.exe -m unittest discover -s tests
```

```powershell
cd client
npm test
```

## Notes

- Google Places data may only be stored as `place_id`; the app never caches other Places content.
- Times use the driving estimate from OpenRouteService (no live traffic).
