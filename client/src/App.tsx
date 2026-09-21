import { useState } from "react";
import { api, errorMessage } from "./api";
import { ArrivalTimePicker } from "./components/ArrivalTimePicker";
import { PlaceField } from "./components/PlaceField";
import { ResultPanel } from "./components/ResultPanel";
import { TripMap } from "./components/TripMap";
import { TripSheet } from "./components/TripSheet";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { useUserLocation } from "./hooks/useUserLocation";
import { focusPointFor } from "./lib/carousel";
import { clockTime, parseArriveBy, shortLabel } from "./lib/format";
import type { PlanResult, SelectedPlace, TripResult } from "./types";

export default function App() {
  const { location, request: requestLocation } = useUserLocation();
  const [from, setFrom] = useState<SelectedPlace | null>(null);
  const [to, setTo] = useState<SelectedPlace | null>(null);
  const [arrive, setArrive] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TripResult | null>(null);
  // 0 is the overview card, 1..n the stops, and the last card the destination.
  const [focusIndex, setFocusIndex] = useState(0);
  const [editing, setEditing] = useState(false);
  const isPhone = useMediaQuery("(max-width: 800px)");

  function changePlace(set: (place: SelectedPlace | null) => void) {
    return (place: SelectedPlace | null) => {
      set(place);
      setResult(null);
      setFocusIndex(0);
      if (place) setError(null);
    };
  }

  async function planTrip() {
    if (!from || !to) return;
    setError(null);
    setResult(null);
    setFocusIndex(0);
    setEditing(false);
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
  const activeStopId = focusIndex >= 1 && focusIndex <= stops.length ? stops[focusIndex - 1].id : null;
  // On a phone the result replaces the form: a compact bar, the map, and a swipeable sheet.
  const tripMode = isPhone && result != null && !editing;
  const focus = tripMode && result ? focusPointFor(focusIndex, stops, result.to) : null;

  function selectStop(id: string) {
    const index = stops.findIndex((stop) => stop.id === id);
    if (index >= 0) setFocusIndex(index + 1);
  }

  return (
    <div className={`app${tripMode ? " trip" : ""}`}>
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

      {tripMode && result && (
        <div className="trip-bar">
          <img className="logo" src="/logo.svg" alt="" width={32} height={32} />
          <div className="trip-bar-text">
            <div className="trip-route" dir="auto">
              {shortLabel(result.from.label)} → {shortLabel(result.to.label)}
            </div>
            {result.arriveBy && <div className="trip-sub">Arrive by {clockTime(result.arriveBy)}</div>}
          </div>
          <button type="button" className="trip-edit" onClick={() => setEditing(true)}>
            Edit
          </button>
        </div>
      )}

      <div className="map-area">
        <TripMap
          from={from}
          to={to}
          geometry={geometry}
          stops={stops}
          activeStopId={activeStopId}
          onSelectStop={selectStop}
          center={location}
          focus={focus}
          refitKey={tripMode}
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

        {isPhone && editing && result && (
          <button type="button" className="link-button" onClick={() => setEditing(false)}>
            Back to your trip
          </button>
        )}

        {result && !isPhone && <ResultPanel result={result} activeStopId={activeStopId} onSelectStop={selectStop} />}
      </main>

      {tripMode && result && <TripSheet result={result} index={focusIndex} onIndexChange={setFocusIndex} />}
    </div>
  );
}
