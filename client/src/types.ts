export interface Country {
  code: string;
  name: string;
}

export interface Suggestion {
  label: string;
  place_id?: string;
  lon?: number;
  lat?: number;
}

export interface SuggestResponse {
  provider: "google" | "ors";
  suggestions: Suggestion[];
}

export interface ResolvedPlace {
  lat: number;
  lon: number;
  address: string;
}

export interface SelectedPlace {
  label: string;
  lon: number;
  lat: number;
}

export interface RouteStep {
  instruction: string;
  distance: number;
  duration: number;
}

export type BudgetStatus = "ok" | "go_direct" | "impossible";

export interface Budget {
  status: BudgetStatus;
  drive_minutes: number;
  buffer_minutes: number;
  free_minutes: number;
}

export interface RouteResult {
  km: number;
  minutes: number;
  geometry: [number, number][];
  steps: RouteStep[];
  budget?: Budget;
}

export interface NearbyPlace {
  id: string;
  name: string;
  lat: number;
  lon: number;
  types: string[];
  primary_type?: string;
  rating?: number;
  rating_count?: number;
  business_status?: string;
  weekday_text?: string[];
  maps_uri?: string;
}

export interface NearbyResult {
  places: NearbyPlace[];
  latency_ms: number;
  stats: { requests: number; errors: number; estimated_cost_usd: number };
}
