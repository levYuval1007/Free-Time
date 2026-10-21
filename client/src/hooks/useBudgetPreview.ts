import { useEffect, useState } from "react";
import { api } from "../api";
import { parseArriveBy } from "../lib/format";
import type { Budget, SelectedPlace } from "../types";

export type BudgetPreview = { kind: "idle" } | { kind: "loading" } | { kind: "ready"; budget: Budget } | { kind: "error" };

const DEBOUNCE_MS = 400;

// The free time for the trip as entered so far. It asks for the same route "Plan my trip" asks for, which the server
// keeps for two minutes, so pressing the button soon afterwards costs no second routing request.
export function useBudgetPreview(from: SelectedPlace | null, to: SelectedPlace | null, arrive: string): BudgetPreview {
  const [preview, setPreview] = useState<BudgetPreview>({ kind: "idle" });

  useEffect(() => {
    const arrival = parseArriveBy(arrive);
    if (!from || !to || arrival.kind !== "ok") {
      setPreview({ kind: "idle" });
      return;
    }
    let current = true;
    setPreview({ kind: "loading" });
    const timer = window.setTimeout(() => {
      api
        .route(from, to, arrival.iso)
        .then((route) => {
          if (current) setPreview(route.budget ? { kind: "ready", budget: route.budget } : { kind: "idle" });
        })
        .catch(() => {
          if (current) setPreview({ kind: "error" });
        });
    }, DEBOUNCE_MS);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [from, to, arrive]);

  return preview;
}
