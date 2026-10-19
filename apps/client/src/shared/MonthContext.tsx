import { Icon } from "./Icon";
import { createContext, useContext, useId, useState } from "react";
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

const MonthContext = createContext<{ month: string; setMonth: (month: string) => void } | null>(
  null,
);

export function MonthProvider({ children }: { children: ReactNode }) {
  const [month, setMonth] = useState(() => seoulMonth());
  return <MonthContext.Provider value={{ month, setMonth }}>{children}</MonthContext.Provider>;
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
