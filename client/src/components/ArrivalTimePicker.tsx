import { useEffect, useRef, useState } from "react";
import { presetSlot } from "../lib/arrival";
import {
  HOURS,
  MINUTES,
  STEP_MINUTES,
  clampSelection,
  dayLabels,
  describeValue,
  initialSelection,
  selectionToValue,
  type Selection,
} from "../lib/wheel";
import { WheelColumn } from "./WheelColumn";

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
  const [now, setNow] = useState(() => new Date());
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const presets = PRESETS.map((preset) => ({ ...preset, slot: presetSlot(now, preset.hours) }));
  const passed = value !== "" && new Date(value) <= now;

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  return (
    <div className="form-group">
      <span className="field-label" id="arrive-label">
        Arrive by (optional)
      </span>
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
      <button
        ref={trigger}
        type="button"
        className="time-trigger"
        aria-labelledby="arrive-label"
        aria-haspopup="dialog"
        onClick={() => {
          setNow(new Date());
          setOpen(true);
        }}
      >
        {value === "" ? "No arrival time" : `${describeValue(value, now)}${passed ? " (passed)" : ""}`}
        <span aria-hidden="true" className="time-trigger-action">
          {value === "" ? "Choose" : "Change"}
        </span>
      </button>
      {open && (
        <TimeDialog
          now={now}
          value={value}
          onCancel={close}
          onDone={(next) => {
            onChange(next);
            close();
          }}
        />
      )}
    </div>
  );
}

interface DialogProps {
  now: Date;
  value: string;
  onCancel: () => void;
  onDone: (value: string) => void;
}

function TimeDialog({ now, value, onCancel, onDone }: DialogProps) {
  const [selection, setSelection] = useState<Selection>(() => initialSelection(value, now));
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.focus();
  }, []);

  // Every move goes through clampSelection, so the drums cannot rest on a time that has passed.
  const choose = (change: Partial<Selection>) => setSelection((current) => clampSelection({ ...current, ...change }, now));
  const chosen = selectionToValue(selection, now);

  return (
    <div className="dialog-backdrop" onClick={onCancel}>
      <div
        ref={panel}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="arrive-dialog-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel();
        }}
      >
        <h2 id="arrive-dialog-title">Arrive by</h2>
        <div className="wheel-columns">
          <WheelColumn
            className="wheel-day"
            label="Day"
            items={dayLabels(now)}
            index={selection.day}
            onChange={(day) => choose({ day })}
          />
          <WheelColumn label="Hour" items={HOURS} index={selection.hour} onChange={(hour) => choose({ hour })} />
          <WheelColumn
            label="Minute"
            items={MINUTES}
            index={selection.minute / STEP_MINUTES}
            onChange={(step) => choose({ minute: step * STEP_MINUTES })}
          />
        </div>
        <p className="dialog-summary" aria-live="polite">
          {describeValue(chosen, now)}
        </p>
        <div className="dialog-actions">
          {value !== "" && (
            <button type="button" className="text-button muted" onClick={() => onDone("")}>
              No arrival time
            </button>
          )}
          <span className="dialog-spacer" />
          <button type="button" className="text-button" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="text-button strong" onClick={() => onDone(chosen)}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
