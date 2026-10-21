# Frontend (React 18 + TypeScript + Vite 5)

Strict TypeScript, no UI library. Leaflet for the map (OpenStreetMap tiles). Stay on Vite 5 (the development Node version is 21). The built app is served by the FastAPI server.

```powershell
npm run typecheck   # tsc --noEmit
npm test            # vitest, node environment: pure logic only, no DOM
npm run build       # typecheck + vite build into dist/ (git-ignored)
npm run dev         # :5173, proxies /api to :8000
```

## Structure

- `src/App.tsx`: all state and the plan flow. "Plan my trip" calls `api.route` and `api.startPlan` in parallel and then polls the job (`lib/polling.ts`). A `currentRun` ref ignores answers from a run that was replaced or abandoned.
- `src/api.ts`: typed fetch. Errors are `ApiError` with the server's `{error}` message and the status. `startPlan` sends a fresh `Idempotency-Key` per click.
- `src/types.ts`: mirrors the server's pydantic models in `server/main.py`. Change both together.
- `src/components/`: `PlaceField` + `Autocomplete` (controlled, Google session tokens, "my location"), `ArrivalTimePicker` (chips + a button that opens a dialog with `WheelColumn` drums for day, hour and minute; today and the next six days, five-minute steps, a time in the past snaps forward), `TripMap` (Leaflet), `TripSheet` (phone carousel), `ResultPanel` + `Timeline` (desktop), `Notices`, `Steps`.
- `src/lib/`: pure, tested helpers (`arrival`, `wheel`, `carousel`, `polling`, `format`, `budgetText`, `maps`).

## Conventions

- **Mobile first.** Under 800 px the result replaces the form: a compact trip bar, the map, and a swipeable card sheet (overview, stops, destination). The 800 px breakpoint exists twice, in `styles.css` and in `useMediaQuery("(max-width: 800px)")` in `App.tsx`; keep them equal.
- **Leaflet:** `zoomAnimation: false` and `animate: false` are deliberate (animations stalled in the test browser); call `invalidateSize()` before fitting bounds.
- **Show what the server decided, never invent it.** Times, stop reasons and the summary come from the result. Text from the server is rendered as text, never as HTML.
- **Handle the unhappy paths:** a job that is gone (404), a failed job (`error`), a `degraded` job (tell the user it is a basic plan), polling that fails a few times.
- No hard-coded lists of countries or places; suggestions come from the server.
- Put logic in `src/lib` with a vitest test; keep components thin.
- English UI text, sentence case, no exclamation marks.

## Checking a UI change

Types and unit tests do not show layout. Run the dev server and look at it in a phone-size viewport and a desktop one. API calls can be stubbed in the page (replace `window.fetch`) to avoid spending real quota; say when a change was only checked against stubbed data.
