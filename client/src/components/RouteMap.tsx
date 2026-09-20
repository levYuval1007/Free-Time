import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

interface MapStop {
  name: string;
  lat: number;
  lon: number;
}

interface Props {
  geometry: [number, number][];
  stops?: MapStop[];
}

export function RouteMap({ geometry, stops }: Props) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current || geometry.length === 0) return;
    const map = L.map(container.current);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    const points = geometry.map(([lon, lat]) => [lat, lon] as L.LatLngTuple);
    const line = L.polyline(points, { color: "#667eea", weight: 5 }).addTo(map);
    L.circleMarker(points[0], { radius: 8, color: "#2e7d32", fillOpacity: 1 }).addTo(map);
    L.circleMarker(points[points.length - 1], { radius: 8, color: "#c62828", fillOpacity: 1 }).addTo(map);
    for (const stop of stops ?? []) {
      L.circleMarker([stop.lat, stop.lon], { radius: 7, color: "#1565c0", fillColor: "#ffffff", fillOpacity: 1, weight: 4 })
        .bindTooltip(stop.name)
        .addTo(map);
    }
    map.fitBounds(line.getBounds(), { padding: [20, 20] });
    return () => {
      map.remove();
    };
  }, [geometry, stops]);

  return <div ref={container} className="map" />;
}
