"""Driving times for one planning run, fetched with as few routing calls as possible.

The free routing quota is small, and one matrix call costs the same however many points it covers. So the
places found so far are remembered, and when a time is missing one call fills in every pair between all known
points. Later questions from the agent and the validator are then answered from memory.
"""

MAX_NODES = 55  # keeps one matrix well under the routing service's limit on routes per request


def _key(point):
    return (round(point[0], 5), round(point[1], 5))


class TravelTimes:
    def __init__(self, matrix_fn):
        self._fetch_matrix = matrix_fn
        self._nodes = {}  # key -> (lon, lat), in the order first seen
        self._minutes = {}  # (from_key, to_key) -> minutes, or None when there is no route
        self.calls = 0

    def register(self, points):
        for point in points:
            self._nodes.setdefault(_key(point), point)

    def __call__(self, points):
        keys = [_key(point) for point in points]
        if any((a, b) not in self._minutes for a in keys for b in keys if a != b):
            self._fill(points)
        return [[0 if a == b else self._minutes[(a, b)] for b in keys] for a in keys]

    def _fill(self, points):
        known = dict(self._nodes)
        for point in points:
            known.setdefault(_key(point), point)
        # Ask for everything known when it fits; otherwise only what was asked for.
        chosen = list(known.values()) if len(known) <= MAX_NODES else list(points)
        grid = self._fetch_matrix(chosen)
        self.calls += 1
        keys = [_key(point) for point in chosen]
        for i, a in enumerate(keys):
            for j, b in enumerate(keys):
                if i != j:
                    self._minutes[(a, b)] = grid[i][j]
