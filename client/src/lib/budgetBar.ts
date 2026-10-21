import type { Budget } from "../types";

export interface BudgetBarParts {
  drive: number; // percentages of the whole bar, adding up to 100
  margin: number;
  free: number;
}

// "50 min", "1 hr", "1 hr 35 min".
export function formatMinutes(minutes: number): string {
  const whole = Math.max(0, Math.round(minutes));
  const hours = Math.floor(whole / 60);
  const rest = whole % 60;
  if (hours === 0) return `${rest} min`;
  return rest === 0 ? `${hours} hr` : `${hours} hr ${rest} min`;
}

// The share of the time until the deadline that goes to the drive, the safety margin and the free time.
export function budgetBarParts(budget: Budget): BudgetBarParts | null {
  if (budget.status === "impossible") return null;
  const total = budget.drive_minutes + budget.buffer_minutes + budget.free_minutes;
  if (total <= 0) return null;
  const drive = (budget.drive_minutes / total) * 100;
  const margin = (budget.buffer_minutes / total) * 100;
  return { drive, margin, free: 100 - drive - margin };
}
