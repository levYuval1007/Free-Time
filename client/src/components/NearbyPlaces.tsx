import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { todayHours } from "../lib/format";
import type { NearbyResult, SelectedPlace } from "../types";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; data: NearbyResult };

export function NearbyPlaces({ to }: { to: SelectedPlace }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    api
      .nearby(to.lat, to.lon)
      .then((data) => {
        if (!cancelled) setState({ status: "done", data });
      })
      .catch((err) => {
        if (!cancelled) setState({ status: "error", message: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [to.lat, to.lon]);

  if (state.status === "loading") return <div className="places-status">Searching...</div>;
  if (state.status === "error") return <div className="error">{state.message}</div>;

  const { data } = state;
  return (
    <div className="places">
      <div className="places-status">
        {data.places.length} places within 3 km ({data.latency_ms} ms, estimated cost so far $
        {data.stats.estimated_cost_usd})
      </div>
      <ol className="places-list">
        {data.places.map((place) => (
          <li key={place.id}>
            <div dir="auto">{place.name}</div>
            <div className="place-meta">
              {place.primary_type ?? "place"} -{" "}
              {place.rating == null ? "no rating" : `${place.rating} (${place.rating_count})`} -{" "}
              {todayHours(place.weekday_text)}
            </div>
            {place.maps_uri?.startsWith("https://") && (
              <a className="place-meta" href={place.maps_uri} target="_blank" rel="noopener noreferrer">
                View on Google Maps
              </a>
            )}
          </li>
        ))}
      </ol>
      <div className="attribution">
        Places data from <strong>Google Maps</strong>
      </div>
    </div>
  );
}
