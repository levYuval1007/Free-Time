import { describe, expect, it } from "vitest";
import { googleMapsUrl } from "./maps";

const from = { lat: 32.08, lon: 34.78 };
const to = { lat: 31.77, lon: 35.21 };

describe("googleMapsUrl", () => {
  it("builds a driving directions link", () => {
    const url = new URL(googleMapsUrl(from, to));
    expect(url.origin + url.pathname).toBe("https://www.google.com/maps/dir/");
    expect(url.searchParams.get("origin")).toBe("32.08,34.78");
    expect(url.searchParams.get("destination")).toBe("31.77,35.21");
    expect(url.searchParams.get("travelmode")).toBe("driving");
    expect(url.searchParams.has("waypoints")).toBe(false);
  });

  it("adds the stops as waypoints in order", () => {
    const url = new URL(googleMapsUrl(from, to, [{ lat: 32.1, lon: 34.8 }, { lat: 31.8, lon: 35.2 }]));
    expect(url.searchParams.get("waypoints")).toBe("32.1,34.8|31.8,35.2");
  });
});
