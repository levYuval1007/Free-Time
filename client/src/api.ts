import type {
  Coordinates,
  PlanJob,
  PlanResult,
  ResolvedPlace,
  RouteResult,
  SuggestResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

type Params = Record<string, string | number | undefined>;

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const message = (body as { error?: string } | null)?.error ?? `Request failed (${res.status})`;
    throw new ApiError(message, res.status);
  }
  return body as T;
}

function getJson<T>(path: string, params: Params = {}): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value));
  }
  return send<T>(`${path}?${query}`);
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

interface Point {
  lon: number;
  lat: number;
  label?: string;
}

export const api = {
  suggest: (q: string, session: string, bias?: Coordinates | null) =>
    getJson<SuggestResponse>("/api/suggest", { q, session, lat: bias?.lat, lon: bias?.lon }),
  resolve: (placeId: string, session: string) =>
    getJson<ResolvedPlace>("/api/places/resolve", { place_id: placeId, session }),
  route: (from: Point, to: Point, arriveBy?: string) =>
    getJson<RouteResult>("/api/route", {
      from_lon: from.lon,
      from_lat: from.lat,
      to_lon: to.lon,
      to_lat: to.lat,
      arrive_by: arriveBy,
    }),
  // The basic planner only, answered in one request.
  plan: (from: Point, to: Point, arriveBy: string) =>
    getJson<PlanResult>("/api/plan", {
      from_lon: from.lon,
      from_lat: from.lat,
      to_lon: to.lon,
      to_lat: to.lat,
      arrive_by: arriveBy,
    }),
  // Starts a planning job. The same idempotency key never starts a second run.
  startPlan: (from: Point, to: Point, arriveBy: string, preferences: string, idempotencyKey: string) =>
    send<PlanJob>("/api/plans", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        from_lon: from.lon,
        from_lat: from.lat,
        to_lon: to.lon,
        to_lat: to.lat,
        arrive_by: arriveBy,
        preferences: preferences.trim(),
        from_label: from.label,
        to_label: to.label,
      }),
    }),
  getPlan: (jobId: string) => send<PlanJob>(`/api/plans/${encodeURIComponent(jobId)}`),
};
