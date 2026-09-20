import logging
import re
import time
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
import countries
import ors
import places

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("server")

COUNTRY_PATTERN = r"^[A-Za-z]{2}$"
SESSION_PATTERN = r"^[A-Za-z0-9_-]{1,36}$"
PLACE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,300}$"
PLACE_TYPE_RE = re.compile(r"[a-z_]{1,40}")

app = FastAPI(title="freeTime API")


class Country(BaseModel):
    code: str
    name: str


class CountriesResponse(BaseModel):
    countries: list[Country]


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


class Place(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    types: list[str]
    primary_type: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    price_level: str | None = None
    business_status: str | None = None
    periods: list[dict] | None = None
    weekday_text: list[str] | None = None
    utc_offset_minutes: int | None = None
    maps_uri: str | None = None


class PlacesStats(BaseModel):
    requests: int
    errors: int
    estimated_cost_usd: float


class NearbyResponse(BaseModel):
    places: list[Place]
    latency_ms: int
    stats: PlacesStats


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


@app.exception_handler(countries.CountriesError)
async def countries_error_handler(request: Request, exc: countries.CountriesError):
    return JSONResponse(status_code=502, content={"error": str(exc)})


@app.get("/api/countries", response_model=CountriesResponse)
def get_countries():
    return {"countries": countries.load_countries()}


@app.get("/api/suggest", response_model=SuggestResponse, response_model_exclude_none=True)
def suggest(
    country: str = Query(pattern=COUNTRY_PATTERN),
    q: str = Query(min_length=3, max_length=200),
    session: str = Query(pattern=SESSION_PATTERN),
):
    try:
        return {"provider": "google", "suggestions": places.autocomplete(q, country, session)}
    except places.PlacesError as err:
        log.warning("Google autocomplete failed, falling back to ORS: %s", err)
        return {"provider": "ors", "suggestions": ors.suggest(q, country)}


@app.get("/api/places/resolve", response_model=ResolvedPlace)
def resolve_place(
    place_id: str = Query(pattern=PLACE_ID_PATTERN),
    session: str = Query(pattern=SESSION_PATTERN),
):
    return places.place_location(place_id, session)


@app.get("/api/places/nearby", response_model=NearbyResponse)
def nearby_places(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius: int = Query(default=3000, ge=1, le=places.MAX_RADIUS_M),
    types: str | None = None,
):
    type_list = [t for t in (types or "").split(",") if t] or None
    if type_list and (len(type_list) > 10 or not all(PLACE_TYPE_RE.fullmatch(t) for t in type_list)):
        raise HTTPException(400, "types must be up to 10 comma-separated place type names")
    started = time.perf_counter()
    found = places.search_nearby(lat, lon, radius, type_list)
    return {
        "places": found,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "stats": places.stats(),
    }


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


CLIENT_DIST = Path(__file__).resolve().parent.parent / "client" / "dist"
if CLIENT_DIST.is_dir():
    app.mount("/", StaticFiles(directory=CLIENT_DIST, html=True), name="client")
