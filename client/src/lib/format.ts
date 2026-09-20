export type ArriveByResult =
  | { kind: "none" }
  | { kind: "ok"; iso: string }
  | { kind: "error"; message: string };

export function parseArriveBy(value: string, now: Date = new Date()): ArriveByResult {
  if (!value) return { kind: "none" };
  const [hours, minutes] = value.split(":").map(Number);
  const target = new Date(now);
  target.setHours(hours, minutes, 0, 0);
  if (target <= now) {
    return { kind: "error", message: "Arrival time must be later than now (today only)." };
  }
  return { kind: "ok", iso: target.toISOString() };
}

export function formatDistance(meters: number): string {
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km`;
}

export function todayHours(weekdayText: string[] | undefined, now: Date = new Date()): string {
  if (!weekdayText || weekdayText.length !== 7) return "hours unknown";
  // Google lists the week starting on Monday; Date.getDay() starts on Sunday.
  return weekdayText[(now.getDay() + 6) % 7];
}

export function newSessionId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Date.now().toString(36) + Math.random().toString(36).slice(2);
}
