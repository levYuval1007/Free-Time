import { useCallback, useEffect, useState } from "react";
import type { Coordinates } from "../types";

export function useUserLocation() {
  const [location, setLocation] = useState<Coordinates | null>(null);

  const request = useCallback(
    () =>
      new Promise<Coordinates>((resolve, reject) => {
        if (!navigator.geolocation) {
          reject(new Error("Your browser can't share your location."));
          return;
        }
        navigator.geolocation.getCurrentPosition(
          (position) => {
            const coordinates = { lat: position.coords.latitude, lon: position.coords.longitude };
            setLocation(coordinates);
            resolve(coordinates);
          },
          (err) =>
            reject(
              new Error(
                err.code === err.PERMISSION_DENIED
                  ? "Location permission was denied. Allow it in your browser to use your location."
                  : "Couldn't get your location. Try again.",
              ),
            ),
          { timeout: 10_000, maximumAge: 300_000 },
        );
      }),
    [],
  );

  // Reading the location without a prompt is fine only when the user already allowed it.
  useEffect(() => {
    navigator.permissions
      ?.query({ name: "geolocation" as PermissionName })
      .then((status) => {
        if (status.state === "granted") void request().catch(() => undefined);
      })
      .catch(() => undefined);
  }, [request]);

  return { location, request };
}
