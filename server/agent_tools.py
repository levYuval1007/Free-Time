"""The tools the planning agent can call, and the code that runs them.

Each tool takes the model's arguments (untrusted) and returns (text, is_error). Errors are returned as text
so the model can read them and correct itself; nothing here raises for bad model input.
"""

import json
import math
from datetime import timedelta

import planner
import places
import validator

MAX_SEARCHES = 3
MAX_TRAVEL_CALLS = 6
MAX_SUBMISSIONS = 3
MAX_RESULTS = 20
MIN_RADIUS_M = 300
MAX_RADIUS_M = 5000
MAX_SEARCH_DISTANCE_KM = 15  # a search centre must be close to the start or the destination
MAX_TRAVEL_NODES = 8
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


def _distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text(value, limit):
    return " ".join(str(value).split())[:limit] if isinstance(value, str) else ""


class ToolBox:
    """Runs the tools for one planning run and remembers what the run found."""

    def __init__(self, ctx: validator.TripContext, search_nearby, travel_matrix):
        self.ctx = ctx
        self._search_nearby = search_nearby
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
            "get_travel_time": self._get_travel_time,
            "submit_itinerary": self._submit_itinerary,
        }.get(name)
        if handler is None:
            return f"Unknown tool {name}", True
        if not isinstance(arguments, dict):
            return "Tool arguments must be an object", True
        try:
            return handler(arguments)
        except places.PlacesError as err:
            return f"The places service failed: {err}", True

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
            _distance_km(lat, lon, point[1], point[0]) for point in (self.ctx.origin, self.ctx.destination)
        )
        if near > MAX_SEARCH_DISTANCE_KM:
            return f"Search near the origin or the destination (within {MAX_SEARCH_DISTANCE_KM} km)", True
        if self.searches >= MAX_SEARCHES:
            return f"The search limit ({MAX_SEARCHES}) is used up. Work with the places you already have.", True
        self.searches += 1

        found = planner.select_candidates(self._search_nearby(lat, lon, int(radius), types))
        found = found[:MAX_RESULTS]
        for place in found:
            self.ctx.known_places[place["id"]] = place
        return json.dumps([self._describe(place) for place in found]), False

    def _describe(self, place):
        weekday = self._local_weekday(place)
        hours_text = place.get("weekday_text")
        return {
            "id": place["id"],
            "name": place["name"],
            "type": (place.get("primary_type") or "place").replace("_", " "),
            "rating": place["rating"],
            "rating_count": place["rating_count"],
            "lat": place["lat"],
            "lon": place["lon"],
            "hours_today": hours_text[weekday] if hours_text and len(hours_text) == 7 else None,
            "typical_visit_minutes": planner.visit_minutes(place),
        }

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
        return json.dumps({"minutes": minutes}), False

    def _submit_itinerary(self, args):
        if self.itinerary is not None:
            return "An itinerary was already accepted.", True
        if self.submissions >= MAX_SUBMISSIONS:
            return "No submissions left.", True
        self.submissions += 1
        stops = args.get("stops")
        result, errors = validator.validate_itinerary(self.ctx, stops, self._travel_matrix)
        if errors:
            left = MAX_SUBMISSIONS - self.submissions
            tail = f" You can submit {left} more time(s)." if left else " No submissions left."
            return "Rejected:\n- " + "\n- ".join(errors) + tail, True
        for stop, proposed in zip(result["stops"], stops):
            stop["why"] = _text(proposed.get("why"), 200)
        result["summary"] = _text(args.get("summary"), 300)
        self.itinerary = result
        return "Itinerary accepted.", False
