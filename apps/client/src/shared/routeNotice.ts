import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router";

/**
 * A notice handed over through router state ("saved", "deleted") is shown once. The state is
 * read on arrival and then removed from the history entry with a replace, so reload, back and
 * forward do not show it again. The screen keeps showing it while it stays mounted.
 */
export function useRouteNotice<T>(pick: (state: unknown) => T | null): T | null {
  const location = useLocation();
  const navigate = useNavigate();
  const shown = useRef<T | null>(null);
  const fresh = pick(location.state);
  if (fresh !== null) shown.current = fresh;
  const hasState = fresh !== null;
  useEffect(() => {
    if (!hasState) return;
    navigate(`${location.pathname}${location.search}${location.hash}`, {
      replace: true,
      state: null,
    });
  }, [hasState, location.pathname, location.search, location.hash, navigate]);
  return shown.current;
}

/** Router state `{ [key]: value }`, or any truthy `{ [key]: … }` when no value is given. */
export const stateFlag =
  (key: string, value?: string) =>
  (state: unknown): true | null => {
    const found = (state as Record<string, unknown> | null)?.[key];
    return (value === undefined ? !!found : found === value) ? true : null;
  };
