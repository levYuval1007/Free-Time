import { describe, expect, it } from "vitest";
import type { PlannedStop } from "../types";
import { focusPointFor, indexFromScroll, minutesBeforeDeadline } from "./carousel";

const stop = (lat: number): PlannedStop => ({
  id: String(lat),
  name: "s",
  lat,
  lon: 0,
  drive_minutes: 5,
  arrive: "",
  leave: "",
  visit_minutes: 30,
});

describe("indexFromScroll", () => {
  it("maps scroll positions to the nearest card", () => {
    expect(indexFromScroll(0, 300, 4)).toBe(0);
    expect(indexFromScroll(100, 300, 4)).toBe(1);
    expect(indexFromScroll(140, 300, 4)).toBe(1);
    expect(indexFromScroll(300, 300, 4)).toBe(3);
  });

  it("handles a single card and clamps", () => {
    expect(indexFromScroll(50, 0, 1)).toBe(0);
    expect(indexFromScroll(999, 300, 4)).toBe(3);
    expect(indexFromScroll(-5, 300, 4)).toBe(0);
  });
});

describe("focusPointFor", () => {
  const stops = [stop(1), stop(2)];
  const destination = { lat: 9, lon: 9 };

  it("shows the whole route on the overview card", () => {
    expect(focusPointFor(0, stops, destination)).toBeNull();
  });

  it("focuses a stop, then the destination on the last card", () => {
    expect(focusPointFor(1, stops, destination)).toBe(stops[0]);
    expect(focusPointFor(2, stops, destination)).toBe(stops[1]);
    expect(focusPointFor(3, stops, destination)).toBe(destination);
  });
});

describe("minutesBeforeDeadline", () => {
  it("returns the spare minutes", () => {
    expect(minutesBeforeDeadline("2026-01-01T10:00:00Z", "2026-01-01T10:20:00Z")).toBe(20);
  });
  it("returns null without an arrival", () => {
    expect(minutesBeforeDeadline(undefined, "2026-01-01T10:20:00Z")).toBeNull();
  });
});
