import { clockTime, todayHours } from "../lib/format";
import type { PlanResult, SelectedPlace } from "../types";

interface Props {
  plan: PlanResult;
  from: SelectedPlace;
  to: SelectedPlace;
  arriveBy: string;
  activeStopId: string | null;
  onSelectStop: (id: string) => void;
}

export function Timeline({ plan, from, to, arriveBy, activeStopId, onSelectStop }: Props) {
  const minutesBefore =
    plan.arrive_destination == null
      ? null
      : Math.round((new Date(arriveBy).getTime() - new Date(plan.arrive_destination).getTime()) / 60_000);

  return (
    <ol className="timeline">
      <li>
        <div className="timeline-time">{plan.depart ? clockTime(plan.depart) : "Now"}</div>
        <div dir="auto">Leave {from.label}</div>
      </li>
      {plan.stops.map((stop, index) => (
        <li key={stop.id}>
          <div className="timeline-drive">Drive {Math.round(stop.drive_minutes)} min</div>
          <button
            type="button"
            className={`stop-card${stop.id === activeStopId ? " active" : ""}`}
            onClick={() => onSelectStop(stop.id)}
          >
            <span className="stop-number">{index + 1}</span>
            <span className="stop-body">
              <span className="stop-name" dir="auto">
                {stop.name}
              </span>
              <span className="stop-time">
                {clockTime(stop.arrive)} - {clockTime(stop.leave)} ({stop.visit_minutes} min)
              </span>
              <span className="place-meta">
                {stop.primary_type?.replace(/_/g, " ") ?? "place"} -{" "}
                {stop.rating == null ? "no rating" : `${stop.rating} (${stop.rating_count})`} -{" "}
                {todayHours(stop.weekday_text, new Date(stop.arrive))}
              </span>
              {stop.maps_uri?.startsWith("https://") && (
                <a
                  className="place-meta"
                  href={stop.maps_uri}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                >
                  View on Google Maps
                </a>
              )}
            </span>
          </button>
        </li>
      ))}
      <li>
        <div className="timeline-drive">Drive {Math.round(plan.final_drive_minutes ?? 0)} min</div>
        <div className="timeline-time">{plan.arrive_destination ? clockTime(plan.arrive_destination) : ""}</div>
        <div dir="auto">Arrive at {to.label}</div>
        {minutesBefore != null && minutesBefore >= 0 && (
          <div className="timeline-slack">{minutesBefore} min before your deadline</div>
        )}
      </li>
    </ol>
  );
}
