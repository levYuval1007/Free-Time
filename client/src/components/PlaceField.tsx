import { useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { newSessionId } from "../lib/format";
import type { Coordinates, SelectedPlace, Suggestion } from "../types";
import { Autocomplete } from "./Autocomplete";

const MY_LOCATION = "My location";

interface Props {
  label: string;
  placeholder: string;
  bias: Coordinates | null;
  onChange: (place: SelectedPlace | null) => void;
  onError: (message: string) => void;
  onRequestLocation?: () => Promise<Coordinates>;
}

export function PlaceField({ label, placeholder, bias, onChange, onError, onRequestLocation }: Props) {
  const session = useRef<string | null>(null);
  const version = useRef(0);
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");
  const [committed, setCommitted] = useState<string | null>(null);

  function sessionId(): string {
    session.current ??= newSessionId();
    return session.current;
  }

  async function select(item: Suggestion) {
    // A Google session ends when a suggestion is picked, so the next search starts a new one.
    const sid = sessionId();
    session.current = null;
    const myVersion = version.current;
    setText(item.label);
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
    setStatus("");
    setCommitted(place.label);
    onChange(place);
  }

  async function useMyLocation() {
    if (!onRequestLocation) return;
    const myVersion = ++version.current;
    setStatus("Locating...");
    try {
      const here = await onRequestLocation();
      if (myVersion !== version.current) return;
      setText(MY_LOCATION);
      setCommitted(MY_LOCATION);
      setStatus("");
      onChange({ label: MY_LOCATION, lat: here.lat, lon: here.lon });
    } catch (err) {
      if (myVersion !== version.current) return;
      setStatus("");
      onError(errorMessage(err));
    }
  }

  function edit() {
    version.current++;
    setStatus("");
    setCommitted(null);
    onChange(null);
  }

  return (
    <Autocomplete<Suggestion>
      label={label}
      placeholder={placeholder}
      text={text}
      onTextChange={setText}
      minChars={3}
      delayMs={150}
      status={status}
      committedText={committed}
      adornment={
        onRequestLocation && (
          <button type="button" className="icon-button" aria-label="Use my location" title="Use my location" onClick={() => void useMyLocation()}>
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" strokeWidth="2" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        )
      }
      search={async (query) => (await api.suggest(query, sessionId(), bias)).suggestions}
      onSelect={(item) => void select(item)}
      onEdit={edit}
      onError={onError}
    />
  );
}
