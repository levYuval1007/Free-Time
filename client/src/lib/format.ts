export type ArriveByResult =
  | { kind: "none" }
  | { kind: "ok"; iso: string }
  | { kind: "error"; message: string };

export function parseArriveBy(value: string, now: Date = new Date()): ArriveByResult {
  if (!value) return { kind: "none" };
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) {
    return { kind: "error", message: "Arrival time is not valid." };
  }
  if (target <= now) {
    return { kind: "error", message: "Arrival time must be later than now." };
  }
  return { kind: "ok", iso: target.toISOString() };
}

export function clockTime(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const dayDifference = Math.round(
    (new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime() -
      new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) /
      86_400_000,
  );
  if (dayDifference === 0) return time;
  if (dayDifference === 1) return `${time} tomorrow`;
  return `${time} (${date.toLocaleDateString()})`;
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
