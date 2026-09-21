import { describe, expect, it } from "vitest";
import { ApiError } from "../api";
import type { PlanJob } from "../types";
import { PollCancelled, pollJob } from "./polling";

const job = (status: PlanJob["status"], stage?: string): PlanJob => ({ job_id: "j", status, stage });
const noSleep = () => Promise.resolve();

function script(...items: (PlanJob | Error)[]) {
  const queue = [...items];
  let calls = 0;
  return {
    get calls() {
      return calls;
    },
    get: async () => {
      calls += 1;
      const next = queue.shift();
      if (!next) throw new Error("script ran out");
      if (next instanceof Error) throw next;
      return next;
    },
  };
}

describe("pollJob", () => {
  it("polls until the job finishes and reports the stages", async () => {
    const source = script(job("queued"), job("running", "Searching for places"), job("succeeded"));
    const stages: (string | undefined)[] = [];
    const done = await pollJob(source.get, { sleep: noSleep, onStage: (s) => stages.push(s) });
    expect(done.status).toBe("succeeded");
    expect(source.calls).toBe(3);
    expect(stages).toEqual([undefined, "Searching for places", undefined]);
  });

  it("returns degraded and failed jobs as finished", async () => {
    expect((await pollJob(script(job("degraded")).get, { sleep: noSleep })).status).toBe("degraded");
    expect((await pollJob(script(job("failed")).get, { sleep: noSleep })).status).toBe("failed");
  });

  it("retries a network error and carries on", async () => {
    const source = script(new TypeError("offline"), job("running"), job("succeeded"));
    expect((await pollJob(source.get, { sleep: noSleep })).status).toBe("succeeded");
  });

  it("gives up after too many failures in a row", async () => {
    const error = new TypeError("offline");
    const source = script(error, error, error, error);
    await expect(pollJob(source.get, { sleep: noSleep, maxFailures: 3 })).rejects.toBe(error);
    expect(source.calls).toBe(4);
  });

  it("does not retry an unknown job", async () => {
    const source = script(new ApiError("gone", 404), job("succeeded"));
    await expect(pollJob(source.get, { sleep: noSleep })).rejects.toThrow("gone");
    expect(source.calls).toBe(1);
  });

  it("stops when it takes too long", async () => {
    let clock = 0;
    const source = script(job("running"), job("running"), job("running"), job("running"));
    await expect(
      pollJob(source.get, { sleep: noSleep, maxMs: 2500, now: () => (clock += 1000) }),
    ).rejects.toThrow("taking too long");
  });

  it("stops when cancelled", async () => {
    let cancelled = false;
    const source = script(job("running"), job("running"));
    const promise = pollJob(source.get, {
      sleep: async () => {
        cancelled = true;
      },
      isCancelled: () => cancelled,
    });
    await expect(promise).rejects.toBeInstanceOf(PollCancelled);
    expect(source.calls).toBe(1);
  });
});
