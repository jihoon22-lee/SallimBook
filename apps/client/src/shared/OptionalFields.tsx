import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

/** Collapsing optional inputs never clears their values or excludes them from validation. */
export function OptionalFields({
  title,
  hasValues,
  children,
  hasError = false,
}: {
  title: string;
  hasValues: boolean;
  hasError?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if ((hasValues || hasError) && ref.current) ref.current.open = true;
  }, [hasValues, hasError]);
  return (
    <details
      ref={ref}
      className="optional-fields"
      onInvalidCapture={(event) => {
        if (ref.current) ref.current.open = true;
        (event.target as HTMLElement).focus();
      }}
    >
      <summary>
        {title} <span className="muted">선택 입력</span>
      </summary>
      <div className="form-grid">{children}</div>
    </details>
  );
}
