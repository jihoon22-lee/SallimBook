import { useCallback, useEffect, useRef } from "react";
import { ApiError } from "../../platform/api";

/** At most one ceremony per mounted form; leaving it cancels browser and fetch work. */
export function useAuthCeremony() {
  const active = useRef<AbortController | null>(null);
  const cancel = useCallback(() => {
    active.current?.abort();
    active.current = null;
  }, []);
  useEffect(() => {
    const hidden = () => {
      if (document.visibilityState !== "visible") cancel();
    };
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("pagehide", cancel);
    return () => {
      cancel();
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("pagehide", cancel);
    };
  }, [cancel]);
  const run = useCallback(async <T>(action: (signal: AbortSignal) => Promise<T>): Promise<T> => {
    if (active.current) throw new ApiError(0, "REQUEST_CANCELLED");
    const controller = new AbortController();
    active.current = controller;
    try {
      return await action(controller.signal);
    } finally {
      if (active.current === controller) active.current = null;
    }
  }, []);
  return { run, cancel };
}
