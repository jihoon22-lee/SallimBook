import { useEffect, useRef } from "react";

/** A manual refresh does not change query identity or discard its last successful data. */
export function useRefreshOnChange(reload: () => Promise<void>, trigger: number) {
  const previous = useRef(trigger);
  useEffect(() => {
    if (previous.current === trigger) return;
    previous.current = trigger;
    void reload();
  }, [reload, trigger]);
}
