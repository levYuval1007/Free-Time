import { ApiError } from "../api";
import type { PlanJob } from "../types";

export class PollCancelled extends Error {
  constructor() {
    super("Planning was cancelled.");
  }
}

export interface PollOptions {
  intervalMs?: number;
  maxMs?: number;
  maxFailures?: number;
  onStage?: (stage: string | undefined) => void;
  isCancelled?: () => boolean;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

const TERMINAL = new Set(["succeeded", "degraded", "failed"]);

// Asks for the job until it finishes. Network hiccups are retried a few times; an unknown job (the server
// restarted or the plan expired) and a run that takes too long stop right away.
export async function pollJob(get: () => Promise<PlanJob>, options: PollOptions = {}): Promise<PlanJob> {
  const {
    intervalMs = 1500,
    maxMs = 120_000,
    maxFailures = 3,
    onStage,
    isCancelled = () => false,
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now = Date.now,
  } = options;
  const started = now();
  let failures = 0;

  for (;;) {
    if (isCancelled()) throw new PollCancelled();
    try {
      const job = await get();
      failures = 0;
      onStage?.(job.stage);
      if (TERMINAL.has(job.status)) return job;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) throw err;
      failures += 1;
      if (failures > maxFailures) throw err;
    }
    if (now() - started > maxMs) throw new Error("Planning is taking too long. Please try again.");
    await sleep(intervalMs * Math.max(1, failures));
  }
}
