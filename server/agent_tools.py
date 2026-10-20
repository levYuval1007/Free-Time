"""The tools the planning agent can call, and the code that runs them.

Each tool takes the model's arguments (untrusted) and returns (text, is_error). Errors are returned as text
so the model can read them and correct itself; nothing here raises for bad model input.
"""

import json
import logging
import time
from datetime import timedelta

import geo
import ors
import planner
import places
import validator

log = logging.getLogger("tools")

MAX_SEARCHES = 3
MAX_TRAVEL_CALLS = 4
MAX_SUBMISSIONS = 3
MAX_RESULTS = 20  # places checked for detour per search
MAX_SHOWN = 12  # places shown to the model per search, best quality first
MIN_RADIUS_M = 300
MAX_RADIUS_M = 5000
MAX_SEARCH_DISTANCE_KM = 15  # a search centre must be close to the start or the destination
MAX_TRAVEL_NODES = 8
MAX_ROUTE_DISTANCE_KM = 15  # places farther than this from the route are dropped; the validator checks the real detour
MAX_POLYLINE_POINTS = 200  # Google does not document a size limit, so the route is kept short
MAX_QUERY_CHARS = 80
ALLOWED_TYPES = [
    *places.DEFAULT_TYPES,
    "cafe",
    "restaurant",
    "bakery",
    "zoo",
    "aquarium",
    "amusement_park",
    "playground",
    "library",
]

TOOLS = [
    {
        "name": "search_places",
        "description": (
            "Find places to visit near a point. Returns up to 20 open, well-rated places with id, name, "
            "type, rating, coordinates and today's opening hours. Only places returned here can be used in "
            "the itinerary. Search near the start or the destination."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "radius_m": {"type": "integer", "minimum": MIN_RADIUS_M, "maximum": MAX_RADIUS_M},
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ALLOWED_TYPES},
                    "description": "Place types to include. Omit for parks, museums and attractions.",
                },
            },
            "required": ["lat", "lon", "radius_m"],
        },
    },
    {
        "name": "search_along_route",
        "description": (
            "Find places that match a free-text query anywhere along the direct driving route from the start to the "
            "destination, for example 'park', 'scenic viewpoint', 'bakery' or 'waterfall'. Use it when the best "
            "stops may be in the middle of the trip and not near either end. Returns up to 20 places with id, name, "
            "type, rating, coordinates, today's opening hours and km_from_route (straight-line distance from the "
            "road), detour_minutes (extra driving compared with going straight) and minutes_from_start. Only places returned by a search can be used in the itinerary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, in a few words."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_travel_time",
        "description": (
            "Driving minutes between 2 to 8 nodes. A node is 'origin', 'destination' or a place id returned "
            "by search_places. Returns a matrix: minutes[from][to]."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"nodes": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": MAX_TRAVEL_NODES}},
            "required": ["nodes"],
        },
    },
    {
        "name": "submit_itinerary",
        "description": (
            "Submit the final plan: the stops in visiting order. Give each stop a place_id, how many minutes "
            "to stay (optional) and a short reason. The server computes all times and checks opening hours and "
            "the deadline; if it finds problems it returns them and you must fix and submit again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "stops": {
                    "type": "array",
                    "maxItems": planner.MAX_STOPS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "place_id": {"type": "string"},
                            "visit_minutes": {"type": "integer"},
                            "why": {"type": "string"},
                        },
                        "required": ["place_id"],
                    },
                },
                "summary": {"type": "string", "description": "One or two sentences for the traveller."},
            },
            "required": ["stops", "summary"],
        },
    },
]


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def describe_call(name, args):
    """A one-line summary of a tool call for the logs. It leaves out coordinates and free text from the user."""
    if not isinstance(args, dict):
        return str(name)
    if name == "search_along_route":
        return f"search_along_route(query={_text(args.get('query'), MAX_QUERY_CHARS)!r})"
    if name == "search_places":
        return f"search_places(radius_m={args.get('radius_m')}, types={args.get('types')})"
    if name == "get_travel_time":
        nodes = args.get("nodes")
        return f"get_travel_time(nodes={len(nodes) if isinstance(nodes, list) else '?'})"
    if name == "submit_itinerary":
        stops = args.get("stops")
        return f"submit_itinerary(stops={len(stops) if isinstance(stops, list) else '?'})"
    return str(name)


def _text(value, limit):
    return " ".join(str(value).split())[:limit] if isinstance(value, str) else ""


