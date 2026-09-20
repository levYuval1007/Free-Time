import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import type { Coordinates, PlannedStop, SelectedPlace } from "../types";

interface Props {
  from: SelectedPlace | null;
  to: SelectedPlace | null;
  geometry?: [number, number][];
  stops: PlannedStop[];
  activeStopId: string | null;
  onSelectStop: (id: string) => void;
  center: Coordinates | null;
}

export function TripMap({ from, to, geometry, stops, activeStopId, onSelectStop, center }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const onSelect = useRef(onSelectStop);
  onSelect.current = onSelectStop;

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const instance = L.map(element, { zoomAnimation: false }).setView([20, 0], 2);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(instance);
    layer.current = L.layerGroup().addTo(instance);
    map.current = instance;
    const observer = new ResizeObserver(() => instance.invalidateSize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      instance.remove();
      map.current = null;
      layer.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const points: L.LatLngTuple[] = [];
    if (geometry?.length) {
      for (const [lon, lat] of geometry) points.push([lat, lon]);
    } else {
      if (from) points.push([from.lat, from.lon]);
      if (to) points.push([to.lat, to.lon]);
    }
    instance.invalidateSize();
    if (points.length > 1) instance.fitBounds(L.latLngBounds(points), { padding: [40, 40], animate: false });
    else if (points.length === 1) instance.setView(points[0], 14, { animate: false });
    else if (center) instance.setView([center.lat, center.lon], 12, { animate: false });
  }, [from, to, geometry, center]);

  useEffect(() => {
    const group = layer.current;
    if (!group) return;
    group.clearLayers();
    if (geometry?.length) {
      L.polyline(
        geometry.map(([lon, lat]) => [lat, lon] as L.LatLngTuple),
        { color: "#667eea", weight: 5 },
      ).addTo(group);
    }
    if (from) {
      L.circleMarker([from.lat, from.lon], { radius: 8, color: "#ffffff", weight: 2, fillColor: "#2e7d32", fillOpacity: 1 })
        .bindTooltip("Start")
        .addTo(group);
    }
    if (to) {
      L.circleMarker([to.lat, to.lon], { radius: 8, color: "#ffffff", weight: 2, fillColor: "#c62828", fillOpacity: 1 })
        .bindTooltip("Destination")
        .addTo(group);
    }
    stops.forEach((stop, index) => {
      const active = stop.id === activeStopId;
      L.marker([stop.lat, stop.lon], {
        icon: L.divIcon({
          className: "",
          html: `<div class="pin${active ? " active" : ""}">${index + 1}</div>`,
          iconSize: [30, 30],
        }),
        title: stop.name,
        zIndexOffset: active ? 1000 : 0,
      })
        .on("click", () => onSelect.current(stop.id))
        .addTo(group);
    });
  }, [from, to, geometry, stops, activeStopId]);

  return <div ref={container} className="map" />;
}
