import { describe, expect, it } from "vitest";
import { nextSlot, presetSlot, timeSlots, toValue } from "./arrival";

const at = (hours: number, minutes: number, seconds = 0) => new Date(2026, 8, 20, hours, minutes, seconds);

describe("toValue", () => {
  it("pads every part and keeps the date", () => {
    expect(toValue(new Date(2026, 0, 5, 7, 5))).toBe("2026-01-05T07:05");
  });
});

describe("nextSlot", () => {
  it("rounds up to the next quarter hour", () => {
    expect(toValue(nextSlot(at(12, 7)))).toBe("2026-09-20T12:15");
  });

  it("moves to the following slot when exactly on a quarter hour", () => {
    expect(toValue(nextSlot(at(12, 15)))).toBe("2026-09-20T12:30");
  });

  it("rolls over the hour", () => {
    expect(toValue(nextSlot(at(12, 50)))).toBe("2026-09-20T13:00");
  });
});

describe("timeSlots", () => {
  it("covers the next 24 hours in quarter hours", () => {
    const slots = timeSlots(at(12, 7));
    expect(slots).toHaveLength(96);
    expect(slots[0]).toEqual({ value: "2026-09-20T12:15", time: "12:15", tomorrow: false });
    expect(slots[slots.length - 1]).toEqual({ value: "2026-09-21T12:00", time: "12:00", tomorrow: true });
  });

  it("continues past midnight and marks tomorrow", () => {
    const slots = timeSlots(at(23, 40));
    expect(slots[0]).toEqual({ value: "2026-09-20T23:45", time: "23:45", tomorrow: false });
    expect(slots[1]).toEqual({ value: "2026-09-21T00:00", time: "00:00", tomorrow: true });
  });

  it("starts tomorrow when the next slot is after midnight", () => {
    const slots = timeSlots(at(23, 50));
    expect(slots[0]).toEqual({ value: "2026-09-21T00:00", time: "00:00", tomorrow: true });
    expect(slots).toHaveLength(96);
  });

  it("only contains times later than now, in increasing order", () => {
    const now = at(12, 7);
    const values = timeSlots(now).map((s) => new Date(s.value).getTime());
    expect(values[0]).toBeGreaterThan(now.getTime());
    expect([...values].sort((a, b) => a - b)).toEqual(values);
  });
});

describe("presetSlot", () => {
  it("adds the hours and rounds up to a quarter hour", () => {
    expect(presetSlot(at(12, 7), 1)).toEqual({ value: "2026-09-20T13:15", time: "13:15", tomorrow: false });
  });

  it("keeps an exact quarter hour", () => {
    expect(presetSlot(at(12, 0), 2).time).toBe("14:00");
  });

  it("rounds up when there are leftover seconds", () => {
    expect(presetSlot(at(12, 0, 30), 2).time).toBe("14:15");
  });

  it("crosses midnight instead of disappearing", () => {
    expect(presetSlot(at(22, 30), 3)).toEqual({ value: "2026-09-21T01:30", time: "01:30", tomorrow: true });
  });
});
