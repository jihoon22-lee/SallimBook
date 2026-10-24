import { useCallback, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { Link } from "react-router";
import { toApiError } from "../../platform/api";
import type { ApiError } from "../../platform/api";
import { useTaskPanelRelease } from "../../shared/TaskLayout";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { useMonthCommand } from "../assets/months/useMonthCommand";
import { formatKrw } from "../assets/months/model";
import { CashflowError } from "../finance/FinancialFeedback";
import { dateLabel, isDateOnly, todaySeoul } from "../finance/dates";
import { allPages, useResource } from "../finance/queries";
import { useFixedApi } from "./api";
import type { Obligation } from "./model";

export function batchEligible(row: Obligation): boolean {
  return (
    row.schedule_state === "active" &&
    row.status === "unpaid" &&
    !row.skipped &&
    !row.manually_completed &&
    !row.manual_override &&
    row.amount_mode === "fixed" &&
    row.economic_type !== "loan" &&
    row.actual_amount_krw === "0" &&
    row.expected_amount_krw !== null &&
    BigInt(row.expected_amount_krw) > 0n
  );
}
type Item = {
  row: Obligation;
  input: components["schemas"]["SettlementCreate"];
  key: string;
  state: "pending" | "saved" | "retry" | "review";
  error: ApiError | null;
};
export function BatchSettlement({
  month,
  onSaved,
  onClose,
}: {
  month: string;
  onSaved: () => void;
  onClose: () => void;
}) {
  const submitting = useRef(false);
  const api = useFixedApi();
  const resource = useResource(
    useCallback(
      () =>
        allPages((cursor) => api.obligations({ month, limit: 200, ...(cursor ? { cursor } : {}) })),
      [api, month],
    ),
  );
  const command = useMonthCommand();
  const release = useTaskPanelRelease();
  const [selected, setSelected] = useState<string[]>([]);
  const [date, setDate] = useState("");
  const [ack, setAck] = useState(false);
  const [message, setMessage] = useState("");
  const [items, setItems] = useState<Item[] | null>(null);
  const rows = resource.data?.filter(batchEligible) ?? [];
  const chosen = items
    ? items.map((item) => item.row)
    : rows.filter((row) => selected.includes(row.id));
  const pending = items?.some((item) => item.state !== "saved") ?? false;
  const guard = useUnsavedChangesGuard(command.busy || pending);
  const total = chosen.reduce((sum, row) => sum + BigInt(row.expected_amount_krw!), 0n);
  const expense = chosen
    .filter((row) => row.economic_type === "expense")
    .reduce((sum, row) => sum + BigInt(row.expected_amount_krw!), 0n);
  async function save(batch: Item[]) {
    // Freeze body, version and key per occurrence before the first attempt. Retry only
    // uncertain rows; a known conflict requires reviewing the individual occurrence.
    const next = [...batch];
    await command.run(async (signal) => {
      for (let index = 0; index < next.length; index++) {
        const item = next[index]!;
        if (signal.aborted) break;
        if (item.state !== "pending" && item.state !== "retry") continue;
        try {
          await api.settle(item.row.id, item.input, item.row.version, item.key, signal);
          next[index] = { ...item, state: "saved", error: null };
        } catch (failure) {
          const error = toApiError(failure);
          next[index] = {
            ...item,
            state: error.status === 0 || error.status >= 500 ? "retry" : "review",
            error,
          };
        }
        if (command.mounted.current) setItems([...next]);
      }
    });
    if (command.mounted.current) {
      if (next.every((item) => item.state === "saved")) {
        guard.release();
        release();
      }
      onSaved();
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    if (items) {
      submitting.current = true;
      try {
        await save(items);
      } finally {
        submitting.current = false;
      }
      return;
    }
    if (!chosen.length || !isDateOnly(date) || date > todaySeoul() || !ack) {
      setMessage("기록할 회차를 선택하고 실제 납부일과 금액을 확인해 주세요.");
      return;
    }
    const next: Item[] = chosen.map((row) => ({
      row,
      key: crypto.randomUUID(),
      state: "pending",
      error: null,
      input: {
        amount_krw: row.expected_amount_krw!,
        occurred_on: date,
        principal_krw: "0",
        interest_krw: null,
        account_id: row.account_id,
        card_id: row.card_id,
        note: null,
      },
    }));
    submitting.current = true;
    setItems(next);
    setMessage("");
    try {
      await save(next);
    } finally {
      submitting.current = false;
    }
  }
  return (
    <section className="card">
      <h2>여러 회차 납부 기록</h2>
      <p>
        실제로 같은 날 납부한 회차만 선택해 주세요. 금액이 미정이거나 변동·대출·부분 납부·수동
        예외인 회차는 상세 화면에서 기록해요.
      </p>
      <CashflowError error={resource.error} />
      {resource.error && (
        <button onClick={() => void resource.reload()}>선택할 회차 다시 확인</button>
      )}
      {resource.loading && <p role="status">선택할 회차를 확인하고 있어요.</p>}
      <form onSubmit={(event) => void submit(event)}>
        <fieldset
          disabled={command.busy || Boolean(items) || resource.loading || Boolean(resource.error)}
        >
          <legend>이번에 기록할 회차</legend>
          {!resource.loading && !resource.error && !rows.length && (
            <p>함께 기록할 수 있는 미납 회차가 없어요.</p>
          )}
          {rows.map((row) => (
            <label className="checkbox-field" key={row.id}>
              <input
                type="checkbox"
                checked={selected.includes(row.id)}
                onChange={(event) => {
                  setSelected((old) =>
                    event.target.checked ? [...old, row.id] : old.filter((id) => id !== row.id),
                  );
                  setAck(false);
                }}
              />
              {row.title} · {dateLabel(row.scheduled_date)} 예정 ·{" "}
              {formatKrw(row.expected_amount_krw!)}
            </label>
          ))}
          <label className="form-field">
            함께 기록할 실제 납부일
            <input
              type="date"
              required
              max={todaySeoul()}
              value={date}
              onChange={(event) => {
                setDate(event.target.value);
                setAck(false);
              }}
            />
          </label>
          <p>
            선택 {chosen.length}건 · 실제 납부 합계 {formatKrw(total.toString())} · 소비{" "}
            {formatKrw(expense.toString())} · 자산 이동 {formatKrw((total - expense).toString())}
          </p>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={ack}
              onChange={(event) => setAck(event.target.checked)}
            />
            선택한 회차를 위 날짜에 예정액과 같은 금액으로 실제 납부했어요.
          </label>
        </fieldset>
        {message && <p role="alert">{message}</p>}
        {items && (
          <section aria-label="선택 납부 저장 결과" aria-live="polite">
            <p>
              {items.filter((item) => item.state === "saved").length} / {items.length}건 저장 확인
            </p>
            <ul>
              {items.map((item) => (
                <li key={item.row.id}>
                  <strong>{item.row.title}</strong> ·{" "}
                  {item.state === "saved"
                    ? "저장 완료"
                    : item.state === "review"
                      ? "개별 확인 필요"
                      : item.state === "retry"
                        ? "결과 확인 필요"
                        : "아직 요청하지 않음"}
                  <CashflowError error={item.error} />
                  {item.state === "review" && (
                    <Link to={`/fixed-payments/${item.row.id}`}>현재 회차와 납부 내역 확인</Link>
                  )}
                </li>
              ))}
            </ul>
            {items.some((item) => item.state === "review") && (
              <p>
                충돌하거나 입력 확인이 필요한 회차는 자동으로 다시 저장하지 않아요. 이미 저장한
                항목은 유지돼요.
              </p>
            )}
          </section>
        )}
        <div className="form-actions">
          <button
            type="submit"
            disabled={
              command.busy ||
              resource.loading ||
              Boolean(resource.error) ||
              (items
                ? !items.some((item) => item.state === "retry" || item.state === "pending")
                : !chosen.length)
            }
          >
            {command.busy
              ? "저장 결과 확인 중…"
              : items
                ? "미확인 회차만 다시 확인"
                : "선택한 실제 납부 저장"}
          </button>
          {!command.busy && !pending && (
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                guard.release();
                release();
                onClose();
              }}
            >
              {items ? "결과 확인 후 닫기" : "선택 입력 닫기"}
            </button>
          )}
          {command.busy && (
            <button type="button" className="secondary-button" onClick={command.cancel}>
              요청 대기 중단
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
