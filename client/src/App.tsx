import { useRef, useState } from "react";
import { api, errorMessage } from "./api";
import { ArrivalTimePicker } from "./components/ArrivalTimePicker";
import { PlaceField } from "./components/PlaceField";
import { ResultPanel } from "./components/ResultPanel";
import { TripMap } from "./components/TripMap";
import { TripSheet } from "./components/TripSheet";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { useUserLocation } from "./hooks/useUserLocation";
import { focusPointFor } from "./lib/carousel";
import { clockTime, newSessionId, parseArriveBy, shortLabel } from "./lib/format";
import { pollJob } from "./lib/polling";
import type { PlanResult, SelectedPlace, TripResult } from "./types";

export default function App() {
  const { location, request: requestLocation } = useUserLocation();
  const [from, setFrom] = useState<SelectedPlace | null>(null);
  const [to, setTo] = useState<SelectedPlace | null>(null);
  const [arrive, setArrive] = useState("");
  const [preferences, setPreferences] = useState("");
  const [stage, setStage] = useState<string | null>(null);
  // Bumped whenever a run is replaced or abandoned, so a late answer from an old run is ignored.
  const currentRun = useRef(0);
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
      currentRun.current += 1;
      setLoading(false);
      setStage(null);
      setResult(null);
      setFocusIndex(0);
      if (place) setError(null);
    };
  }

  async function runPlan(
    origin: SelectedPlace,
    destination: SelectedPlace,
    arriveBy: string,
    run: number,
  ): Promise<{ plan?: PlanResult; planError?: string; degradedReason?: string }> {
    const isCurrent = () => run === currentRun.current;
    try {
      const started = await api.startPlan(origin, destination, arriveBy, preferences, newSessionId());
      const job = await pollJob(() => api.getPlan(started.job_id), {
        onStage: (text) => isCurrent() && setStage(text ?? null),
        isCancelled: () => !isCurrent(),
      });
      if (job.status === "failed") return { planError: job.error ?? "Planning failed." };
      return {
        plan: job.result,
        degradedReason: job.status === "degraded" ? (job.degraded_reason ?? "unknown") : undefined,
      };
    } catch (err) {
      return { planError: errorMessage(err) };
    }
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
    const run = ++currentRun.current;
    setLoading(true);
    setStage(null);
    try {
      // The route is quick; the plan is a job that takes longer and is polled until it finishes.
      const planning = arriveBy ? runPlan(from, to, arriveBy, run) : Promise.resolve({});
      const [route, planned] = await Promise.all([api.route(from, to, arriveBy), planning]);
      if (run !== currentRun.current) return;
      setResult({ from, to, arriveBy, route, ...planned });
    } catch (err) {
      if (run === currentRun.current) setError(errorMessage(err));
    } finally {
      if (run === currentRun.current) {
        setLoading(false);
        setStage(null);
      }
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

        <div className="form-group">
          <label htmlFor="preferences">What are you in the mood for? (optional)</label>
          <input
            id="preferences"
            type="text"
            value={preferences}
            maxLength={500}
            placeholder="Quiet places, coffee first, good with kids..."
            onChange={(e) => setPreferences(e.target.value)}
          />
        </div>

        <button className="primary" disabled={!from || !to || loading} onClick={() => void planTrip()}>
          {loading ? `${stage ?? "Planning your trip"}...` : "Plan my trip"}
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
