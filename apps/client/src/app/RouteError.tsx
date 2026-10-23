import { useEffect, useRef } from "react";

/**
 * Replaces the router's English default page when a screen throws while rendering. It is
 * standalone (no auth, router or data hooks that may be what failed) and never shows the
 * error itself: no message, no stack, nothing from the data on screen.
 */
export function RouteError() {
  const main = useRef<HTMLElement>(null);
  useEffect(() => {
    document.title = "화면을 표시하지 못했어요 · SallimBook";
    main.current?.focus();
  }, []);
  return (
    <main ref={main} className="route-error" tabIndex={-1}>
      <h1>화면을 표시하지 못했어요.</h1>
      <p>잠시 후 다시 시도해 주세요. 계속 안 되면 홈으로 돌아가 주세요.</p>
      <div className="form-actions">
        <button type="button" onClick={() => window.location.reload()}>
          다시 시도
        </button>
        <a className="button-link secondary-button" href="/">
          홈으로
        </a>
      </div>
    </main>
  );
}
