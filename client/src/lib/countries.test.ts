import { describe, expect, it } from "vitest";
import type { Country } from "../types";
import { filterCountries } from "./countries";

const countries: Country[] = [
  { code: "IL", name: "Israel" },
  { code: "IR", name: "Iran, Islamic Rep." },
  { code: "IE", name: "Ireland" },
  { code: "NC", name: "New Caledonia" },
];

describe("filterCountries", () => {
  it("puts names that start with the text before names that contain it", () => {
    expect(filterCountries(countries, "ir").map((c) => c.code)).toEqual(["IR", "IE"]);
  });

  it("is case insensitive and trims the text", () => {
    expect(filterCountries(countries, "  ISR ").map((c) => c.code)).toEqual(["IL"]);
  });

  it("returns everything for an empty text", () => {
    expect(filterCountries(countries, "")).toHaveLength(4);
  });

  it("returns nothing when there is no match", () => {
    expect(filterCountries(countries, "zzz")).toEqual([]);
  });

  it("caps the number of results", () => {
    const many = Array.from({ length: 100 }, (_, i) => ({ code: String(i), name: `Land ${i}` }));
    expect(filterCountries(many, "land")).toHaveLength(30);
  });
});
