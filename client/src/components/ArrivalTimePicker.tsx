import { useEffect, useId, useState } from "react";
import { presetTime, timeSlots } from "../lib/arrival";

const PRESETS = [
  { label: "In 1 hour", hours: 1 },
  { label: "In 2 hours", hours: 2 },
  { label: "In 3 hours", hours: 3 },
];

interface Props {
  value: string;
  onChange: (value: string) => void;
}

export function ArrivalTimePicker({ value, onChange }: Props) {
  const selectId = useId();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const slots = timeSlots(now);
  const presets = PRESETS.map((preset) => ({ ...preset, time: presetTime(now, preset.hours) })).filter(
    (preset): preset is { label: string; hours: number; time: string } => preset.time !== null,
  );

  return (
    <div className="form-group">
      <label htmlFor={selectId}>Arrive by (optional, today)</label>
      {presets.length > 0 && (
        <div className="chips" role="group" aria-label="Quick arrival times">
          {presets.map((preset) => {
            const active = value === preset.time;
            return (
              <button
                key={preset.hours}
                type="button"
                className={`chip${active ? " active" : ""}`}
                aria-pressed={active}
                onClick={() => onChange(active ? "" : preset.time)}
              >
                {preset.label}
                <span className="chip-time">{preset.time}</span>
              </button>
            );
          })}
        </div>
      )}
      <select id={selectId} value={value} disabled={slots.length === 0} onChange={(e) => onChange(e.target.value)}>
        <option value="">{slots.length === 0 ? "No more times today" : "No arrival time"}</option>
        {value !== "" && !slots.includes(value) && <option value={value}>{value}</option>}
        {slots.map((slot) => (
          <option key={slot} value={slot}>
            {slot}
          </option>
        ))}
      </select>
    </div>
  );
}
