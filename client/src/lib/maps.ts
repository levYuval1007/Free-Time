import type { Coordinates } from "../types";

export function googleMapsUrl(from: Coordinates, to: Coordinates, stops: Coordinates[] = []): string {
  const point = (c: Coordinates) => `${c.lat},${c.lon}`;
  const params = new URLSearchParams({
    api: "1",
    origin: point(from),
    destination: point(to),
    travelmode: "driving",
  });
  if (stops.length > 0) params.set("waypoints", stops.map(point).join("|"));
  return `https://www.google.com/maps/dir/?${params}`;
}
