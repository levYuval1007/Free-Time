import { useEffect, useRef } from "react";
import { budgetMessage, planReasonMessage } from "../lib/budgetText";
import { clockTime } from "../lib/format";
import { googleMapsUrl } from "../lib/maps";
import type { TripResult } from "../types";
import { Steps } from "./Steps";
import { Timeline } from "./Timeline";

interface Props {
  result: TripResult;
  activeStopId: string | null;
  onSelectStop: (id: string) => void;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
}

export function ResultPanel({ result, activeStopId, onSelectStop }: Props) {
  const { from, to, route, plan, planError, arriveBy } = result;
  const container = useRef<HTMLDivElement>(null);

  // On a phone the result starts below the form, so bring it into view.
  useEffect(() => {
    if (window.matchMedia("(max-width: 800px)").matches) {
      container.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [result]);
  const stops = plan?.stops ?? [];
  const hasPlan = plan != null && stops.length > 0 && arriveBy != null;
  const budget = plan?.budget ?? route.budget;
  const showReason = plan?.reason != null && budget?.status === "ok";
  const steps = hasPlan ? (plan.steps ?? route.steps) : route.steps;

  return (
    <div className="result" ref={container}>
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

      {!hasPlan && budget && budget.status !== "ok" && (
        <div className={`notice ${budget.status}`}>{budgetMessage(budget)}</div>
      )}
      {!hasPlan && showReason && plan?.reason && <div className="notice go_direct">{planReasonMessage(plan.reason)}</div>}
      {planError && <div className="notice go_direct">Couldn't look for places to visit right now. {planError}</div>}

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
