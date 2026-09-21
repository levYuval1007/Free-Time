import { budgetMessage, degradedMessage, planReasonMessage } from "../lib/budgetText";
import type { TripResult } from "../types";

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
}

export function Notices({ result, hasPlan }: { result: TripResult; hasPlan: boolean }) {
  const { route, plan, planError, degradedReason } = result;
  const budget = plan?.budget ?? route.budget;
  const showReason = plan?.reason != null && budget?.status === "ok";
  return (
    <>
      {degradedReason && <div className="notice go_direct">{degradedMessage(degradedReason)}</div>}
      {!hasPlan && budget && budget.status !== "ok" && (
        <div className={`notice ${budget.status}`}>{budgetMessage(budget)}</div>
      )}
      {!hasPlan && showReason && plan?.reason && <div className="notice go_direct">{planReasonMessage(plan.reason)}</div>}
      {planError && <div className="notice go_direct">Couldn't look for places to visit right now. {planError}</div>}
    </>
  );
}