class ToolBox:
    """Runs the tools for one planning run and remembers what the run found."""

    def __init__(self, ctx: validator.TripContext, search_nearby, travel_matrix, search_along_route=None):
        self.ctx = ctx
        self._search_nearby = search_nearby
        self._search_along_route = search_along_route
        self._polyline = None
        self._travel_matrix = travel_matrix
        self.searches = 0
        self.travel_calls = 0
        self.submissions = 0
        self.itinerary = None  # set once a submission passes validation

    @property
    def finished(self):
        return self.itinerary is not None or self.submissions >= MAX_SUBMISSIONS

    def run(self, name, arguments):
        handler = {
            "search_places": self._search_places,
            "search_along_route": self._search_along_route_tool,
            "get_travel_time": self._get_travel_time,
            "submit_itinerary": self._submit_itinerary,
        }.get(name)
        if handler is None:
            return f"Unknown tool {name}", True
        if not isinstance(arguments, dict):
            return "Tool arguments must be an object", True
        started = time.perf_counter()
        try:
            text, is_error = handler(arguments)
        except places.PlacesError as err:
            text, is_error = f"The places service failed: {err}", True
        except ors.RouteError as err:
            text, is_error = f"The routing service failed: {err}", True
        log.info(
            "tool %s ok=%s ms=%d%s",
            name, not is_error, (time.perf_counter() - started) * 1000, f" error={text[:300]!r}" if is_error else "",
        )
        return text, is_error

    def _search_places(self, args):
        lat, lon, radius = args.get("lat"), args.get("lon"), args.get("radius_m")
        if not (_number(lat) and _number(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return "lat and lon must be valid coordinates", True
        if not _number(radius) or not MIN_RADIUS_M <= radius <= MAX_RADIUS_M:
            return f"radius_m must be between {MIN_RADIUS_M} and {MAX_RADIUS_M}", True
        types = args.get("types")
        if types is not None:
            if not isinstance(types, list) or not types or any(t not in ALLOWED_TYPES for t in types):
                return f"types must be a non-empty list drawn from: {', '.join(ALLOWED_TYPES)}", True
        near = min(
            geo.haversine_km(lat, lon, point[1], point[0]) for point in (self.ctx.origin, self.ctx.destination)
        )
        if near > MAX_SEARCH_DISTANCE_KM:
            return f"Search near the origin or the destination (within {MAX_SEARCH_DISTANCE_KM} km)", True
        if self.searches >= MAX_SEARCHES:
            return f"The search limit ({MAX_SEARCHES}) is used up. Work with the places you already have.", True
        self.searches += 1

        raw = self._search_nearby(lat, lon, int(radius), types)
        found = planner.select_candidates(raw)
        log.info("search_places google=%d quality_ok=%d", len(raw), len(found))
        return self._remember(found[:MAX_RESULTS]), False

    def _remember(self, found):
        """Keep what a search found so later steps can use it, and describe it for the model.

        Places that would add more than the allowed detour are not shown to the model. They stay in
        known_places, so the basic planner can still use them if the agent fails.
        """
        for place in found:
            self.ctx.known_places[place["id"]] = place
        register = getattr(self._travel_matrix, "register", None)
        if register:
            register([(place["lon"], place["lat"]) for place in found])
        timing = self._timing(found)
        passing = [place for place in found if place["id"] in timing]
        shown = passing[:MAX_SHOWN]
        log.info(
            "detour check places=%d shown=%d hidden=%d capped=%d",
            len(found), len(shown), len(found) - len(passing), len(passing) - len(shown),
        )
        # Compact JSON, with the original characters: escaping Hebrew names would cost many more tokens.
        return json.dumps(
            [self._describe(place, timing[place["id"]]) for place in shown], ensure_ascii=False, separators=(",", ":")
        )

    def _timing(self, found):
        """Detour and drive time for each place, from one routing request that also answers later questions.

        detour is the extra driving compared with going straight to the destination.
        """
        if not found:
            return {}
        points = [self.ctx.origin, self.ctx.destination, *[(place["lon"], place["lat"]) for place in found]]
        grid = self._travel_matrix(points)
        direct = grid[0][1]
        timing = {}
        for index, place in enumerate(found, start=2):
            out, back = grid[0][index], grid[index][1]
            if direct is None or out is None or back is None:
                continue
            detour = out + back - direct
            if detour > validator.MAX_DETOUR_MINUTES:
                continue
            timing[place["id"]] = {"detour_minutes": max(0, round(detour)), "minutes_from_start": round(out)}
        return timing

    def _search_along_route_tool(self, args):
        query = _text(args.get("query"), MAX_QUERY_CHARS)
        if len(query) < 2:
            return "query must be a few words describing what to look for", True
        if self._search_along_route is None or len(self.ctx.route) < 2:
            return "Searching along the route is not available for this trip. Use search_places.", True
        if self.searches >= MAX_SEARCHES:
            return f"The search limit ({MAX_SEARCHES}) is used up. Work with the places you already have.", True
        self.searches += 1

        if self._polyline is None:
            self._polyline = geo.encode_polyline(geo.thin(self.ctx.route, MAX_POLYLINE_POINTS))
        raw = self._search_along_route(self._polyline, query)
        found = planner.select_candidates(raw)
        near = [
            place for place in found
            if geo.distance_to_route_km(place["lat"], place["lon"], self.ctx.route) <= MAX_ROUTE_DISTANCE_KM
        ]
        log.info("search_along_route google=%d quality_ok=%d near_route=%d", len(raw), len(found), len(near))
        return self._remember(near[:MAX_RESULTS]), False

    def _describe(self, place, timing):
        weekday = self._local_weekday(place)
        hours_text = place.get("weekday_text")
        off_route = geo.distance_to_route_km(place["lat"], place["lon"], self.ctx.route)
        described = {
            "id": place["id"],
            "name": place["name"],
            "type": (place.get("primary_type") or "place").replace("_", " "),
            "rating": place["rating"],
            "rating_count": place["rating_count"],
            "hours_today": hours_text[weekday] if hours_text and len(hours_text) == 7 else None,
            "typical_visit_minutes": planner.visit_minutes(place),
            **timing,
        }
        if off_route is not None:
            described["km_from_route"] = round(off_route, 1)
        return described

    def _local_weekday(self, place):
        local = self.ctx.now + timedelta(minutes=place.get("utc_offset_minutes") or 0)
        return local.weekday()  # Google lists Monday first, like Python

    def _node_point(self, node):
        if node == "origin":
            return self.ctx.origin
        if node == "destination":
            return self.ctx.destination
        place = self.ctx.known_places.get(node) if isinstance(node, str) else None
        return (place["lon"], place["lat"]) if place else None

    def _get_travel_time(self, args):
        nodes = args.get("nodes")
        if not isinstance(nodes, list) or not 2 <= len(nodes) <= MAX_TRAVEL_NODES:
            return f"nodes must list 2 to {MAX_TRAVEL_NODES} entries", True
        if len(set(map(str, nodes))) != len(nodes):
            return "nodes must be distinct", True
        points = [self._node_point(node) for node in nodes]
        unknown = [str(node) for node, point in zip(nodes, points) if point is None]
        if unknown:
            return f"Unknown nodes: {', '.join(unknown)}. Use 'origin', 'destination' or ids from search_places.", True
        if self.travel_calls >= MAX_TRAVEL_CALLS:
            return f"The travel time limit ({MAX_TRAVEL_CALLS}) is used up.", True
        self.travel_calls += 1

        grid = self._travel_matrix(points)
        minutes = {
            str(a): {str(b): (None if grid[i][j] is None else round(grid[i][j])) for j, b in enumerate(nodes) if i != j}
            for i, a in enumerate(nodes)
        }
        return json.dumps({"minutes": minutes}, separators=(",", ":")), False

    def _submit_itinerary(self, args):
        if self.itinerary is not None:
            return "An itinerary was already accepted.", True
        if self.submissions >= MAX_SUBMISSIONS:
            return "No submissions left.", True
        self.submissions += 1
        stops = args.get("stops")
        result, errors = validator.validate_itinerary(self.ctx, stops, self._travel_matrix)
        log.info("submit stops=%s accepted=%s", len(stops) if isinstance(stops, list) else "?", not errors)
        if errors:
            left = MAX_SUBMISSIONS - self.submissions
            tail = f"You can submit {left} more time(s)." if left else "No submissions left."
            return "Rejected:\n- " + "\n- ".join(errors) + "\n" + tail, True
        for stop, proposed in zip(result["stops"], stops):
            stop["why"] = _text(proposed.get("why"), 200)
        result["summary"] = _text(args.get("summary"), 300)
        trimmed = result.pop("trimmed", [])
        self.itinerary = result
        if not trimmed:
            return "Itinerary accepted.", False
        log.info("submit trimmed=%s", trimmed)
        changes = "; ".join(f"{name}: {before} to {after} minutes" for name, before, after in trimmed)
        return f"Itinerary accepted. The server shortened visits so you arrive in time ({changes}).", False
