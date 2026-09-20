import { useEffect, useState } from "react";
import { api, errorMessage } from "./api";
import { CountryField } from "./components/CountryField";
import { PlaceField } from "./components/PlaceField";
import { ResultCard } from "./components/ResultCard";
import { parseArriveBy } from "./lib/format";
import type { Country, RouteResult, SelectedPlace } from "./types";

interface CalculatedRoute {
  id: number;
  from: SelectedPlace;
  to: SelectedPlace;
  data: RouteResult;
}

export default function App() {
  const [countries, setCountries] = useState<Country[]>([]);
  const [country, setCountry] = useState<Country | null>(null);
  const [from, setFrom] = useState<SelectedPlace | null>(null);
  const [to, setTo] = useState<SelectedPlace | null>(null);
  const [arrive, setArrive] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CalculatedRoute | null>(null);

  useEffect(() => {
    api
      .countries()
      .then(setCountries)
      .catch((err) => setError(errorMessage(err)));
  }, []);

  function changeCountry(next: Country | null) {
    setCountry(next);
    setFrom(null);
    setTo(null);
    setResult(null);
    if (next) setError(null);
  }

  async function calculate() {
    if (!from || !to) return;
    setError(null);
    setResult(null);
    const arrival = parseArriveBy(arrive);
    if (arrival.kind === "error") {
      setError(arrival.message);
      return;
    }
    setLoading(true);
    try {
      const data = await api.route(from, to, arrival.kind === "ok" ? arrival.iso : undefined);
      setResult({ id: Date.now(), from, to, data });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card">
      <h1>🚗 Travel Time</h1>

      {error && <div className="error">{error}</div>}

      <CountryField countries={countries} selected={country} onChange={changeCountry} onError={setError} />

      <PlaceField
        key={`from-${country?.code ?? "none"}`}
        label="Starting location"
        country={country?.code ?? null}
        onChange={(place) => {
          setFrom(place);
          if (place) setError(null);
        }}
        onError={setError}
      />
      <PlaceField
        key={`to-${country?.code ?? "none"}`}
        label="Destination"
        country={country?.code ?? null}
        onChange={(place) => {
          setTo(place);
          if (place) setError(null);
        }}
        onError={setError}
      />

      <div className="form-group">
        <label htmlFor="arrive">Arrive by (optional, today)</label>
        <input id="arrive" type="time" value={arrive} onChange={(e) => setArrive(e.target.value)} />
      </div>

      <button disabled={!from || !to || loading} onClick={() => void calculate()}>
        Calculate
      </button>

      {loading && <div className="loading">Loading...</div>}
      {result && <ResultCard key={result.id} from={result.from} to={result.to} data={result.data} />}
    </div>
  );
}
