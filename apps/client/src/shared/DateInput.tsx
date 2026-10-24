import { useId, useState } from "react";
import type { InputHTMLAttributes } from "react";

/** Keep the browser's date validation and show a persistent, readable field error. */
export function DateInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const errorId = useId();
  const [error, setError] = useState("");
  function validate(input: HTMLInputElement) {
    const validity = input.validity;
    setError(
      validity.valueMissing
        ? "날짜를 입력해 주세요."
        : validity.rangeUnderflow
          ? `${input.min} 이후 날짜를 입력해 주세요.`
          : validity.rangeOverflow
            ? `${input.max} 이전 날짜를 입력해 주세요.`
            : !validity.valid
              ? "날짜를 확인해 주세요."
              : "",
    );
  }
  return (
    <>
      <input
        {...props}
        type="date"
        aria-invalid={error ? true : props["aria-invalid"]}
        aria-describedby={
          [props["aria-describedby"], error ? errorId : ""].filter(Boolean).join(" ") || undefined
        }
        onInvalid={(event) => {
          validate(event.currentTarget);
          props.onInvalid?.(event);
        }}
        onBlur={(event) => {
          validate(event.currentTarget);
          props.onBlur?.(event);
        }}
        onChange={(event) => {
          if (error) validate(event.currentTarget);
          props.onChange?.(event);
        }}
      />
      {error && (
        <span className="field-error" id={errorId} role="alert">
          {error}
        </span>
      )}
    </>
  );
}
