const SLOT_MINUTES = 15;

export function toValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
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

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function nextSlot(now: Date): Date {
  return ceilToSlot(new Date(now.getTime() + 1));
}

export function timeSlots(now: Date): string[] {
  const slots: string[] = [];
  const cursor = nextSlot(now);
  while (isSameDay(cursor, now)) {
    slots.push(toValue(cursor));
    cursor.setMinutes(cursor.getMinutes() + SLOT_MINUTES);
  }
  return slots;
}

export function presetTime(now: Date, hours: number): string | null {
  const target = ceilToSlot(new Date(now.getTime() + hours * 3_600_000));
  return isSameDay(target, now) ? toValue(target) : null;
}
