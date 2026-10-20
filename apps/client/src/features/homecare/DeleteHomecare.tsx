import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { toApiError } from "../../platform/api";
import { useMonthCommand } from "../assets/months/useMonthCommand";
import { SaveControls } from "../finance/FinancialFeedback";
import { HomecareError } from "./HomecareSupport";
type DeleteHomecareProps<T> = {
  initial: T;
  label: string;
  name: string;
  read: () => Promise<T>;
  remove: (row: T, signal: AbortSignal) => Promise<unknown>;
  render: (row: T) => ReactNode;
  deleted: () => void;
  listPath: string;
};
export function DeleteHomecare<T extends { id: string; version: number }>(
  props: DeleteHomecareProps<T>,
) {
  // A new parent snapshot requires a new review, even when a fast reload never shows loading.
  return <DeleteHomecareReview key={`${props.initial.id}:${props.initial.version}`} {...props} />;
}
function DeleteHomecareReview<T extends { id: string; version: number }>({
  initial,
  label,
  name,
  read,
  remove,
  render,
  deleted,
  listPath,
}: DeleteHomecareProps<T>) {
  const [open, setOpen] = useState(false);
  const [row, setRow] = useState(initial);
  const [latest, setLatest] = useState<T | null>(null);
  const [ack, setAck] = useState(false);
  const command = useMonthCommand();
  const recoverable = command.error?.code === "VERSION_CONFLICT" || command.error?.status === 0;
  async function compare() {
    try {
      const current = await read();
      if (command.mounted.current) setLatest(current);
    } catch (e) {
      if (command.mounted.current) command.setError(toApiError(e));
    }
  }
  async function submit() {
    if (!ack || command.error) return;
    const result = await command.run((signal) => remove(row, signal));
    if (result.ok && command.mounted.current) deleted();
  }
  return open ? (
    <section className="review-panel danger-review">
      <h3>오등록 {label} 삭제 검토</h3>
      <p>
        연결·사용·문서 이력이 없는 오등록만 실제 삭제할 수 있어요. 이력이 있으면 사용 종료 또는 연결
        중지로 보존해 주세요.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={ack}
            disabled={command.busy}
            onChange={(e) => setAck(e.target.checked)}
          />
          오등록 {name}의 실제 삭제를 확인했어요
        </label>
        <HomecareError error={command.error} />
        {command.error?.status === 0 && (
          <p>
            삭제됐을 수 있어요. 현재 기록을 확인하거나{" "}
            <Link to={listPath}>목록에서 삭제 결과 확인</Link>을 해 주세요.
          </p>
        )}
        {recoverable && (
          <>
            <button type="button" onClick={() => void compare()}>
              삭제 전 현재 내용 비교
            </button>
            {latest && (
              <>
                {render(latest)}
                <button
                  type="button"
                  onClick={() => {
                    setRow(latest);
                    setLatest(null);
                    setAck(false);
                    command.setError(null);
                  }}
                >
                  현재 내용 확인 후 삭제 다시 검토
                </button>
              </>
            )}
          </>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          disabled={!ack || !!command.error}
          label={`오등록 ${label} 실제 삭제`}
        />
        <button
          type="button"
          disabled={command.busy}
          onClick={() => {
            setOpen(false);
            setAck(false);
            setLatest(null);
            command.setError(null);
          }}
        >
          삭제 검토 닫기
        </button>
      </form>
    </section>
  ) : (
    <button type="button" className="danger-button" onClick={() => setOpen(true)}>
      오등록 {label} 삭제 검토
    </button>
  );
}
