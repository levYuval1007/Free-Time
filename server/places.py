import json
import logging
import random
import threading
import time
import urllib.parse

import config
from http_client import PooledClient, TransportError

log = logging.getLogger("places")

HOST = "places.googleapis.com"
SEARCH_NEARBY_PATH = "/v1/places:searchNearby"
AUTOCOMPLETE_PATH = "/v1/places:autocomplete"
DETAILS_PATH = "/v1/places/"
MAX_RADIUS_M = 50000
DEFAULT_TYPES = [
    "park",
    "museum",
    "art_gallery",
    "tourist_attraction",
    "botanical_garden",
    "historical_landmark",
]
# rating and regularOpeningHours are Enterprise-tier fields, which set the price of the whole request.
FIELD_MASK = ",".join(
    "places." + f
    for f in (
        "id",
        "displayName",
        "location",
        "types",
        "primaryType",
        "businessStatus",
        "googleMapsUri",
        "utcOffsetMinutes",
        "rating",
        "userRatingCount",
        "priceLevel",
        "regularOpeningHours",
    )
)
AUTOCOMPLETE_FIELD_MASK = "suggestions.placePrediction.placeId,suggestions.placePrediction.text.text"
# location and formattedAddress are Essentials-tier; displayName would raise the request to Pro.
DETAILS_FIELD_MASK = "location,formattedAddress"

# Estimated USD per request beyond the free monthly caps. Autocomplete inside a session is billed
# through the Place Details call that ends it.
COST_NEARBY_ENTERPRISE = 0.035
COST_DETAILS_ESSENTIALS = 0.005
COST_AUTOCOMPLETE_IN_SESSION = 0.0

_client = PooledClient(HOST, timeout=6)
_stats_lock = threading.Lock()
_stats = {"requests": 0, "errors": 0, "estimated_cost_usd": 0.0}


class PlacesError(Exception):
    def __init__(self, message, transient=False):
        super().__init__(message)
        self.transient = transient


def stats():
    with _stats_lock:
        return {**_stats, "estimated_cost_usd": round(_stats["estimated_cost_usd"], 4)}


def _record(ok, cost=0.0):
    with _stats_lock:
        _stats["requests" if ok else "errors"] += 1
        if ok:
            _stats["estimated_cost_usd"] += cost


def _key():
    key = config.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise PlacesError("GOOGLE_MAPS_API_KEY is not set. Put it in server/.env or set the environment variable.")
    return key


def normalize_place(raw):
    place_id = raw.get("id")
    location = raw.get("location")
    if not place_id or not location:
        return None
    hours = raw.get("regularOpeningHours") or {}
    return {
        "id": place_id,
        "name": (raw.get("displayName") or {}).get("text", ""),
        "lat": location["latitude"],
        "lon": location["longitude"],
        "types": raw.get("types", []),
        "primary_type": raw.get("primaryType"),
        "rating": raw.get("rating"),
        "rating_count": raw.get("userRatingCount"),
        "price_level": raw.get("priceLevel"),
        "business_status": raw.get("businessStatus"),
        "periods": hours.get("periods"),
        "weekday_text": hours.get("weekdayDescriptions"),
        "utc_offset_minutes": raw.get("utcOffsetMinutes"),
        "maps_uri": raw.get("googleMapsUri"),
    }


def _error_message(raw):
    try:
        return json.loads(raw)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return raw.decode(errors="replace")[:200]


def _request_once(label, method, path, body, field_mask, cost):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _key(),
        "X-Goog-FieldMask": field_mask,
    }
    started = time.perf_counter()
    try:
        status, raw = _client.request(method, path, body, headers)
    except TransportError as err:
        _record(False)
        raise PlacesError(f"Could not reach Google Places: {err}", transient=True)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if status != 200:
        _record(False)
        log.warning("%s status=%s ms=%d", label, status, elapsed_ms)
        raise PlacesError(
            f"Google Places error {status}: {_error_message(raw)}",
            transient=status == 429 or status >= 500,
        )
    _record(True, cost)
    log.info("%s status=200 ms=%d", label, elapsed_ms)
    return json.loads(raw)


def _request(label, method, path, body, field_mask, cost):
    for attempt in (1, 2):
        try:
            return _request_once(label, method, path, body, field_mask, cost)
        except PlacesError as err:
            if err.transient and attempt == 1:
                time.sleep(random.uniform(0.2, 0.6))
                continue
            raise


def search_nearby(lat, lon, radius_m, types=None, max_results=20):
    body = json.dumps(
        {
            "includedTypes": types or DEFAULT_TYPES,
            "maxResultCount": max_results,
            "rankPreference": "POPULARITY",
            "languageCode": "en",
            "locationRestriction": {
                "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": float(radius_m)}
            },
        }
    ).encode()
    data = _request(
        "searchNearby", "POST", SEARCH_NEARBY_PATH, body, FIELD_MASK, COST_NEARBY_ENTERPRISE
    )
    found = [p for p in map(normalize_place, data.get("places", [])) if p]
    log.info("searchNearby results=%d", len(found))
    return found


def autocomplete(text, session_token, bias=None):
    """Place suggestions; bias is an optional (lat, lon) that ranks nearby places first."""
    request = {"input": text, "languageCode": "en", "sessionToken": session_token}
    if bias:
        lat, lon = bias
        request["locationBias"] = {
            "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": float(MAX_RADIUS_M)}
        }
    body = json.dumps(request).encode()
    data = _request(
        "autocomplete", "POST", AUTOCOMPLETE_PATH, body, AUTOCOMPLETE_FIELD_MASK, COST_AUTOCOMPLETE_IN_SESSION
    )
    return [
        {"label": s["placePrediction"]["text"]["text"], "place_id": s["placePrediction"]["placeId"]}
        for s in data.get("suggestions", [])
        if "placePrediction" in s
    ]


def place_location(place_id, session_token):
    path = (
        DETAILS_PATH
        + urllib.parse.quote(place_id, safe="")
        + "?"
        + urllib.parse.urlencode({"sessionToken": session_token})
    )
    data = _request("placeDetails", "GET", path, None, DETAILS_FIELD_MASK, COST_DETAILS_ESSENTIALS)
    location = data.get("location")
    if not location:
        raise PlacesError("Google returned no location for this place")
    return {
        "lat": location["latitude"],
        "lon": location["longitude"],
        "address": data.get("formattedAddress", ""),
    }
