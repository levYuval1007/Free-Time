import hmac
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

import adminpage
import budget
import config
import evalservice
import jobs
import jobtrace  # noqa: F401  (tags log lines with the job id)
import limits
import ors
import places
import planning

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s [%(job)s] %(message)s")
log = logging.getLogger("server")
logging.getLogger("uvicorn.access").addFilter(limits.RedactQueryFilter())

SESSION_PATTERN = r"^[A-Za-z0-9_-]{1,36}$"
PLACE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,300}$"
IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"

store = jobs.JobStore()
runner = jobs.JobRunner(store)

app = FastAPI(title="Leeway API")


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
    why: str | None = None


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
    source: Literal["agent", "baseline"] | None = None
    summary: str | None = None


class PlanJobRequest(BaseModel):
    from_lon: float = Field(ge=-180, le=180)
    from_lat: float = Field(ge=-90, le=90)
    to_lon: float = Field(ge=-180, le=180)
    to_lat: float = Field(ge=-90, le=90)
    arrive_by: str = Field(min_length=1, max_length=64)
    preferences: str = Field(default="", max_length=500)
    from_label: str = Field(default="the start", max_length=200)
    to_label: str = Field(default="the destination", max_length=200)


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "degraded", "failed"]
    stage: str | None = None
    result: PlanResponse | None = None
    error: str | None = None
    degraded_reason: str | None = None


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
    request = planning.PlanRequest(origin=(from_lon, from_lat), destination=(to_lon, to_lat), arrive_by=arrive, radius=radius)
    deps = planning.Deps()
    now = datetime.now(timezone.utc)
    _, free_time, _ = planning.compute_free_time(request, now, deps)
    if free_time["status"] != "ok":
        reason = "impossible" if free_time["status"] == "impossible" else "not_enough_time"
        return {"budget": free_time, "stops": [], "reason": reason}
    return planning.baseline_plan(request, free_time, now, deps)


def _job_view(job: jobs.Job):
    return {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "result": job.result,
        "error": job.error,
        "degraded_reason": job.degraded_reason,
    }


@app.post("/api/plans", response_model=JobResponse, response_model_exclude_none=True, status_code=202)
def create_plan_job(request: Request, body: PlanJobRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    """Start a planning run (the agent, with the rule-based planner as fallback) and poll GET /api/plans/{job_id}."""
    if idempotency_key is not None and not re.fullmatch(IDEMPOTENCY_PATTERN, idempotency_key):
        raise HTTPException(400, "Idempotency-Key must be 8 to 64 letters, digits, dashes or underscores")
    try:
        arrive = budget.parse_arrive_by(body.arrive_by)
    except ValueError:
        raise HTTPException(400, "arrive_by must be an ISO 8601 time with a timezone offset")
    fingerprint = json.dumps(body.model_dump(), sort_keys=True)
    client_ip = request.client.host if request.client else "unknown"
    replay = idempotency_key is not None and store.has_key(idempotency_key)
    if not replay:
        refused = limits.guard.check_new_plan(client_ip)
        if refused:
            message, retry_after = refused
            return JSONResponse(status_code=429, content={"error": message}, headers={"Retry-After": str(retry_after)})
    try:
        job, created = store.create(fingerprint, idempotency_key)
    except jobs.Busy as err:
        return JSONResponse(status_code=503, content={"error": str(err)}, headers={"Retry-After": "10"})
    except jobs.KeyConflict as err:
        raise HTTPException(409, str(err))
    if created:
        limits.guard.count_plan(client_ip)
        plan_request = planning.PlanRequest(
            origin=(body.from_lon, body.from_lat),
            destination=(body.to_lon, body.to_lat),
            arrive_by=arrive,
            preferences=body.preferences,
            origin_label=body.from_label,
            destination_label=body.to_label,
        )
        runner.submit(job.id, lambda progress: planning.execute_plan(plan_request, progress))
    return JSONResponse(status_code=202 if created else 200, content=JobResponse(**_job_view(job)).model_dump(exclude_none=True))


@app.get("/api/plans/{job_id}", response_model=JobResponse, response_model_exclude_none=True)
def get_plan_job(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "This plan is no longer available. Please plan again.")
    return _job_view(job)


# ---- Admin: run the AI-vs-planner comparison on this server (it spends real money) ----

class EvalStartRequest(BaseModel):
    max_usd: float = Field(default=0.30, ge=0.05, le=1.0)
    only: str | None = Field(default=None, max_length=40)


def _require_admin(authorization: str | None):
    """The admin endpoints exist only when ADMIN_TOKEN is set, and need it as a bearer token."""
    token = config.get("ADMIN_TOKEN")
    if not token:
        raise HTTPException(404, "Not found")
    supplied = authorization[len("Bearer "):] if authorization and authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(401, "Unauthorized")


@app.get("/admin/evals", include_in_schema=False)
def admin_evals_page():
    """The page itself holds nothing secret, but like the endpoints it does not exist unless ADMIN_TOKEN is set."""
    if not config.get("ADMIN_TOKEN"):
        raise HTTPException(404, "Not found")
    return HTMLResponse(adminpage.HTML, headers=adminpage.SECURITY_HEADERS)


@app.post("/api/admin/evals", status_code=202)
def start_eval(body: EvalStartRequest, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    try:
        run_id = evalservice.runner.start(body.max_usd, body.only)
    except evalservice.Busy as err:
        raise HTTPException(409, str(err))
    return {"id": run_id, "status": "running"}


@app.get("/api/admin/evals")
def list_evals(authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    return {"runs": evalservice.runner.recent(), "storage": evalservice.runner.storage_kind}


@app.get("/api/admin/storage")
def eval_storage(authorization: str | None = Header(default=None)):
    """Whether the place where reports are saved works (a database round trip when one is configured)."""
    _require_admin(authorization)
    return evalservice.runner.storage_check()


@app.get("/api/admin/evals/{run_id}")
def get_eval(run_id: str, format: Literal["json", "md"] = "json", authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    view = evalservice.runner.view(run_id)
    if view is None:
        raise HTTPException(404, "No such comparison (it may be from before a restart; the log has finished reports)")
    if format == "md":
        text = evalservice.runner.markdown(run_id)
        if text is None:
            raise HTTPException(409, f"The comparison is {view['status']}: {view['progress']}")
        return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")
    return view


CLIENT_DIST = Path(__file__).resolve().parent.parent / "client" / "dist"
if CLIENT_DIST.is_dir():
    app.mount("/", StaticFiles(directory=CLIENT_DIST, html=True), name="client")
