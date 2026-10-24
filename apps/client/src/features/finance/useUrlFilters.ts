import { useLayoutEffect, useRef } from "react";
import { useNavigationType, useSearchParams } from "react-router";
export function useUrlFilters() {
  const [params, setParams] = useSearchParams();
  const navigationType = useNavigationType();
  const pending = useRef(params);
  const requested = useRef<string | null>(null);
  useLayoutEffect(() => {
    // A previous navigation may commit after the next control has already changed.
    // Only the newest requested URL (or an explicit back/forward) replaces pending input.
    if (
      navigationType === "POP" ||
      requested.current === null ||
      params.toString() === requested.current
    ) {
      pending.current = params;
      requested.current = null;
    }
  }, [params, navigationType]);
  const commit = (next: URLSearchParams) => {
    pending.current = next;
    requested.current = next.toString();
    setParams(next);
  };
  return {
    params,
    filter: (key: string, value: string) => {
      const next = new URLSearchParams(pending.current);
      if (value) next.set(key, value);
      else next.delete(key);
      commit(next);
    },
    reset: () => commit(new URLSearchParams()),
  };
}
