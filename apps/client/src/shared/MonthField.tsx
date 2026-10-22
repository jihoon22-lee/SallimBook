import { useId, useRef, useState } from "react";
import type { ReactNode, Ref } from "react";
import { isValidMonth, seoulMonth, shiftMonth } from "./month";

/**
 * A "YYYY-MM" field that also works where the browser shows a plain text box instead of a
 * month picker. Typing is kept as a local draft; `onChange` only receives a complete month
 * inside min/max, so half-typed text never reaches the URL or the server.
 */
export function MonthField({
  label,
  value,
  onChange,
  min = "0001-01",
  max = "9999-12",
  disabled = false,
  required = false,
  icon,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  min?: string;
  max?: string;
  disabled?: boolean;
  required?: boolean;
  icon?: ReactNode;
}) {
  const id = useId();
  const earlierRef = useRef<HTMLButtonElement>(null);
  const [draft, setDraft] = useState(value);
  const [synced, setSynced] = useState(value);
  // A month that changed from outside (a button, the URL, a new Seoul month) replaces the draft.
  if (synced !== value) {
    setSynced(value);
    setDraft(value);
  }
  const usable = (month: string | null) =>
    month !== null && isValidMonth(month) && month >= min && month <= max;
  function pick(next: string | null) {
    if (next !== null && usable(next) && next !== value) onChange(next);
  }
  const current = seoulMonth();
  // aria-disabled instead of disabled, so the button a person just pressed keeps its focus.
  const step = (
    target: string | null,
    text: string,
    mark: string,
    side: "before" | "after",
    ref?: Ref<HTMLButtonElement>,
  ) => {
    const allowed = usable(target) && !disabled;
    return (
      <button
        ref={ref}
        type="button"
        className="secondary-button month-step"
        aria-disabled={allowed ? undefined : true}
        disabled={disabled}
        onClick={() => {
          if (allowed) pick(target);
        }}
      >
        {side === "before" && <span aria-hidden="true">{mark}</span>}
        <span className="month-step-text">{text}</span>
        {side === "after" && <span aria-hidden="true">{mark}</span>}
      </button>
    );
  };
  return (
    <div className="month-field">
      <label htmlFor={id}>
        {icon}
        {label}
      </label>
      <div className="month-field-row">
        {step(shiftMonth(value, -1), "이전 달", "‹", "before", earlierRef)}
        <input
          id={id}
          type="month"
          value={draft}
          min={min}
          max={max}
          disabled={disabled}
          required={required}
          placeholder="YYYY-MM"
          autoComplete="off"
          onChange={(event) => {
            setDraft(event.target.value);
            pick(event.target.value);
          }}
          onBlur={() => {
            if (!usable(draft)) setDraft(value);
          }}
        />
        {step(shiftMonth(value, 1), "다음 달", "›", "after")}
        {usable(current) && current !== value && !disabled && (
          <button
            type="button"
            className="secondary-button month-step month-today"
            onClick={() => {
              pick(current);
              // The shortcut disappears once it has been used; keep focus inside the field.
              earlierRef.current?.focus();
            }}
          >
            이번 달
          </button>
        )}
      </div>
    </div>
  );
}
