import json
import logging
import threading
import time
import urllib.parse

import config
from http_client import PooledClient, TransportError

API_HOST = "api.openrouteservice.org"
ROUTE_CACHE_TTL_S = 120

log = logging.getLogger("ors")


class RouteError(Exception):
    pass


class QuotaExceeded(RouteError):
    """The free OpenRouteService quota (or rate limit) is used up."""


def _key():
    key = config.get("ORS_API_KEY")
    if not key:
        raise RouteError("ORS_API_KEY is not set. Put it in server/.env or set the environment variable.")
    return key


_client = PooledClient(API_HOST)


def _call(method, path, body=None, headers=None):
    try:
        status, raw = _client.request(method, path, body, headers)
    except TransportError as err:
        raise RouteError(f"Could not reach OpenRouteService: {err}")
    if status != 200:
        detail = raw.decode(errors="replace")
        log.warning("OpenRouteService %s %s -> %s %s", method, path.split("?")[0], status, detail[:200])
        if status == 429 or (status == 403 and "quota" in detail.lower()):
            raise QuotaExceeded("The routing service has reached its usage limit. Please try again later.")
        raise RouteError(f"The routing service returned an error ({status}).")
    return json.loads(raw)


def geocode(place, country):
    query = urllib.parse.urlencode(
        {"api_key": _key(), "text": place, "size": 1, "boundary.country": country}
    )
    data = _call("GET", f"/geocode/search?{query}")
    if not data["features"]:
        raise RouteError(f"Could not find place: {place}")
    feature = data["features"][0]
    lon, lat = feature["geometry"]["coordinates"]
    return lon, lat, feature["properties"].get("label", place)


def suggest(text, bias=None):
    """Place suggestions; bias is an optional (lat, lon) that ranks nearby places first."""
    params = {"api_key": _key(), "text": text, "size": 5}
    if bias:
        params["focus.point.lat"], params["focus.point.lon"] = bias
    data = _call("GET", f"/geocode/autocomplete?{urllib.parse.urlencode(params)}")
    return [
        {"label": f["properties"].get("label", f["properties"].get("name", "")),
         "lon": f["geometry"]["coordinates"][0],
         "lat": f["geometry"]["coordinates"][1]}
        for f in data["features"]
    ]


def matrix(points):
    """Driving minutes between every pair of (lon, lat) points; None where no route exists."""
    body = json.dumps({"locations": [[lon, lat] for lon, lat in points], "metrics": ["duration"]}).encode()
    data = _call(
        "POST",
        "/v2/matrix/driving-car",
        body,
        {"Authorization": _key(), "Content-Type": "application/json"},
    )
    return [[None if seconds is None else seconds / 60 for seconds in row] for row in data["durations"]]


_route_cache = {}  # key -> (expires, result)
_route_locks = {}
_route_guard = threading.Lock()


def route_coords(start_lon, start_lat, end_lon, end_lat):
    """The direct route. Answers are kept for a couple of minutes and identical requests that arrive together
    share one call, because the page and the planning job both ask for the same route."""
    key = tuple(round(value, 5) for value in (start_lon, start_lat, end_lon, end_lat))
    with _route_guard:
        lock = _route_locks.setdefault(key, threading.Lock())
    with lock:
        hit = _route_cache.get(key)
        if hit and hit[0] > time.monotonic():
            return dict(hit[1])
        result = route_through([(start_lon, start_lat), (end_lon, end_lat)])
        now = time.monotonic()
        with _route_guard:
            _route_cache[key] = (now + ROUTE_CACHE_TTL_S, result)
            for old_key in [k for k, (expires, _) in _route_cache.items() if expires <= now]:
                del _route_cache[old_key]
                _route_locks.pop(old_key, None)
    return dict(result)


def route_through(points):
    body = json.dumps({"coordinates": [[lon, lat] for lon, lat in points]}).encode()
    data = _call(
        "POST",
        "/v2/directions/driving-car/geojson",
        body,
        {"Authorization": _key(), "Content-Type": "application/json"},
    )
    feature = data["features"][0]
    summary = feature["properties"]["summary"]
    steps = [step for segment in feature["properties"]["segments"] for step in segment["steps"]]
    return {
        "km": round(summary["distance"] / 1000, 1),
        "minutes": round(summary["duration"] / 60),
        "geometry": feature["geometry"]["coordinates"],
        "steps": [
            {"instruction": s["instruction"], "distance": s["distance"], "duration": s["duration"]}
            for s in steps
        ],
    }


def route(country, origin, destination):
    start = geocode(origin, country)
    end = geocode(destination, country)
    result = route_coords(start[0], start[1], end[0], end[1])
    return {
        "from": start[2],
        "to": end[2],
        "km": result["km"],
        "minutes": result["minutes"],
    }
