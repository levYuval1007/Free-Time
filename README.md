# freeTime / travel-time

Pick a country, choose two places (Google autocomplete, falls back to OpenRouteService), and get the driving distance and time. Optionally add an arrival time to see how much free time you have, view the route on a map, and find places near the destination.

```
server/   FastAPI backend (Python)      client/   React + TypeScript UI (Vite)
```

## Setup

**API keys** (never commit them):

| Variable | Used for |
|---|---|
| `GOOGLE_MAPS_API_KEY` | Google Places (autocomplete, place details, nearby search) |
| `ORS_API_KEY` | OpenRouteService routing (free key from openrouteservice.org) |

Put them in `server/.env` (copy `server/.env.example`; the file is git-ignored), or set environment variables. Environment variables take priority over `.env`. In PowerShell, for the current window only:

```powershell
$env:GOOGLE_MAPS_API_KEY = "your-key"
```

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
