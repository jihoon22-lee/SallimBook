import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, toApiError } from "../../../platform/api";
import { useMounted } from "../../auth/AuthFeedback";

/** A changed payload/version gets a new key; cancelled/ambiguous retries reuse the same key. */
export function useIdempotencyKey(fingerprint: string) {
  const current = useRef<{ fingerprint: string; key: string } | null>(null);
  if (current.current?.fingerprint !== fingerprint)
    current.current = { fingerprint, key: crypto.randomUUID() };
  return current.current.key;
}
export function useMonthCommand() {
  const mounted = useMounted();
  const controller = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const cancel = useCallback(() => {
    controller.current?.abort();
  }, []);
  useEffect(() => {
    window.addEventListener("pagehide", cancel);
    return () => {
      cancel();
      window.removeEventListener("pagehide", cancel);
    };
  }, [cancel]);
  async function run<T>(
    action: (signal: AbortSignal) => Promise<T>,
  ): Promise<{ ok: true; value: T } | { ok: false; error: ApiError }> {
    if (controller.current) return { ok: false, error: new ApiError(0, "REQUEST_CANCELLED") };
    const next = new AbortController();
    controller.current = next;
    setBusy(true);
    setError(null);
    try {
      const value = await action(next.signal);
      if (next.signal.aborted) throw new ApiError(0, "REQUEST_CANCELLED");
      return { ok: true, value };
    } catch (failure) {
      const value = toApiError(failure);
      if (mounted.current) setError(value);
      return { ok: false, error: value };
    } finally {
      if (controller.current === next) controller.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  return { busy, error, setError, run, cancel, mounted };
}
