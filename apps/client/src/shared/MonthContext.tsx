import { Icon } from "./Icon";
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useState } from "react";
import type { ReactNode } from "react";

export function seoulMonth(date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
  }).formatToParts(date);
  return `${parts.find((part) => part.type === "year")!.value}-${parts.find((part) => part.type === "month")!.value}`;
}

export function isValidMonth(month: string): boolean {
  return /^(?!0000)\d{4}-(0[1-9]|1[0-2])$/.test(month);
}

export function formatMonth(month: string): string {
  return `${month.slice(0, 4)}년 ${Number(month.slice(5))}월`;
}

type MonthState = { month: string; currentMonth: string };
const MonthContext = createContext<(MonthState & { setMonth: (month: string) => void }) | null>(
  null,
);

/**
 * Keeps the Seoul month current while the app stays open. The selected month follows a new
 * month only while it was following the current one; a month chosen by hand stays.
 */
export function MonthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<MonthState>(() => {
    const current = seoulMonth();
    return { month: current, currentMonth: current };
  });
  useEffect(() => {
    const follow = () =>
      setState((old) => {
        const current = seoulMonth();
        return current === old.currentMonth
          ? old
          : { currentMonth: current, month: old.month === old.currentMonth ? current : old.month };
      });
    const visible = () => {
      if (document.visibilityState === "visible") follow();
    };
    const timer = window.setInterval(follow, 30_000);
    window.addEventListener("focus", follow);
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", follow);
      document.removeEventListener("visibilitychange", visible);
    };
  }, []);
  // A stable setter keeps effects keyed on it (AssetMonthPage) from re-running.
  const setMonth = useCallback(
    (month: string) => setState((old) => (old.month === month ? old : { ...old, month })),
    [],
  );
  const value = useMemo(() => ({ ...state, setMonth }), [state, setMonth]);
  return <MonthContext.Provider value={value}>{children}</MonthContext.Provider>;
}

export function useMonth() {
  const context = useContext(MonthContext);
  if (!context) throw new Error("MonthProvider is required");
  return context;
}

export function MonthPicker() {
  const { month, setMonth } = useMonth();
  const id = useId();
  return (
    <div className="month-picker">
      <div className="month-control">
        <label htmlFor={id}>
          <Icon name="calendar" size={17} />
          확인할 월
        </label>
        <input
          id={id}
          type="month"
          value={month}
          min="0001-01"
          max="9999-12"
          onChange={(event) => {
            if (isValidMonth(event.target.value)) setMonth(event.target.value);
          }}
        />
      </div>
      <span className="muted">서울 기준 · {formatMonth(month)}</span>
    </div>
  );
}
