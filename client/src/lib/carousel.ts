import type { Coordinates, PlannedStop } from "../types";

// Cards are equally spaced and snap to the centre, so the scroll position maps linearly to a card index.
export function indexFromScroll(scrollLeft: number, maxScroll: number, count: number): number {
  if (count <= 1 || maxScroll <= 0) return 0;
  const index = Math.round((scrollLeft / maxScroll) * (count - 1));
  return Math.min(count - 1, Math.max(0, index));
}

// Card 0 is the overview (whole route), cards 1..n are the stops, and the last card is the destination.
export function focusPointFor(index: number, stops: PlannedStop[], destination: Coordinates): Coordinates | null {
  if (index <= 0) return null;
  if (index <= stops.length) return stops[index - 1];
  return destination;
}

export function minutesBeforeDeadline(arriveDestination: string | undefined, arriveBy: string): number | null {
  if (!arriveDestination) return null;
  return Math.round((new Date(arriveBy).getTime() - new Date(arriveDestination).getTime()) / 60_000);
}
