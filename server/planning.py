"""Plans one trip end to end: free-time budget, the agent, and the rule-based planner as its fallback."""

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import agent
import agent_tools
import budget
import config
import limits
import ors
import places
import planner
import validator

log = logging.getLogger("planning")

JOB_BUDGET_S = 75  # no new model request starts after this
STAGE_TEXT = {
    "search_places": "Searching for places",
    "get_travel_time": "Checking drive times",
    "submit_itinerary": "Checking the plan",
}


@dataclass
class PlanRequest:
    origin: tuple  # (lon, lat)
    destination: tuple
    arrive_by: datetime
    preferences: str = ""
    origin_label: str = "the start"
    destination_label: str = "the destination"
    radius: int = 3000


@dataclass
class Deps:
    search_nearby: Callable = places.search_nearby
    travel_matrix: Callable = ors.matrix
    route_through: Callable = ors.route_through
    make_client: Callable = agent.make_client
    agent_enabled: Callable = lambda: bool(config.get("ANTHROPIC_API_KEY"))
    # False once the day's token budget is spent; plans then use the rule-based planner.
    budget_ok: Callable = limits.guard.agent_allowed
    record_usage: Callable = limits.guard.record_usage


@dataclass
class PlanOutcome:
    status: str  # "succeeded" or "degraded"
    result: dict
    degraded_reason: str | None = None


def _format_plan(free_time, chosen, now, considered, request: PlanRequest, deps: Deps, source, summary=None):
    stops = []
    for stop in chosen["stops"]:
        place = stop["place"]
        formatted = {
            **{key: place.get(key) for key in ("id", "name", "lat", "lon", "primary_type", "rating", "rating_count", "maps_uri", "weekday_text")},
            "drive_minutes": round(stop["drive_minutes"], 1),
            "arrive": stop["arrive"].isoformat(),
            "leave": stop["leave"].isoformat(),
            "visit_minutes": stop["visit_minutes"],
        }
        if stop.get("why"):
            formatted["why"] = stop["why"]
        stops.append(formatted)
    route = deps.route_through([request.origin, *[(s["lon"], s["lat"]) for s in stops], request.destination])
    result = {
        "budget": free_time,
        "stops": stops,
        "depart": now.isoformat(),
        "arrive_destination": chosen["arrive_destination"].isoformat(),
        "final_drive_minutes": round(chosen["final_drive_minutes"], 1),
        "geometry": route["geometry"],
        "steps": route["steps"],
        "candidates_considered": considered,
        "source": source,
    }
    if summary:
        result["summary"] = summary
    return result


def baseline_plan(request: PlanRequest, free_time, now, deps: Deps, known_places=None):
    """The rule-based planner. known_places, when given, replaces a new places search."""
    if known_places:
        found = list(known_places.values())
    else:
        def search(center):
            try:
                return deps.search_nearby(center[1], center[0], request.radius)
            except places.PlacesError as err:
                log.warning("Nearby search failed: %s", err)
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            searched = list(pool.map(search, [request.origin, request.destination]))
        if all(result is None for result in searched):
            raise places.PlacesError("Could not search for places right now", transient=True)
        found = [p for result in searched if result for p in result]

    candidates = planner.select_candidates(found)
    if not candidates:
        return {"budget": free_time, "stops": [], "reason": "no_candidates", "source": "baseline"}
    grid = deps.travel_matrix([request.origin, request.destination, *[(c["lon"], c["lat"]) for c in candidates]])
    chosen = planner.plan_stops(candidates, grid, now, request.arrive_by, free_time["buffer_minutes"])
    if chosen is None:
        return {
            "budget": free_time, "stops": [], "reason": "no_feasible_plan",
            "candidates_considered": len(candidates), "source": "baseline",
        }
    return _format_plan(free_time, chosen, now, len(candidates), request, deps, "baseline")


def compute_free_time(request: PlanRequest, now, deps: Deps):
    direct = deps.travel_matrix([request.origin, request.destination])[0][1]
    if direct is None:
        raise ors.RouteError("There is no driving route between these places")
    direct_minutes = math.ceil(direct)
    return direct_minutes, budget.plan_budget(request.arrive_by, now, direct_minutes)


def execute_plan(request: PlanRequest, progress: Callable = lambda text: None, now=None, deps: Deps | None = None) -> PlanOutcome:
    """Try the agent; if it is unavailable or its plan fails validation, fall back to the rule-based planner."""
    deps = deps or Deps()
    now = now or datetime.now(timezone.utc)
    progress("Checking your route")
    direct_minutes, free_time = compute_free_time(request, now, deps)
    if free_time["status"] != "ok":
        reason = "impossible" if free_time["status"] == "impossible" else "not_enough_time"
        return PlanOutcome("succeeded", {"budget": free_time, "stops": [], "reason": reason, "source": "baseline"})

    if not deps.agent_enabled():
        return PlanOutcome("succeeded", baseline_plan(request, free_time, now, deps))

    if not deps.budget_ok():
        log.warning("daily agent token budget is used up; using the rule-based planner")
        return PlanOutcome("degraded", baseline_plan(request, free_time, now, deps), "daily_budget")

    ctx = validator.TripContext(
        now=now, arrive_by=request.arrive_by, buffer_minutes=free_time["buffer_minutes"],
        origin=request.origin, destination=request.destination,
    )
    box = agent_tools.ToolBox(ctx, deps.search_nearby, deps.travel_matrix)
    message = agent.build_user_message(
        ctx, free_time, direct_minutes, request.preferences, request.origin_label, request.destination_label
    )
    progress("Choosing places")
    try:
        client = deps.make_client()
    except Exception as err:  # a missing or broken key must degrade the plan, not fail it
        log.warning("Could not create the Claude client: %s", err)
        outcome = agent.AgentOutcome(status="failed", reason="llm_unavailable")
    else:
        outcome = agent.run_agent(
            client, box, message,
            on_progress=lambda tool: progress(STAGE_TEXT.get(tool, "Planning")),
            deadline=time.monotonic() + JOB_BUDGET_S,
        )

    deps.record_usage(outcome.usage)
    log.info(limits.cost_line(outcome.usage, outcome.searches, outcome.rounds))
    if outcome.status == "ok":
        result = _format_plan(
            free_time, outcome.itinerary, now, len(outcome.known_places), request, deps, "agent",
            summary=outcome.itinerary.get("summary"),
        )
        return PlanOutcome("succeeded", result)

    progress("Using the basic planner")
    log.info("agent failed (%s); using the rule-based planner", outcome.reason)
    return PlanOutcome("degraded", baseline_plan(request, free_time, now, deps, outcome.known_places), outcome.reason)
