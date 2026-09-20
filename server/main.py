import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

import budget
import ors
import places
import planner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("server")

SESSION_PATTERN = r"^[A-Za-z0-9_-]{1,36}$"
PLACE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,300}$"

app = FastAPI(title="freeTime API")


class Suggestion(BaseModel):
    label: str
    place_id: str | None = None
    lon: float | None = None
    lat: float | None = None


class SuggestResponse(BaseModel):
    provider: Literal["google", "ors"]
    suggestions: list[Suggestion]


class ResolvedPlace(BaseModel):
    lat: float
    lon: float
    address: str


class RouteStep(BaseModel):
    instruction: str
    distance: float
    duration: float


class Budget(BaseModel):
    status: Literal["ok", "go_direct", "impossible"]
    drive_minutes: int
    buffer_minutes: int
    free_minutes: int


class RouteResponse(BaseModel):
    km: float
    minutes: int
    geometry: list[list[float]]
    steps: list[RouteStep]
    budget: Budget | None = None


class PlannedStop(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    primary_type: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    maps_uri: str | None = None
    weekday_text: list[str] | None = None
    drive_minutes: float
    arrive: str
    leave: str
    visit_minutes: int


class PlanResponse(BaseModel):
    budget: Budget
    stops: list[PlannedStop]
    reason: Literal["impossible", "not_enough_time", "no_candidates", "no_feasible_plan"] | None = None
    depart: str | None = None
    arrive_destination: str | None = None
    final_drive_minutes: float | None = None
    geometry: list[list[float]] | None = None
    steps: list[RouteStep] | None = None
    candidates_considered: int = 0


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    return JSONResponse(status_code=400, content={"error": f"Invalid request: {problems}"})


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(ors.RouteError)
async def route_error_handler(request: Request, exc: ors.RouteError):
    return JSONResponse(status_code=502, content={"error": str(exc)})


@app.exception_handler(places.PlacesError)
async def places_error_handler(request: Request, exc: places.PlacesError):
    return JSONResponse(status_code=502, content={"error": str(exc), "transient": exc.transient})


@app.get("/api/suggest", response_model=SuggestResponse, response_model_exclude_none=True)
def suggest(
    q: str = Query(min_length=3, max_length=200),
    session: str = Query(pattern=SESSION_PATTERN),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
):
    if (lat is None) != (lon is None):
        raise HTTPException(400, "lat and lon must be given together")
    bias = None if lat is None else (lat, lon)
    try:
        return {"provider": "google", "suggestions": places.autocomplete(q, session, bias)}
    except places.PlacesError as err:
        log.warning("Google autocomplete failed, falling back to ORS: %s", err)
        return {"provider": "ors", "suggestions": ors.suggest(q, bias)}


@app.get("/api/places/resolve", response_model=ResolvedPlace)
def resolve_place(
    place_id: str = Query(pattern=PLACE_ID_PATTERN),
    session: str = Query(pattern=SESSION_PATTERN),
):
    return places.place_location(place_id, session)


@app.get("/api/route", response_model=RouteResponse, response_model_exclude_none=True)
def route(
    from_lon: float = Query(ge=-180, le=180),
    from_lat: float = Query(ge=-90, le=90),
    to_lon: float = Query(ge=-180, le=180),
    to_lat: float = Query(ge=-90, le=90),
    arrive_by: str | None = None,
):
    arrive = None
    if arrive_by:
        try:
            arrive = budget.parse_arrive_by(arrive_by)
        except ValueError:
            raise HTTPException(400, "arrive_by must be an ISO 8601 time with a timezone offset")
    result = ors.route_coords(from_lon, from_lat, to_lon, to_lat)
    if arrive:
        result["budget"] = budget.plan_budget(arrive, datetime.now(timezone.utc), result["minutes"])
    return result


@app.get("/api/plan", response_model=PlanResponse, response_model_exclude_none=True)
def plan(
    from_lon: float = Query(ge=-180, le=180),
    from_lat: float = Query(ge=-90, le=90),
    to_lon: float = Query(ge=-180, le=180),
    to_lat: float = Query(ge=-90, le=90),
    arrive_by: str = Query(min_length=1),
    radius: int = Query(default=3000, ge=500, le=5000),
):
    try:
        arrive = budget.parse_arrive_by(arrive_by)
    except ValueError:
        raise HTTPException(400, "arrive_by must be an ISO 8601 time with a timezone offset")
    now = datetime.now(timezone.utc)
    origin = (from_lon, from_lat)
    destination = (to_lon, to_lat)

    direct = ors.matrix([origin, destination])[0][1]
    if direct is None:
        raise HTTPException(400, "There is no driving route between these places")
    free_time = budget.plan_budget(arrive, now, math.ceil(direct))
    if free_time["status"] != "ok":
        reason = "impossible" if free_time["status"] == "impossible" else "not_enough_time"
        return {"budget": free_time, "stops": [], "reason": reason}

    def search(center):
        try:
            return places.search_nearby(center[1], center[0], radius)
        except places.PlacesError as err:
            log.warning("Nearby search failed: %s", err)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        found = list(pool.map(search, [origin, destination]))
    if all(result is None for result in found):
        raise places.PlacesError("Could not search for places right now", transient=True)
    candidates = planner.select_candidates([p for result in found if result for p in result])
    if not candidates:
        return {"budget": free_time, "stops": [], "reason": "no_candidates"}

    grid = ors.matrix([origin, destination, *[(c["lon"], c["lat"]) for c in candidates]])
    chosen = planner.plan_stops(candidates, grid, now, arrive, free_time["buffer_minutes"])
    if chosen is None:
        return {"budget": free_time, "stops": [], "reason": "no_feasible_plan", "candidates_considered": len(candidates)}

    stops = [
        {
            **{key: stop["place"].get(key) for key in ("id", "name", "lat", "lon", "primary_type", "rating", "rating_count", "maps_uri", "weekday_text")},
            "drive_minutes": round(stop["drive_minutes"], 1),
            "arrive": stop["arrive"].isoformat(),
            "leave": stop["leave"].isoformat(),
            "visit_minutes": stop["visit_minutes"],
        }
        for stop in chosen["stops"]
    ]
    route = ors.route_through([origin, *[(s["lon"], s["lat"]) for s in stops], destination])
    return {
        "budget": free_time,
        "stops": stops,
        "depart": now.isoformat(),
        "arrive_destination": chosen["arrive_destination"].isoformat(),
        "final_drive_minutes": round(chosen["final_drive_minutes"], 1),
        "geometry": route["geometry"],
        "steps": route["steps"],
        "candidates_considered": len(candidates),
    }


CLIENT_DIST = Path(__file__).resolve().parent.parent / "client" / "dist"
if CLIENT_DIST.is_dir():
    app.mount("/", StaticFiles(directory=CLIENT_DIST, html=True), name="client")
