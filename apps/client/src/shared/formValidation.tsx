import { useCallback, useMemo, useState } from "react";
import { flushSync } from "react-dom";

/** Show field errors only after a submit attempt, then move focus to the first problem. */
export function useSubmitAttempt() {
  const [attempted, setAttempted] = useState(false);
  const reject = useCallback((form: HTMLFormElement) => {
    flushSync(() => setAttempted(true));
    const target =
      form.querySelector<HTMLElement>('[aria-invalid="true"]') ??
      form.querySelector<HTMLElement>("[data-form-error]");
    target?.focus();
  }, []);
  const reset = useCallback(() => setAttempted(false), []);
  return useMemo(() => ({ attempted, reject, reset }), [attempted, reject, reset]);
}

export function FormError({ message }: { message: string }) {
  return message ? (
    <p className="form-error" role="alert" tabIndex={-1} data-form-error>
      {message}
    </p>
  ) : null;
}
