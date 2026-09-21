import { clockTime } from "../lib/format";
import { googleMapsUrl } from "../lib/maps";
import type { TripResult } from "../types";
import { Metric, Notices } from "./Notices";
import { Steps } from "./Steps";
import { Timeline } from "./Timeline";

interface Props {
  result: TripResult;
  activeStopId: string | null;
  onSelectStop: (id: string) => void;
}

export function ResultPanel({ result, activeStopId, onSelectStop }: Props) {
  const { from, to, route, plan, arriveBy } = result;
  const stops = plan?.stops ?? [];
  const hasPlan = plan != null && stops.length > 0 && arriveBy != null;
  const budget = plan?.budget ?? route.budget;
  const steps = hasPlan ? (plan.steps ?? route.steps) : route.steps;

  return (
    <div className="result">
      {hasPlan ? (
        <div className="metrics">
          <Metric label="Leave" value={plan.depart ? clockTime(plan.depart) : "Now"} />
          <Metric label="Arrive" value={plan.arrive_destination ? clockTime(plan.arrive_destination) : ""} />
          <Metric label="Stops" value={String(stops.length)} />
        </div>
      ) : (
        <div className="metrics">
          <Metric label="Drive" value={`${route.minutes} min`} />
          <Metric label="Distance" value={`${route.km} km`} />
          {budget && <Metric label="Free time" value={`${budget.free_minutes} min`} />}
        </div>
      )}

      <Notices result={result} hasPlan={hasPlan} />

      {hasPlan && plan.summary && <p className="plan-summary">{plan.summary}</p>}

      {hasPlan && (
        <Timeline
          plan={plan}
          from={from}
          to={to}
          arriveBy={arriveBy}
          activeStopId={activeStopId}
          onSelectStop={onSelectStop}
        />
      )}

      <a
        className="button-link"
        href={googleMapsUrl(from, to, stops)}
        target="_blank"
        rel="noopener noreferrer"
      >
        Open in Google Maps
      </a>

      <details className="directions">
        <summary>Directions</summary>
        <Steps steps={steps} />
      </details>

      {hasPlan && (
        <div className="attribution">
          Places data from <strong>Google Maps</strong>. Opening hours can change, so please check before you go.
        </div>
      )}
    </div>
  );
}
