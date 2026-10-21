import { useEffect, useLayoutEffect, useRef, useState } from "react";

// Keep equal to --wheel-item in styles.css.
const ITEM_HEIGHT = 44;
const SETTLE_MS = 110;

interface Props {
  label: string;
  items: string[];
  index: number;
  onChange: (index: number) => void;
  className?: string;
}

// One drum: scroll (or swipe) until an item rests in the middle band, click an item, or use the arrow keys.
export function WheelColumn({ label, items, index, onChange, className = "" }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const settleTimer = useRef<number>();
  const mounted = useRef(false);
  const [settled, setSettled] = useState(0);

  // Bring the drum to the chosen item. Runs again after every settle, so a choice the parent moved elsewhere (a time in
  // the past) pulls the drum back even though the index itself did not change.
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const target = index * ITEM_HEIGHT;
    if (Math.abs(element.scrollTop - target) > 1) {
      element.scrollTo({ top: target, behavior: mounted.current ? "smooth" : "auto" });
    }
    mounted.current = true;
  }, [index, settled]);

  useEffect(() => () => window.clearTimeout(settleTimer.current), []);

  function onScroll() {
    window.clearTimeout(settleTimer.current);
    settleTimer.current = window.setTimeout(() => {
      const element = ref.current;
      if (!element) return;
      const chosen = Math.min(items.length - 1, Math.max(0, Math.round(element.scrollTop / ITEM_HEIGHT)));
      if (chosen !== index) onChange(chosen);
      setSettled((count) => count + 1);
    }, SETTLE_MS);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    onChange(Math.min(items.length - 1, Math.max(0, index + step)));
  }

  return (
    <div
      ref={ref}
      className={`wheel ${className}`.trim()}
      role="listbox"
      aria-label={label}
      tabIndex={0}
      onScroll={onScroll}
      onKeyDown={onKeyDown}
    >
      {items.map((item, position) => (
        <div
          key={item}
          role="option"
          aria-selected={position === index}
          className={`wheel-item${position === index ? " selected" : ""}`}
          onClick={() => onChange(position)}
        >
          {item}
        </div>
      ))}
    </div>
  );
}
