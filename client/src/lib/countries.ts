import type { Country } from "../types";

const MAX_RESULTS = 30;

export function filterCountries(countries: Country[], text: string): Country[] {
  const query = text.trim().toLowerCase();
  const starts = countries.filter((c) => c.name.toLowerCase().startsWith(query));
  const contains = countries.filter(
    (c) => !c.name.toLowerCase().startsWith(query) && c.name.toLowerCase().includes(query),
  );
  return [...starts, ...contains].slice(0, MAX_RESULTS);
}
