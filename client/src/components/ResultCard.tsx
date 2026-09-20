import { useState } from "react";
import type { Budget, RouteResult, SelectedPlace } from "../types";
import { NearbyPlaces } from "./NearbyPlaces";
import { RouteMap } from "./RouteMap";
import { Steps } from "./Steps";

interface Props {
  from: SelectedPlace;
  to: SelectedPlace;
  data: RouteResult;
}

function Row({ name, value }: { name: string; value: string }) {
  return (
    <div className="result-row">
      <strong>{name}: </strong>
      <span dir="auto">{value}</span>
    </div>
  );
}

function budgetMessage(budget: Budget): string {
  switch (budget.status) {
    case "ok":
      return `You have ${budget.free_minutes} free minutes (drive ${budget.drive_minutes} min + ${budget.buffer_minutes} min buffer).`;
    case "go_direct":
      return `Only ${budget.free_minutes} free minutes after the drive and buffer - head straight there.`;
    case "impossible":
      return "You can't arrive by then, even by driving straight there.";
  }
}

export function ResultCard({ from, to, data }: Props) {
  const [showMap, setShowMap] = useState(false);
  const [showPlaces, setShowPlaces] = useState(false);

  return (
    <>
      <div className="result">
        <h2>Result</h2>
        <Row name="From" value={from.label} />
        <Row name="To" value={to.label} />
        <Row name="Distance" value={`${data.km} km`} />
        <Row name="Driving time" value={`${data.minutes} min`} />
        {data.budget && <div className={`budget ${data.budget.status}`}>{budgetMessage(data.budget)}</div>}
      </div>

      <button className="secondary" onClick={() => setShowMap((v) => !v)}>
        {showMap ? "Hide" : "Show"} map &amp; directions
      </button>
      {showMap && (
        <div className="details">
          <RouteMap geometry={data.geometry} />
          <Steps steps={data.steps} />
        </div>
      )}

      <button className="secondary" onClick={() => setShowPlaces((v) => !v)}>
        {showPlaces ? "Hide places" : "Find places near destination (debug)"}
      </button>
      {showPlaces && <NearbyPlaces to={to} />}
    </>
  );
}
