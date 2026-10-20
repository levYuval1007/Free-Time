# Leeway

A web app: the user enters a start, a destination and an arrival time; the app computes the free time after the direct drive and an AI agent (Claude, with tools) proposes up to three stops that fit. Python + FastAPI backend in `server/`, React + TypeScript (Vite 5) frontend in `client/`. Deployed as one web service on Render (the server also serves the built client). Read `README.md` for the design; this file is what to know before changing things.

## Commands

```powershell
# server tests (offline, ~2 s)
cd server; .venv\Scripts\python.exe -m unittest discover -s tests
# client
cd client; npm run typecheck; npm test; npm run build
# run locally: uvicorn on :8000 and `npm run dev` on :5173 (Vite proxies /api)
cd server; .venv\Scripts\python.exe -m uvicorn main:app --port 8000 --reload
```

Use the venv Python (`server/.venv`). A bare `python` in this shell may be a Windows Store stub that prints nothing useful.

## Principles that must keep holding

1. **The model proposes, the code decides.** Nothing the model says is trusted: every itinerary goes through `server/validator.py`, which computes all times from real driving times. Never let a model-written number or time reach the user unchecked.
2. **There is always a fallback.** Agent failure, refusal, timeout or budget exhaustion degrades to the rule-based planner (`status: degraded`). An unavailable routing service fails fast on purpose (the owner chose this over a second provider).
3. **Bounded cost.** Searches, rounds, tokens and plans per address/day are capped (`server/limits.py`, `agent.py`, `agent_tools.py`). Do not add a paid call without thinking about its cap.
4. **Privacy.** No coordinates or user-written text in logs (access logs are redacted). Google Places content may only be stored as `place_id`.
5. **Secrets only in environment variables** or the git-ignored `server/.env`.

## Working agreements with the owner

- **Do not commit or push unless asked.** Each change ends with a short report and the question; commit when told to. If git has no identity configured, pass it per command with `git -c user.name=... -c user.email=...` and never edit git config.
- **Never type, print or request API keys.** The owner sets them in Render or `server/.env`. Do not probe the machine for credentials.
- **Do not run anything that spends money without explicit approval:** real Claude, Google or OpenRouteService calls, `server/evals/run_evals.py`, and the `/api/admin/evals` endpoints.
- **Verify before claiming.** Unit tests use fakes, so say plainly when something was not tried against the real services. When quoting prices, quotas or limits of a provider, check the provider's current docs.
- **The owner writes in Hebrew.** Reply in Hebrew; keep code, comments, commit messages and docs in English.
- Add or update tests with every change. Keep `README.md`, `server/.env.example` and the settings table in sync when adding an environment variable.
- Prefer small, reviewable changes; explain trade-offs and wait for the owner's decision when a choice affects product behaviour, cost or reliability.

## Where things are

- `server/CLAUDE.md`: backend modules, request flow, conventions, checklists.
- `server/tests/CLAUDE.md`: test helpers and gotchas.
- `server/evals/CLAUDE.md`: the paid evals.
- `client/CLAUDE.md`: frontend structure and conventions.
