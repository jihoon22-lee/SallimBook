import { useId } from "react";
import { formatKrw } from "../features/assets/months/model";
import { parseKrwInput } from "./krw";

/** A won amount input that echoes the parsed value and explains a rejected one in place. */
export function AmountField({
  label,
  value,
  onChange,
  error = null,
  required = false,
  disabled = false,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
  required?: boolean;
  disabled?: boolean;
  hint?: string;
}) {
  const id = useId();
  const parsed = parseKrwInput(value);
  const echo = parsed.ok ? formatKrw(parsed.krw) : null;
  const describedBy = [echo && `${id}-echo`, hint && `${id}-hint`, error && `${id}-error`]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="form-field">
      <label htmlFor={`${id}-input`}>{label}</label>
      <input
        id={`${id}-input`}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        maxLength={40}
        value={value}
        required={required}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {echo && (
        <p id={`${id}-echo`} className="amount-echo">
          {echo}
        </p>
      )}
      {hint && (
        <p id={`${id}-hint`} className="muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
