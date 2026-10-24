import { useSyncExternalStore } from "react";
const query = "(min-width: 1000px)";
function subscribe(notify: () => void) {
  const media = window.matchMedia(query);
  media.addEventListener("change", notify);
  return () => media.removeEventListener("change", notify);
}
/** Render one accessible representation; editing state remains outside the responsive list. */
export function useWideLayout() {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}
