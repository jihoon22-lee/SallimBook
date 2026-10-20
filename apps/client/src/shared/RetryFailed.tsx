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
