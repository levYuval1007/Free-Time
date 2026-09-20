import { filterCountries } from "../lib/countries";
import type { Country } from "../types";
import { Autocomplete } from "./Autocomplete";

interface CountryItem {
  label: string;
  country: Country;
}

interface Props {
  countries: Country[];
  selected: Country | null;
  onChange: (country: Country | null) => void;
  onError: (message: string) => void;
}

export function CountryField({ countries, selected, onChange, onError }: Props) {
  return (
    <Autocomplete<CountryItem>
      label="Country"
      placeholder="Start typing a country..."
      minChars={0}
      delayMs={0}
      openOnFocus
      status={selected ? `Selected: ${selected.name}` : ""}
      search={async (text) =>
        filterCountries(countries, text).map((country) => ({ label: country.name, country }))
      }
      onSelect={(item) => onChange(item.country)}
      onEdit={() => onChange(null)}
      onError={onError}
    />
  );
}
