import { describe, expect, it } from "vitest";
import { clockTime, formatDistance, parseArriveBy, todayHours } from "./format";

const now = new Date(2026, 8, 20, 12, 0, 0);

describe("parseArriveBy", () => {
  it("returns none for an empty value", () => {
    expect(parseArriveBy("", now)).toEqual({ kind: "none" });
  });

  it("returns an ISO time for a later time today", () => {
    expect(parseArriveBy("2026-09-20T15:30", now)).toEqual({
      kind: "ok",
      iso: new Date(2026, 8, 20, 15, 30).toISOString(),
    });
  });

  it("accepts a time tomorrow", () => {
    expect(parseArriveBy("2026-09-21T01:00", now)).toEqual({
      kind: "ok",
      iso: new Date(2026, 8, 21, 1, 0).toISOString(),
    });
  });

  it("rejects a time that already passed", () => {
    expect(parseArriveBy("2026-09-20T11:00", now).kind).toBe("error");
  });

  it("rejects exactly now", () => {
    expect(parseArriveBy("2026-09-20T12:00", now).kind).toBe("error");
  });

  it("rejects text that is not a date", () => {
    expect(parseArriveBy("soon", now)).toEqual({ kind: "error", message: "Arrival time is not valid." });
  });
});

describe("clockTime", () => {
  it("shows only the time for today", () => {
    expect(clockTime(new Date(2026, 8, 20, 18, 5).toISOString(), now)).toBe("18:05");
  });

  it("marks times on the next day", () => {
    expect(clockTime(new Date(2026, 8, 21, 1, 30).toISOString(), now)).toBe("01:30 tomorrow");
  });

  it("shows the date for later days", () => {
    expect(clockTime(new Date(2026, 8, 23, 9, 0).toISOString(), now)).toContain("09:00 (");
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
