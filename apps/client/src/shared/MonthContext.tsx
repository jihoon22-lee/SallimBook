import { Icon } from "./Icon";
import { MonthField } from "./MonthField";
import { formatMonth, seoulMonth } from "./month";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export { formatMonth, isValidMonth, seoulMonth } from "./month";

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
  return (
    <div className="month-picker">
      <div className="month-control">
        <MonthField
          label="확인할 월"
          icon={<Icon name="calendar" size={17} />}
          value={month}
          onChange={setMonth}
        />
      </div>
      <span className="muted">서울 기준 · {formatMonth(month)}</span>
    </div>
  );
}
