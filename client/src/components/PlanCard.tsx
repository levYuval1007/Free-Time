import { useState } from "react";
import { api, errorMessage } from "../api";
import { clockTime, todayHours } from "../lib/format";
import type { PlanReason, PlanResult, SelectedPlace } from "../types";
import { RouteMap } from "./RouteMap";

interface Props {
  from: SelectedPlace;
  to: SelectedPlace;
  arriveBy: string;
}

type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; plan: PlanResult };

const REASONS: Record<PlanReason, string> = {
  impossible: "You can't arrive by then, even by driving straight there.",
  not_enough_time: "There is not enough free time for a stop - head straight there.",
  no_candidates: "No highly rated places with known opening hours were found near the start or the destination.",
  no_feasible_plan: "Nothing fits in your free time. The places nearby may be closed at those hours.",
};

export function PlanCard({ from, to, arriveBy }: Props) {
  const [state, setState] = useState<State>({ status: "idle" });

  async function suggest() {
    setState({ status: "loading" });
    try {
      setState({ status: "done", plan: await api.plan(from, to, arriveBy) });
    } catch (err) {
      setState({ status: "error", message: errorMessage(err) });
    }
  }

  return (
    <div className="plan">
      {state.status === "idle" && (
        <button onClick={() => void suggest()}>Suggest stops for my free time</button>
      )}
      {state.status === "loading" && <div className="plan-status">Looking for places to visit...</div>}
      {state.status === "error" && (
        <>
          <div className="error">{state.message}</div>
          <button onClick={() => void suggest()}>Try again</button>
        </>
      )}
      {state.status === "done" && <Timeline plan={state.plan} from={from} to={to} arriveBy={arriveBy} />}
    </div>
  );
}

function Timeline({ plan, from, to, arriveBy }: { plan: PlanResult; from: SelectedPlace; to: SelectedPlace; arriveBy: string }) {
  if (plan.stops.length === 0) {
    return <div className="plan-status">{plan.reason ? REASONS[plan.reason] : "No stops found."}</div>;
  }
  return (
    <>
      <h2 className="plan-title">Your free-time plan</h2>
      <ol className="timeline">
        <li>
          <div className="timeline-time">{plan.depart ? clockTime(plan.depart) : "Now"}</div>
          <div dir="auto">Leave {from.label}</div>
        </li>
        {plan.stops.map((stop) => (
          <li key={stop.id}>
            <div className="timeline-drive">Drive {Math.round(stop.drive_minutes)} min</div>
            <div className="stop-card">
              <div className="timeline-time">
                {clockTime(stop.arrive)} - {clockTime(stop.leave)}
              </div>
              <div className="stop-name" dir="auto">
                {stop.name}
              </div>
              <div className="place-meta">
                {stop.primary_type ?? "place"} - {stop.rating == null ? "no rating" : `${stop.rating} (${stop.rating_count})`} -{" "}
                {todayHours(stop.weekday_text, new Date(stop.arrive))}
              </div>
              {stop.maps_uri?.startsWith("https://") && (
                <a className="place-meta" href={stop.maps_uri} target="_blank" rel="noopener noreferrer">
                  View on Google Maps
                </a>
              )}
            </div>
          </li>
        ))}
        <li>
          <div className="timeline-drive">Drive {Math.round(plan.final_drive_minutes ?? 0)} min</div>
          <div className="timeline-time">{plan.arrive_destination ? clockTime(plan.arrive_destination) : ""}</div>
          <div dir="auto">
            Arrive at {to.label} (deadline {clockTime(arriveBy)})
          </div>
        </li>
      </ol>
      {plan.geometry && <RouteMap geometry={plan.geometry} stops={plan.stops} />}
      <div className="attribution">
        Places data from <strong>Google Maps</strong>. Opening hours can change, so please check before you go.
      </div>
    </>
  );
}
