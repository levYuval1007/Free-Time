import { describe, expect, it } from "vitest";
import { nextSlot, presetTime, timeSlots, toValue } from "./arrival";

const at = (hours: number, minutes: number, seconds = 0) => new Date(2026, 8, 20, hours, minutes, seconds);

describe("toValue", () => {
  it("pads hours and minutes", () => {
    expect(toValue(at(7, 5))).toBe("07:05");
  });
});

describe("nextSlot", () => {
  it("rounds up to the next quarter hour", () => {
    expect(toValue(nextSlot(at(12, 7)))).toBe("12:15");
  });

  it("moves to the following slot when exactly on a quarter hour", () => {
    expect(toValue(nextSlot(at(12, 15)))).toBe("12:30");
  });

  it("rolls over the hour", () => {
    expect(toValue(nextSlot(at(12, 50)))).toBe("13:00");
  });
});

describe("timeSlots", () => {
  it("lists quarter hours from the next slot until 23:45", () => {
    const slots = timeSlots(at(12, 7));
    expect(slots[0]).toBe("12:15");
    expect(slots[1]).toBe("12:30");
    expect(slots[slots.length - 1]).toBe("23:45");
    expect(slots).toHaveLength(47);
  });

  it("is empty when the next slot is already tomorrow", () => {
    expect(timeSlots(at(23, 50))).toEqual([]);
  });

  it("still offers 23:45 at 23:40", () => {
    expect(timeSlots(at(23, 40))).toEqual(["23:45"]);
  });

  it("only contains times later than now", () => {
    const now = at(12, 7);
    for (const slot of timeSlots(now)) {
      const [hours, minutes] = slot.split(":").map(Number);
      expect(at(hours, minutes).getTime()).toBeGreaterThan(now.getTime());
    }
  });
});

describe("presetTime", () => {
  it("adds the hours and rounds up to a quarter hour", () => {
    expect(presetTime(at(12, 7), 1)).toBe("13:15");
  });

  it("keeps an exact quarter hour", () => {
    expect(presetTime(at(12, 0), 2)).toBe("14:00");
  });

  it("rounds up when there are leftover seconds", () => {
    expect(presetTime(at(12, 0, 30), 2)).toBe("14:15");
  });

  it("returns null when the time falls on another day", () => {
    expect(presetTime(at(22, 30), 3)).toBeNull();
  });
});
