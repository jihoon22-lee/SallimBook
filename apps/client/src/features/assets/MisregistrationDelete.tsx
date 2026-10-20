import { useState } from "react";
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
  children: ReactNode;
}) {
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
    <section className="card" aria-labelledby={`${id}-title`}>
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
        <button type="button" disabled={busy} onClick={cancel}>
          삭제 취소
        </button>
      </div>
    </section>
  );
}
