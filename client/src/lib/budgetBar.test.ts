import { describe, expect, it } from "vitest";
import type { Budget } from "../types";
import { budgetBarParts, formatMinutes } from "./budgetBar";

const budget = (overrides: Partial<Budget>): Budget => ({
  status: "ok",
  drive_minutes: 50,
  buffer_minutes: 15,
  free_minutes: 95,
  ...overrides,
});

describe("formatMinutes", () => {
  it("uses minutes under an hour", () => {
    expect(formatMinutes(50)).toBe("50 min");
    expect(formatMinutes(0)).toBe("0 min");
  });

  it("uses hours and minutes after that", () => {
    expect(formatMinutes(95)).toBe("1 hr 35 min");
    expect(formatMinutes(120)).toBe("2 hr");
  });

  it("rounds and never goes below zero", () => {
    expect(formatMinutes(49.6)).toBe("50 min");
    expect(formatMinutes(-5)).toBe("0 min");
  });
});

describe("budgetBarParts", () => {
  it("splits the time until the deadline", () => {
    const parts = budgetBarParts(budget({}));
    expect(parts?.drive).toBeCloseTo((50 / 160) * 100);
    expect(parts?.margin).toBeCloseTo((15 / 160) * 100);
    expect(parts?.free).toBeCloseTo((95 / 160) * 100);
  });

  it("adds up to the whole bar", () => {
    const parts = budgetBarParts(budget({ drive_minutes: 37, buffer_minutes: 15, free_minutes: 61 }));
    expect((parts?.drive ?? 0) + (parts?.margin ?? 0) + (parts?.free ?? 0)).toBeCloseTo(100);
  });

  it("shows a trip with almost no free time", () => {
    const parts = budgetBarParts(budget({ status: "go_direct", free_minutes: 10 }));
    expect(parts?.free).toBeCloseTo((10 / 75) * 100);
  });

  it("has nothing to show when the trip cannot be made", () => {
    expect(budgetBarParts(budget({ status: "impossible", free_minutes: 0 }))).toBeNull();
  });
});
