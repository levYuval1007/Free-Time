import type {
  Coordinates,
  PlanResult,
  ResolvedPlace,
  RouteResult,
  SuggestResponse,
} from "./types";

export class ApiError extends Error {}

type Params = Record<string, string | number | undefined>;

async function getJson<T>(path: string, params: Params = {}): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const res = await fetch(`${path}?${query}`);
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const message = (body as { error?: string } | null)?.error ?? `Request failed (${res.status})`;
    throw new ApiError(message);
  }
  return body as T;
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export const api = {
  suggest: (q: string, session: string, bias?: Coordinates | null) =>
    getJson<SuggestResponse>("/api/suggest", { q, session, lat: bias?.lat, lon: bias?.lon }),
  resolve: (placeId: string, session: string) =>
    getJson<ResolvedPlace>("/api/places/resolve", { place_id: placeId, session }),
  route: (
    from: { lon: number; lat: number },
    to: { lon: number; lat: number },
    arriveBy?: string,
  ) =>
    getJson<RouteResult>("/api/route", {
      from_lon: from.lon,
      from_lat: from.lat,
      to_lon: to.lon,
      to_lat: to.lat,
      arrive_by: arriveBy,
    }),
  plan: (from: { lon: number; lat: number }, to: { lon: number; lat: number }, arriveBy: string) =>
    getJson<PlanResult>("/api/plan", {
      from_lon: from.lon,
      from_lat: from.lat,
      to_lon: to.lon,
      to_lat: to.lat,
      arrive_by: arriveBy,
    }),
};
