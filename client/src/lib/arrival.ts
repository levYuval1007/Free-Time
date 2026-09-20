const SLOT_MINUTES = 15;
const WINDOW_HOURS = 24;

export interface Slot {
  value: string;
  time: string;
  tomorrow: boolean;
}

const pad = (n: number) => String(n).padStart(2, "0");

// Local date-time without an offset (the datetime-local format): new Date(value) reads it as local time.
export function toValue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function ceilToSlot(date: Date): Date {
  const result = new Date(date);
  const hadSeconds = result.getSeconds() > 0 || result.getMilliseconds() > 0;
  result.setSeconds(0, 0);
  const remainder = result.getMinutes() % SLOT_MINUTES;
  if (remainder !== 0) {
    result.setMinutes(result.getMinutes() + SLOT_MINUTES - remainder);
  } else if (hadSeconds) {
    result.setMinutes(result.getMinutes() + SLOT_MINUTES);
  }
  return result;
}

function toSlot(date: Date, now: Date): Slot {
  return {
    value: toValue(date),
    time: `${pad(date.getHours())}:${pad(date.getMinutes())}`,
    tomorrow: !isSameDay(date, now),
  };
}

export function nextSlot(now: Date): Date {
  return ceilToSlot(new Date(now.getTime() + 1));
}

export function timeSlots(now: Date): Slot[] {
  const end = now.getTime() + WINDOW_HOURS * 3_600_000;
  const slots: Slot[] = [];
  const cursor = nextSlot(now);
  while (cursor.getTime() <= end) {
    slots.push(toSlot(cursor, now));
    cursor.setTime(cursor.getTime() + SLOT_MINUTES * 60_000);
  }
  return slots;
}

export function presetSlot(now: Date, hours: number): Slot {
  return toSlot(ceilToSlot(new Date(now.getTime() + hours * 3_600_000)), now);
}
