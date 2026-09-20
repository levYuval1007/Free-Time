import type { Budget } from "../types";

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
