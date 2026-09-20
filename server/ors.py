import json
import urllib.parse

import config
from http_client import PooledClient, TransportError

API_HOST = "api.openrouteservice.org"


class RouteError(Exception):
    pass


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
        raise RouteError(f"OpenRouteService error {status}: {raw.decode(errors='replace')}")
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


def route_coords(start_lon, start_lat, end_lon, end_lat):
    return route_through([(start_lon, start_lat), (end_lon, end_lat)])


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
