import { useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { newSessionId } from "../lib/format";
import type { SelectedPlace, Suggestion } from "../types";
import { Autocomplete } from "./Autocomplete";

interface Props {
  label: string;
  country: string | null;
  onChange: (place: SelectedPlace | null) => void;
  onError: (message: string) => void;
}

export function PlaceField({ label, country, onChange, onError }: Props) {
  const session = useRef<string | null>(null);
  const version = useRef(0);
  const [status, setStatus] = useState("");

  function sessionId(): string {
    session.current ??= newSessionId();
    return session.current;
  }

  async function select(item: Suggestion) {
    // A Google session ends when a suggestion is picked, so the next search starts a new one.
    const sid = sessionId();
    session.current = null;
    const myVersion = version.current;
    let place: SelectedPlace;
    if (item.lon != null && item.lat != null) {
      place = { label: item.label, lon: item.lon, lat: item.lat };
    } else {
      setStatus("Locating...");
      try {
        const resolved = await api.resolve(item.place_id ?? "", sid);
        place = { label: item.label, lon: resolved.lon, lat: resolved.lat };
      } catch (err) {
        if (myVersion === version.current) {
          setStatus("");
          onError(errorMessage(err));
        }
        return;
      }
    }
    if (myVersion !== version.current) return;
    setStatus(`Selected: ${place.label}`);
    onChange(place);
  }

  function edit() {
    version.current++;
    setStatus("");
    onChange(null);
  }

  return (
    <Autocomplete<Suggestion>
      label={label}
      placeholder={country ? "Type at least 3 letters..." : "Choose a country first"}
      disabled={!country}
      minChars={3}
      delayMs={150}
      status={status}
      search={async (text) => {
        if (!country) return [];
        return (await api.suggest(country, text, sessionId())).suggestions;
      }}
      onSelect={(item) => void select(item)}
      onEdit={edit}
      onError={onError}
    />
  );
}
