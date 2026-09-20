import { useEffect, useId, useState } from "react";
import { presetSlot, timeSlots } from "../lib/arrival";

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
  const today = slots.filter((slot) => !slot.tomorrow);
  const tomorrow = slots.filter((slot) => slot.tomorrow);
  const presets = PRESETS.map((preset) => ({ ...preset, slot: presetSlot(now, preset.hours) }));

  return (
    <div className="form-group">
      <label htmlFor={selectId}>Arrive by (optional)</label>
      <div className="chips" role="group" aria-label="Quick arrival times">
        {presets.map(({ label, hours, slot }) => {
          const active = value === slot.value;
          return (
            <button
              key={hours}
              type="button"
              className={`chip${active ? " active" : ""}`}
              aria-pressed={active}
              onClick={() => onChange(active ? "" : slot.value)}
            >
              {label}
              <span className="chip-time">
                {slot.time}
                {slot.tomorrow ? " tomorrow" : ""}
              </span>
            </button>
          );
        })}
      </div>
      <select id={selectId} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">No arrival time</option>
        {value !== "" && !slots.some((slot) => slot.value === value) && (
          <option value={value}>{value.slice(11)} (passed)</option>
        )}
        {today.length > 0 && (
          <optgroup label="Today">
            {today.map((slot) => (
              <option key={slot.value} value={slot.value}>
                {slot.time}
              </option>
            ))}
          </optgroup>
        )}
        {tomorrow.length > 0 && (
          <optgroup label="Tomorrow">
            {tomorrow.map((slot) => (
              <option key={slot.value} value={slot.value}>
                {slot.time} (tomorrow)
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </div>
  );
}
