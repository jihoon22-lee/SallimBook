import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, toApiError } from "../../../platform/api";
import { useMounted } from "../../auth/AuthFeedback";
import { rememberFocus } from "../../../shared/focusKeeper";

/** True when the server may have saved the request although no answer arrived. */
export const outcomeUnknown = (error: ApiError) => error.status === 0 || error.status >= 500;

/**
 * A changed payload/version gets a new key; cancelled/ambiguous retries reuse the same key.
 * While `hold` is set (the last save may have reached the server), an edited payload keeps
 * the key too, so the server answers IDEMPOTENCY_CONFLICT instead of saving a second record.
 */
export function useIdempotencyKey(fingerprint: string, hold = false) {
  const [current, setCurrent] = useState(() => ({ fingerprint, key: crypto.randomUUID() }));
  if (current.fingerprint !== fingerprint) {
    const next = { fingerprint, key: hold ? current.key : crypto.randomUUID() };
    setCurrent(next);
    return next.key;
  }
  return current.key;
}
export function useMonthCommand() {
  const mounted = useMounted();
  const controller = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [uncertain, setUncertain] = useState(false);
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
    const restoreFocus = rememberFocus();
    setBusy(true);
    setError(null);
    try {
      const value = await action(next.signal);
      if (next.signal.aborted) throw new ApiError(0, "REQUEST_CANCELLED");
      if (mounted.current) setUncertain(false);
      return { ok: true, value };
    } catch (failure) {
      const value = toApiError(failure);
      if (mounted.current) {
        setError(value);
        // A rejected key reuse says the earlier attempt was saved, so the key stays held.
        if (outcomeUnknown(value)) setUncertain(true);
        else if (value.code !== "IDEMPOTENCY_CONFLICT") setUncertain(false);
      }
      return { ok: false, error: value };
    } finally {
      if (controller.current === next) controller.current = null;
      if (mounted.current) setBusy(false);
      restoreFocus();
    }
  }
  return { busy, error, setError, run, cancel, mounted, uncertain };
}
