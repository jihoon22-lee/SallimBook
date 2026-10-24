import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, toApiError } from "../../platform/api";
import { useMounted } from "../auth/AuthFeedback";
import { FinanceError } from "../finance/FinanceSupport";

/**
 * Deletes a misregistered row after an explicit acknowledgment. A 404 means it is already
 * gone (an ambiguous earlier attempt or the spouse), which is what the user asked for.
 */
export function MisregistrationDelete({
  id,
  title,
  ackLabel,
  actionLabel,
  inUseCode,
  remove,
  done,
  cancel,
  reload,
  children,
}: {
  id: string;
  title: string;
  ackLabel: string;
  actionLabel: string;
  inUseCode: ApiError["code"];
  remove: () => Promise<unknown>;
  done: () => void;
  cancel: () => void;
  /** Loads the item again after another edit changed it. */
  reload: () => void;
  children: ReactNode;
}) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const opener = document.activeElement;
    panel.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: "start" });
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected)
        opener.focus({ preventScroll: true });
    };
  }, []);
  const mounted = useMounted();
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      await remove();
      if (mounted.current) done();
    } catch (failure) {
      const value = toApiError(failure);
      if (!mounted.current) return;
      if (value.status === 404) done();
      else setError(value);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  // A version conflict or a reference stays visible; the user decides what to do next.
  const blocked = error?.code === "VERSION_CONFLICT" || error?.code === inUseCode;
  return (
    <section ref={panel} tabIndex={-1} className="card task-panel" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={ack}
          disabled={busy}
          onChange={(event) => setAck(event.target.checked)}
        />
        {ackLabel}
      </label>
      <FinanceError error={error} />
      <div className="form-actions">
        <button
          type="button"
          className="danger-button"
          disabled={busy || !ack || blocked}
          onClick={() => void run()}
        >
          {actionLabel}
        </button>
        {error?.code === "VERSION_CONFLICT" && (
          <>
            <p>최신 내용을 불러온 뒤 삭제 검토를 다시 열어 확인해 주세요.</p>
            <button type="button" disabled={busy} onClick={reload}>
              다시 불러오기
            </button>
          </>
        )}
        <button type="button" disabled={busy} onClick={cancel}>
          삭제 취소
        </button>
      </div>
    </section>
  );
}
