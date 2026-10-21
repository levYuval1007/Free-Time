import { toValue } from "./arrival";

export const STEP_MINUTES = 5;
export const DAY_COUNT = 7;

// A choice on the three wheels: how many days from today, the hour and the minute (a multiple of STEP_MINUTES).
export interface Selection {
  day: number;
  hour: number;
  minute: number;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n: number) => String(n).padStart(2, "0");

export const HOURS = Array.from({ length: 24 }, (_, hour) => pad(hour));
export const MINUTES = Array.from({ length: 60 / STEP_MINUTES }, (_, step) => pad(step * STEP_MINUTES));

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function daysBetween(from: Date, to: Date): number {
  return Math.round((startOfDay(to).getTime() - startOfDay(from).getTime()) / 86_400_000);
}

function ceilToStep(date: Date): Date {
  const result = new Date(date);
  const hadSeconds = result.getSeconds() > 0 || result.getMilliseconds() > 0;
  result.setSeconds(0, 0);
  const remainder = result.getMinutes() % STEP_MINUTES;
  if (remainder !== 0) {
    result.setMinutes(result.getMinutes() + STEP_MINUTES - remainder);
  } else if (hadSeconds) {
    result.setMinutes(result.getMinutes() + STEP_MINUTES);
  }
  return result;
}

// The first time that can be chosen: the next step after now (never now itself).
export function earliest(now: Date): Date {
  return ceilToStep(new Date(now.getTime() + 1));
}

export function selectionToDate(selection: Selection, now: Date): Date {
  const today = startOfDay(now);
  return new Date(today.getFullYear(), today.getMonth(), today.getDate() + selection.day, selection.hour, selection.minute);
}

export function dateToSelection(date: Date, now: Date): Selection {
  return {
    day: Math.min(Math.max(daysBetween(now, date), 0), DAY_COUNT - 1),
    hour: date.getHours(),
    minute: Math.floor(date.getMinutes() / STEP_MINUTES) * STEP_MINUTES,
  };
}

// A time in the past moves forward to the earliest choosable time, so the wheels can never rest on one.
export function clampSelection(selection: Selection, now: Date): Selection {
  const first = earliest(now);
  return selectionToDate(selection, now) < first ? dateToSelection(first, now) : selection;
}

// Where the wheels start: the current value when it is still ahead, otherwise one hour from now.
export function initialSelection(value: string, now: Date): Selection {
  const parsed = value ? new Date(value) : null;
  const usable = parsed !== null && !Number.isNaN(parsed.getTime()) ? parsed : ceilToStep(new Date(now.getTime() + 3_600_000));
  return clampSelection(dateToSelection(usable, now), now);
}

export function selectionToValue(selection: Selection, now: Date): string {
  return toValue(selectionToDate(selection, now));
}

export function dayLabel(day: number, now: Date): string {
  if (day === 0) return "Today";
  if (day === 1) return "Tomorrow";
  const date = selectionToDate({ day, hour: 12, minute: 0 }, now);
  return `${WEEKDAYS[date.getDay()]} ${MONTHS[date.getMonth()]} ${date.getDate()}`;
}

export const dayLabels = (now: Date): string[] => Array.from({ length: DAY_COUNT }, (_, day) => dayLabel(day, now));

// "Today 18:35", "Tomorrow 09:00", "Fri Oct 23 09:00" for a datetime-local value.
export function describeValue(value: string, now: Date): string {
  const date = new Date(value);
  const days = daysBetween(now, date);
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (days === 0) return `Today ${time}`;
  if (days === 1) return `Tomorrow ${time}`;
  return `${WEEKDAYS[date.getDay()]} ${MONTHS[date.getMonth()]} ${date.getDate()} ${time}`;
}
