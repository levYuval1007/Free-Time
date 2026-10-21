import { budgetBarParts, formatMinutes } from "../lib/budgetBar";
import { budgetMessage } from "../lib/budgetText";
import type { BudgetPreview } from "../hooks/useBudgetPreview";

interface Props {
  preview: BudgetPreview;
}

// How the time until the deadline divides into the drive, a safety margin and time for stops.
export function BudgetBar({ preview }: Props) {
  if (preview.kind === "idle" || preview.kind === "error") return null;
  if (preview.kind === "loading") {
    return (
      <div className="budget-bar" aria-busy="true">
        <div className="budget-title">Checking your free time...</div>
      </div>
    );
  }

  const { budget } = preview;
  const parts = budgetBarParts(budget);
  if (!parts) return <div className="budget-bar notice impossible">{budgetMessage(budget)}</div>;

  const enough = budget.status === "ok";
  return (
    <div className="budget-bar" role="group" aria-label="Free time before your deadline">
      <div className="budget-head">
        <span className="budget-title">Free time</span>
        <span className={`budget-total${enough ? "" : " low"}`}>{formatMinutes(budget.free_minutes)} free</span>
      </div>
      <div className="budget-track" aria-hidden="true">
        <span className="budget-drive" style={{ width: `${parts.drive}%` }} />
        <span className="budget-margin" style={{ width: `${parts.margin}%` }} />
        <span className="budget-free" style={{ width: `${parts.free}%` }} />
      </div>
      <div className="budget-legend">
        <span>Drive {formatMinutes(budget.drive_minutes)}</span>
        <span>Margin {formatMinutes(budget.buffer_minutes)}</span>
        <span className={enough ? "usable" : "low"}>{enough ? "Usable" : "Too little"} {formatMinutes(budget.free_minutes)}</span>
      </div>
      {!enough && <div className="budget-note">{budgetMessage(budget)}</div>}
    </div>
  );
}
