import type { Budget, PlanReason } from "../types";

export function budgetMessage(budget: Budget): string {
  const free = `${budget.free_minutes} free ${budget.free_minutes === 1 ? "minute" : "minutes"}`;
  switch (budget.status) {
    case "ok":
      return `You have ${free} (drive ${budget.drive_minutes} min + ${budget.buffer_minutes} min buffer).`;
    case "go_direct":
      return `Only ${free} after the drive and buffer - head straight there.`;
    case "impossible":
      return "You can't arrive by then, even by driving straight there.";
  }
}

export function planReasonMessage(reason: PlanReason): string {
  switch (reason) {
    case "impossible":
      return "You can't arrive by then, even by driving straight there.";
    case "not_enough_time":
      return "There isn't enough free time for a stop, so head straight there.";
    case "no_candidates":
      return "No highly rated places with known opening hours were found near the start or the destination.";
    case "no_feasible_plan":
      return "Nothing fits in your free time. The places nearby may be closed at those hours.";
  }
}
