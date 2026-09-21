export interface Coordinates {
  lat: number;
  lon: number;
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

export interface PlannedStop {
  id: string;
  name: string;
  lat: number;
  lon: number;
  primary_type?: string;
  rating?: number;
  rating_count?: number;
  maps_uri?: string;
  weekday_text?: string[];
  drive_minutes: number;
  arrive: string;
  leave: string;
  visit_minutes: number;
  why?: string;
}

export type PlanReason = "impossible" | "not_enough_time" | "no_candidates" | "no_feasible_plan";

export interface PlanResult {
  budget: Budget;
  stops: PlannedStop[];
  reason?: PlanReason;
  depart?: string;
  arrive_destination?: string;
  final_drive_minutes?: number;
  geometry?: [number, number][];
  steps?: RouteStep[];
  candidates_considered: number;
  source?: "agent" | "baseline";
  summary?: string;
}

export interface TripResult {
  from: SelectedPlace;
  to: SelectedPlace;
  arriveBy?: string;
  route: RouteResult;
  plan?: PlanResult;
  planError?: string;
  // Set when the AI planner could not finish and the basic planner was used instead.
  degradedReason?: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "degraded" | "failed";

export interface PlanJob {
  job_id: string;
  status: JobStatus;
  stage?: string;
  result?: PlanResult;
  error?: string;
  degraded_reason?: string;
}
