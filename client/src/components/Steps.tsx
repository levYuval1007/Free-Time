import { formatDistance } from "../lib/format";
import type { RouteStep } from "../types";

export function Steps({ steps }: { steps: RouteStep[] }) {
  return (
    <ol className="steps">
      {steps.map((step, index) => (
        <li key={index}>
          <div className="step-row">
            <span dir="auto">{step.instruction}</span>
            <span className="step-dist">{formatDistance(step.distance)}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}
