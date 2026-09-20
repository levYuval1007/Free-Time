import { describe, expect, it } from "vitest";
import type { Budget } from "../types";
import { budgetMessage, planReasonMessage } from "./budgetText";

const budget = (overrides: Partial<Budget>): Budget => ({
  status: "ok",
  drive_minutes: 55,
  buffer_minutes: 15,
  free_minutes: 109,
  ...overrides,
});

describe("budgetMessage", () => {
  it("describes free time when there is enough", () => {
    expect(budgetMessage(budget({}))).toBe("You have 109 free minutes (drive 55 min + 15 min buffer).");
  });

  it("uses the singular for one minute", () => {
    expect(budgetMessage(budget({ status: "go_direct", free_minutes: 1 }))).toBe(
      "Only 1 free minute after the drive and buffer - head straight there.",
    );
  });

  it("uses the plural for zero minutes", () => {
    expect(budgetMessage(budget({ status: "go_direct", free_minutes: 0 }))).toContain("Only 0 free minutes");
  });

  it("says arriving is impossible", () => {
    expect(budgetMessage(budget({ status: "impossible", free_minutes: 0 }))).toBe(
      "You can't arrive by then, even by driving straight there.",
    );
  });
});

describe("planReasonMessage", () => {
  it("explains every reason in plain words", () => {
    for (const reason of ["impossible", "not_enough_time", "no_candidates", "no_feasible_plan"] as const) {
      expect(planReasonMessage(reason).length).toBeGreaterThan(20);
    }
  });

  it("suggests heading straight there when there is no free time", () => {
    expect(planReasonMessage("not_enough_time")).toContain("head straight there");
  });
});
