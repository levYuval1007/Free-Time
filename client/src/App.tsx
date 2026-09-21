import { useState } from "react";
import { api, errorMessage } from "./api";
import { ArrivalTimePicker } from "./components/ArrivalTimePicker";
import { PlaceField } from "./components/PlaceField";
import { ResultPanel } from "./components/ResultPanel";
import { TripMap } from "./components/TripMap";
import { useUserLocation } from "./hooks/useUserLocation";
import { parseArriveBy } from "./lib/format";
import type { PlanResult, SelectedPlace, TripResult } from "./types";

export default function App() {
  const { location, request: requestLocation } = useUserLocation();
  const [from, setFrom] = useState<SelectedPlace | null>(null);
  const [to, setTo] = useState<SelectedPlace | null>(null);
  const [arrive, setArrive] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TripResult | null>(null);
  const [activeStop, setActiveStop] = useState<string | null>(null);

  function changePlace(set: (place: SelectedPlace | null) => void) {
    return (place: SelectedPlace | null) => {
      set(place);
      setResult(null);
      setActiveStop(null);
      if (place) setError(null);
    };
  }

  async function planTrip() {
    if (!from || !to) return;
    setError(null);
    setResult(null);
    setActiveStop(null);
    const arrival = parseArriveBy(arrive);
    if (arrival.kind === "error") {
      setError(arrival.message);
      return;
    }
    const arriveBy = arrival.kind === "ok" ? arrival.iso : undefined;
    setLoading(true);
    try {
      // The plan endpoint only pays for a places search when there is free time, so both can run together.
      const planning: Promise<{ plan?: PlanResult; planError?: string }> = arriveBy
        ? api
            .plan(from, to, arriveBy)
            .then((plan) => ({ plan }))
            .catch((err) => ({ planError: errorMessage(err) }))
        : Promise.resolve({});
      const [route, planned] = await Promise.all([api.route(from, to, arriveBy), planning]);
      setResult({ from, to, arriveBy, route, ...planned });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  const stops = result?.plan?.stops ?? [];
  const geometry = stops.length > 0 ? result?.plan?.geometry : result?.route.geometry;

  return (
    <div className="app">
      <header className="banner">
        <div className="brand">
          <img className="logo" src="/logo.svg" alt="" width={40} height={40} />
          <div>
            <h1>Leeway</h1>
            <p className="tagline">Make the most of the time before you have to be there.</p>
          </div>
        </div>
        <div className="banner-route" aria-hidden="true">
          <svg viewBox="0 0 100 32" preserveAspectRatio="none">
            <path d="M100 5 C 92 -3, 88 17, 80 12 S 66 -3, 58 12 S 44 27, 36 15 S 22 31, 14 22 S 6 27, 0 27" />
          </svg>
          <span className="route-end" />
          <span className="route-start" />
        </div>
      </header>

      <div className="map-area">
        <TripMap
          from={from}
          to={to}
          geometry={geometry}
          stops={stops}
          activeStopId={activeStop}
          onSelectStop={setActiveStop}
          center={location}
        />
      </div>

      <main className="panel">
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}

        <PlaceField
          label="From"
          placeholder="Where are you now?"
          bias={location}
          onChange={changePlace(setFrom)}
          onError={setError}
          onRequestLocation={requestLocation}
        />
        <PlaceField
          label="To"
          placeholder="Where do you need to be?"
          bias={location}
          onChange={changePlace(setTo)}
          onError={setError}
        />
        <ArrivalTimePicker value={arrive} onChange={setArrive} />

        <button className="primary" disabled={!from || !to || loading} onClick={() => void planTrip()}>
          {loading ? "Planning your trip..." : "Plan my trip"}
        </button>

        {result && <ResultPanel result={result} activeStopId={activeStop} onSelectStop={setActiveStop} />}
      </main>
    </div>
  );
}
