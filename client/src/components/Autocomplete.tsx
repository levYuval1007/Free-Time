import { useEffect, useId, useRef, useState } from "react";
import { errorMessage } from "../api";

interface Item {
  label: string;
}

interface Props<T extends Item> {
  label: string;
  placeholder: string;
  disabled?: boolean;
  minChars: number;
  delayMs: number;
  openOnFocus?: boolean;
  status?: string;
  search: (text: string) => Promise<T[]>;
  onSelect: (item: T) => void;
  onEdit: () => void;
  onError: (message: string) => void;
}

export function Autocomplete<T extends Item>(props: Props<T>) {
  const { label, placeholder, disabled, minChars, delayMs, openOnFocus, status } = props;
  const inputId = useId();
  const [text, setText] = useState("");
  const [items, setItems] = useState<T[]>([]);
  const [open, setOpen] = useState(false);
  const typed = useRef(false);
  const requestId = useRef(0);
  const latest = useRef(props);
  latest.current = props;

  async function runSearch(query: string) {
    const id = ++requestId.current;
    try {
      const found = await latest.current.search(query);
      if (id !== requestId.current) return;
      setItems(found);
      setOpen(found.length > 0);
    } catch (err) {
      if (id === requestId.current) latest.current.onError(errorMessage(err));
    }
  }

  useEffect(() => {
    if (!typed.current) return;
    requestId.current++;
    const query = text.trim();
    if (query.length < minChars) {
      setItems([]);
      setOpen(false);
      return;
    }
    const timer = setTimeout(() => void runSearch(query), delayMs);
    return () => clearTimeout(timer);
  }, [text, minChars, delayMs]);

  function pick(item: T) {
    typed.current = false;
    requestId.current++;
    setText(item.label);
    setItems([]);
    setOpen(false);
    props.onSelect(item);
  }

  return (
    <div className="form-group">
      <label htmlFor={inputId}>{label}</label>
      <div className="combo">
        <input
          id={inputId}
          type="text"
          value={text}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          onChange={(e) => {
            typed.current = true;
            setText(e.target.value);
            props.onEdit();
          }}
          onFocus={() => {
            if (openOnFocus && !status) {
              typed.current = true;
              void runSearch(text.trim());
            }
          }}
          onBlur={() => setOpen(false)}
        />
        {open && (
          <div className="suggestions">
            {items.map((item, index) => (
              <div
                key={`${item.label}-${index}`}
                className="suggestion"
                dir="auto"
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(item);
                }}
              >
                {item.label}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="selected">{status}</div>
    </div>
  );
}
