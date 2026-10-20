"""Small geometry helpers for working with a driving route.

Routes are lists of (lon, lat) points, the order OpenRouteService uses.
"""

import math

EARTH_RADIUS_KM = 6371


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def distance_to_route_km(lat, lon, route):
    """Straight-line distance in km from a point to the nearest part of the route (None for an empty route).

    Each segment is flattened around the point, which is accurate to well under a percent for the few tens of
    kilometres we care about.
    """
    if not route:
        return None
    if len(route) == 1:
        return haversine_km(lat, lon, route[0][1], route[0][0])
    km_per_degree_lat = math.pi * EARTH_RADIUS_KM / 180
    km_per_degree_lon = km_per_degree_lat * math.cos(math.radians(lat))
    best = math.inf
    for (lon1, lat1), (lon2, lat2) in zip(route, route[1:]):
        ax, ay = (lon1 - lon) * km_per_degree_lon, (lat1 - lat) * km_per_degree_lat
        bx, by = (lon2 - lon) * km_per_degree_lon, (lat2 - lat) * km_per_degree_lat
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        t = 0.0 if length_squared == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length_squared))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def thin(route, max_points):
    """At most max_points points that keep the route's shape: points are kept at even distances along it,
    and the first and last point are always kept."""
    if len(route) <= max_points or max_points < 2:
        return list(route)
    legs = [haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(route, route[1:])]
    total = sum(legs)
    if total == 0:
        return [route[0], route[-1]]
    step = total / (max_points - 1)
    kept, travelled, next_mark = [route[0]], 0.0, step
    for point, leg in zip(route[1:], legs):
        travelled += leg
        if travelled >= next_mark and len(kept) < max_points - 1:
            kept.append(point)
            next_mark += step * max(1, int((travelled - next_mark) // step) + 1)
    kept.append(route[-1])
    return kept


def encode_polyline(route):
    """Google's Encoded Polyline Algorithm (5 decimal places) for a list of (lon, lat) points."""

    def encode_value(value):
        value = ~(value << 1) if value < 0 else value << 1
        chunks = []
        while value >= 0x20:
            chunks.append(chr((0x20 | (value & 0x1F)) + 63))
            value >>= 5
        chunks.append(chr(value + 63))
        return "".join(chunks)

    out, last_lat, last_lon = [], 0, 0
    for lon, lat in route:
        lat_e5, lon_e5 = round(lat * 1e5), round(lon * 1e5)
        out.append(encode_value(lat_e5 - last_lat))
        out.append(encode_value(lon_e5 - last_lon))
        last_lat, last_lon = lat_e5, lon_e5
    return "".join(out)
