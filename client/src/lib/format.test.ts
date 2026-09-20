import { describe, expect, it } from "vitest";
import { formatDistance, parseArriveBy, todayHours } from "./format";

const now = new Date(2026, 8, 20, 12, 0, 0);

describe("parseArriveBy", () => {
  it("returns none for an empty value", () => {
    expect(parseArriveBy("", now)).toEqual({ kind: "none" });
  });

  it("returns an ISO time for a later time today", () => {
    expect(parseArriveBy("15:30", now)).toEqual({
      kind: "ok",
      iso: new Date(2026, 8, 20, 15, 30).toISOString(),
    });
  });

  it("rejects a time that already passed", () => {
    expect(parseArriveBy("11:00", now).kind).toBe("error");
  });

  it("rejects exactly now", () => {
    expect(parseArriveBy("12:00", now).kind).toBe("error");
  });
});

describe("formatDistance", () => {
  it("uses meters below one kilometer", () => {
    expect(formatDistance(327.4)).toBe("327 m");
  });

  it("uses kilometers with one decimal from one kilometer", () => {
    expect(formatDistance(8300)).toBe("8.3 km");
  });
});

describe("todayHours", () => {
  const week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  it("maps Sunday to the last entry", () => {
    expect(todayHours(week, new Date(2026, 8, 20))).toBe("Sun");
  });

  it("maps Monday to the first entry", () => {
    expect(todayHours(week, new Date(2026, 8, 21))).toBe("Mon");
  });

  it("reports unknown hours when the list is missing or incomplete", () => {
    expect(todayHours(undefined)).toBe("hours unknown");
    expect(todayHours(["Mon"])).toBe("hours unknown");
  });
});
