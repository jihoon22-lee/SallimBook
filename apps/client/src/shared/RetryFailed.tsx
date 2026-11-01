import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { ApiError } from "../platform/api";
import { MonthError } from "../features/assets/months/MonthFeedback";

export type RetryItem = { error: ApiError | null; retry: () => void };

/** True when two or more parts failed and their own retries should give way to one. */
export const retriesCombined = (items: RetryItem[]) =>
  items.filter((item) => item.error).length > 1;

/** One message and one button when several parts of a screen failed together. */
export function RetryFailed({ items, label }: { items: RetryItem[]; label: string }) {
  const failed = items.filter((item) => item.error);
  if (failed.length < 2) return null;
  return (
    <div className="retry-failed">
      <MonthError error={failed[0]!.error} />
      <button type="button" onClick={() => failed.forEach((item) => item.retry())}>
        {label}
      </button>
    </div>
  );
}

type Report = (id: string, item: RetryItem | null) => void;
const RetryContext = createContext<{ report: Report; combined: boolean } | null>(null);

/** Parts that load on their own report here, so a shared outage shows one message, not one per part. */
export function RetryScope({ label, children }: { label: string; children: ReactNode }) {
  const [items, setItems] = useState<Record<string, RetryItem>>({});
  const report = useCallback<Report>(
    (id, item) =>
      setItems((old) => {
        if (item) return { ...old, [id]: item };
        if (!(id in old)) return old;
        const rest = { ...old };
        delete rest[id];
        return rest;
      }),
    [],
  );
  const list = Object.values(items);
  const combined = retriesCombined(list);
  const value = useMemo(() => ({ report, combined }), [report, combined]);
  return (
    <RetryContext.Provider value={value}>
      <RetryFailed items={list} label={label} />
      {children}
    </RetryContext.Provider>
  );
}

/** Reports one part's failure; true while the scope's single retry stands in for this part's own. */
export function useRetryReport(id: string, error: ApiError | null, retry: () => unknown) {
  const context = useContext(RetryContext);
  const latest = useRef(retry);
  useEffect(() => {
    latest.current = retry;
  });
  const report = context?.report;
  useEffect(() => {
    if (!report) return;
    report(id, error ? { error, retry: () => void latest.current() } : null);
    return () => report(id, null);
  }, [report, id, error]);
  return !!context?.combined && !!error;
}
