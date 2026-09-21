import { useEffect, useRef } from "react";
import { indexFromScroll, minutesBeforeDeadline } from "../lib/carousel";
import { clockTime, shortTime, todayHours } from "../lib/format";
import { googleMapsUrl } from "../lib/maps";
import type { PlanResult, TripResult } from "../types";
import { Metric, Notices } from "./Notices";
import { Steps } from "./Steps";

interface Props {
  result: TripResult;
  index: number;
  onIndexChange: (index: number) => void;
}

interface CardsProps {
  result: TripResult;
  plan: PlanResult;
  arriveBy: string;
  index: number;
  onIndexChange: (index: number) => void;
}

const SETTLE_MS = 700;

function Cards({ result, plan, arriveBy, index, onIndexChange }: CardsProps) {
  const { to } = result;
  const stops = plan.stops;
  const count = stops.length + 2;
  const scroller = useRef<HTMLDivElement>(null);
  const shown = useRef(index);
  const lockedUntil = useRef(0);
  const spare = minutesBeforeDeadline(plan.arrive_destination, arriveBy);

  function onScroll() {
    const el = scroller.current;
    if (!el || Date.now() < lockedUntil.current) return;
    const next = indexFromScroll(el.scrollLeft, el.scrollWidth - el.clientWidth, count);
    if (next !== shown.current) {
      shown.current = next;
      onIndexChange(next);
    }
  }

  // The map pins and the nav below can change the index too; bring the matching card into view.
  useEffect(() => {
    if (index === shown.current) return;
    shown.current = index;
    const el = scroller.current;
    const card = el?.children[index] as HTMLElement | undefined;
    if (!el || !card) return;
    lockedUntil.current = Date.now() + SETTLE_MS;
    el.scrollTo({ left: card.offsetLeft - (el.clientWidth - card.clientWidth) / 2, behavior: "smooth" });
  }, [index]);

  const navLabels = ["All", ...stops.map((stop) => shortTime(stop.arrive)), plan.arrive_destination ? shortTime(plan.arrive_destination) : "End"];

  return (
    <>
      <div className="carousel" ref={scroller} onScroll={onScroll}>
        <article className="card" aria-label="Overview">
          <div className="card-kicker">Your plan</div>
          <div className="card-title">
            Leave {plan.depart ? clockTime(plan.depart) : "now"} - arrive{" "}
            {plan.arrive_destination ? clockTime(plan.arrive_destination) : ""}
          </div>
          <div className="card-sub">
            {stops.length} {stops.length === 1 ? "stop" : "stops"}
            {spare != null && spare >= 0 ? ` - ${spare} min to spare` : ""}
          </div>
          <div className="card-hint">Swipe to see each stop</div>
        </article>

        {stops.map((stop, i) => (
          <article className="card" key={stop.id} aria-label={`Stop ${i + 1}`}>
            <div className="card-kicker">
              Stop {i + 1} - drive {Math.round(stop.drive_minutes)} min
            </div>
            <div className="card-title" dir="auto">
              {stop.name}
            </div>
            <div className="card-sub">
              {clockTime(stop.arrive)} - {clockTime(stop.leave)} ({stop.visit_minutes} min)
            </div>
            <div className="card-meta">
              {stop.primary_type?.replace(/_/g, " ") ?? "place"} -{" "}
              {stop.rating == null ? "no rating" : `${stop.rating} (${stop.rating_count})`} -{" "}
              {todayHours(stop.weekday_text, new Date(stop.arrive))}
            </div>
            {stop.maps_uri?.startsWith("https://") && (
              <a className="card-link" href={stop.maps_uri} target="_blank" rel="noopener noreferrer">
                View on Google Maps
              </a>
            )}
          </article>
        ))}

        <article className="card" aria-label="Destination">
          <div className="card-kicker">Destination - drive {Math.round(plan.final_drive_minutes ?? 0)} min</div>
          <div className="card-title" dir="auto">
            {to.label}
          </div>
          <div className="card-sub">Arrive {plan.arrive_destination ? clockTime(plan.arrive_destination) : ""}</div>
          {spare != null && spare >= 0 && <div className="card-ok">{spare} min before your deadline</div>}
        </article>
      </div>

      <nav className="carousel-nav" aria-label="Trip steps">
        {navLabels.map((label, i) => (
          <button
            key={i}
            type="button"
            className={`nav-item${i === index ? " active" : ""}`}
            aria-current={i === index}
            onClick={() => onIndexChange(i)}
          >
            <span className="nav-dot" />
            {label}
          </button>
        ))}
      </nav>
    </>
  );
}

export function TripSheet({ result, index, onIndexChange }: Props) {
  const { from, to, route, plan, arriveBy } = result;
  const stops = plan?.stops ?? [];
  const hasPlan = plan != null && stops.length > 0 && arriveBy != null;
  const budget = plan?.budget ?? route.budget;
  const steps = hasPlan ? (plan.steps ?? route.steps) : route.steps;

  return (
    <section className="trip-sheet">
      {hasPlan ? (
        <Cards result={result} plan={plan} arriveBy={arriveBy} index={index} onIndexChange={onIndexChange} />
      ) : (
        <div className="sheet-body">
          <div className="metrics">
            <Metric label="Drive" value={`${route.minutes} min`} />
            <Metric label="Distance" value={`${route.km} km`} />
            {budget && <Metric label="Free time" value={`${budget.free_minutes} min`} />}
          </div>
          <Notices result={result} hasPlan={false} />
        </div>
      )}

      <div className="sheet-body">
        <a className="button-link" href={googleMapsUrl(from, to, stops)} target="_blank" rel="noopener noreferrer">
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
    </section>
  );
}
