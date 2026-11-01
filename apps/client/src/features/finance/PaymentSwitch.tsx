import { useEffect, useRef, useState } from "react";
import type { components } from "@sallimbook/api-client";
import { Link } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { PaymentMethod } from "../fixed/PaymentMethod";
import { nativeFinance } from "../../platform/nativeFinance";
import { cancellableNative } from "../../platform/cancellableNative";
import { ApiError, toApiError } from "../../platform/api";
import { CashflowError } from "./FinancialFeedback";
import { dateLabel, isDateOnly, todaySeoul } from "./dates";
import { allPages } from "./queries";
import { formatKrw } from "../assets/months/model";
type S = components["schemas"];
type Input = S["PaymentSwitchInput"];
type Row = S["PlanPaymentSwitchRow"];
type Entry = {
  row: Row;
  selected: boolean;
  key: string;
  state: "ready" | "saved" | "error" | "gone";
  error: ApiError | null;
};
export function PaymentSwitch({
  sourceKind,
  sourceId,
  disabled,
  onBusy,
  onSaved,
}: {
  sourceKind: Input["source_kind"];
  sourceId: string;
  disabled: boolean;
  onBusy: (value: boolean) => void;
  onSaved: () => void;
}) {
  const { domainApi } = useAuth();
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState<"none" | "account" | "card">("none");
  const [target, setTarget] = useState("");
  const [date, setDate] = useState(todaySeoul);
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [previewInput, setPreviewInput] = useState<Input | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [validation, setValidation] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    const ref = generation;
    return () => {
      ref.current++;
      controller.current?.abort();
      onBusy(false);
    };
  }, [onBusy]);
  function reset() {
    generation.current++;
    setEntries(null);
    setPreviewInput(null);
    setError(null);
    setValidation("");
  }
  async function preview(failedOnly = false) {
    if (busy) return;
    if (!isDateOnly(date) || date < todaySeoul()) {
      setValidation("오늘 이후의 올바른 적용일을 입력해 주세요.");
      return;
    }
    if (method === "none" || !target || (method === sourceKind && target === sourceId)) {
      setValidation("기존 수단과 다른 납부 계좌 또는 카드를 선택해 주세요.");
      return;
    }
    const input: Input = {
      source_kind: sourceKind,
      source_id: sourceId,
      target_kind: method,
      target_id: target,
      effective_on: date,
    };
    const current = ++generation.current;
    setBusy(true);
    onBusy(true);
    setError(null);
    setValidation("");
    try {
      const rows = await allPages((cursor) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/expense-plan-payment-switch/preview", {
              body: input,
              params: { query: { limit: 200, ...(cursor ? { cursor } : {}) } },
            }),
          () =>
            nativeFinance.previewExpensePlanPaymentSwitch({
              input,
              query: { limit: 200, ...(cursor ? { cursor } : {}) },
            }),
        ),
      );
      if (current !== generation.current) return;
      const entry = (row: Row): Entry => ({
        row,
        selected: false,
        key: crypto.randomUUID(),
        state: "ready",
        error: null,
      });
      setEntries((previous) =>
        failedOnly && previous
          ? previous.map((old) => {
              if (old.state !== "error") return old;
              const row = rows.find((row) => row.id === old.row.id);
              return row ? entry(row) : { ...old, selected: false, state: "gone", error: null };
            })
          : rows.map(entry),
      );
      setPreviewInput(input);
    } catch (failure) {
      if (current === generation.current) setError(toApiError(failure));
    } finally {
      if (current === generation.current) {
        setBusy(false);
        onBusy(false);
      }
    }
  }
  async function save(retry?: Entry) {
    if (busy || !previewInput || !entries) return;
    const selected = retry
      ? [retry]
      : entries.filter(
          (entry) => entry.selected && entry.state === "ready" && !entry.row.blocked_reason,
        );
    if (!selected.length) return;
    const current = generation.current;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    onBusy(true);
    setError(null);
    let attempted = false;
    for (const entry of selected) {
      if (abort.signal.aborted || current !== generation.current) break;
      const input: S["PaymentSwitchApply"] = {
        ...previewInput,
        preview_digest: entry.row.preview_digest,
        reason: "결제수단 일괄 변경",
      };
      let failure: ApiError | null = null;
      try {
        attempted = true;
        await domainApi.write(
          (client) =>
            client.POST("/api/v1/expense-plan-payment-switch/{plan_id}", {
              body: input,
              params: {
                path: { plan_id: entry.row.id },
                header: { "If-Match": `"${entry.row.version}"`, "Idempotency-Key": entry.key },
              },
              signal: abort.signal,
            }),
          () =>
            cancellableNative(abort.signal, () =>
              nativeFinance.applyExpensePlanPaymentSwitch({
                planId: entry.row.id,
                input,
                ifMatch: `"${entry.row.version}"`,
                idempotencyKey: entry.key,
              }),
            ),
        );
      } catch (caught) {
        failure = toApiError(caught);
      }
      if (abort.signal.aborted || current !== generation.current) break;
      setEntries(
        (rows) =>
          rows?.map((row) =>
            row.row.id === entry.row.id
              ? { ...row, selected: false, state: failure ? "error" : "saved", error: failure }
              : row,
          ) ?? null,
      );
      if (failure && [401, 403, 0].includes(failure.status)) break;
    }
    if (current === generation.current) {
      setBusy(false);
      onBusy(false);
      if (attempted) onSaved();
    }
  }
  return (
    <div className="payment-switch">
      <button
        type="button"
        aria-expanded={open}
        disabled={disabled || busy}
        onClick={() => setOpen(!open)}
      >
        연결 규칙 결제수단 바꾸기
      </button>
      {open && (
        <section aria-label="결제수단 일괄 변경">
          <h3>정기 납부 결제수단 변경</h3>
          <p>
            살림북에 등록한 계획만 바꿔요. 금융기관·서비스의 자동이체나 카드 결제는 해당 기관에서
            직접 변경해 주세요.
          </p>
          {sourceKind === "account" && (
            <p>
              이 계좌의 직접 납부 규칙을 변경해요. 이 계좌로 대금을 내는 카드의 승인 계획과 카드
              결제계좌는 각 카드 상세에서 확인해 주세요.
            </p>
          )}
          <fieldset disabled={disabled || busy}>
            <legend>새 결제수단과 적용일</legend>
            <PaymentMethod
              method={method}
              id={target}
              onChange={(kind, id) => {
                reset();
                setMethod(kind);
                setTarget(id);
              }}
            />
            <label>
              변경 적용일
              <input
                type="date"
                onKeyDown={(event) => {
                  if (event.key === "Enter") event.preventDefault();
                }}
                value={date}
                min={todaySeoul()}
                onChange={(event) => {
                  reset();
                  setDate(event.target.value);
                }}
              />
            </label>
            {validation && <p role="alert">{validation}</p>}
            <button type="button" onClick={() => void preview()}>
              변경 미리보기
            </button>
          </fieldset>
          <CashflowError error={error} />
          {busy && <p role="status">선택한 연결을 확인하고 처리하고 있어요.</p>}
          {entries && (
            <>
              <p>
                적용일 이후에도 금액·주기·예정 변경 기간을 유지해요. 적용일 이전 회차, 납부 기록이
                있는 회차, 수동 조정한 회차는 보존해요.
              </p>
              {!entries.length && <p>변경할 직접 연결 규칙이 없어요.</p>}
              <ul className="item-list">
                {entries.map((entry) => (
                  <li key={entry.row.id}>
                    <label className="checkbox-field">
                      <input
                        type="checkbox"
                        onKeyDown={(event) => {
                          if (event.key === "Enter") event.preventDefault();
                        }}
                        checked={entry.selected}
                        disabled={
                          disabled || busy || entry.state !== "ready" || !!entry.row.blocked_reason
                        }
                        onChange={(event) =>
                          setEntries((rows) =>
                            rows!.map((row) =>
                              row.row.id === entry.row.id
                                ? { ...row, selected: event.target.checked }
                                : row,
                            ),
                          )
                        }
                      />
                      {entry.row.title}
                    </label>
                    <Link to={`/fixed-payments/rules/${entry.row.id}`}>규칙 상세</Link>
                    <p>
                      변경 예정 회차 {entry.row.update_occurrence_count}개 · 이전 회차 보존{" "}
                      {entry.row.preserved_past_count}개 · 납부 회차 보존{" "}
                      {entry.row.preserved_paid_count}개 · 수동 예외 보존{" "}
                      {entry.row.preserved_manual_count}개
                    </p>
                    <details>
                      <summary>현재·미래 적용 기간 {entry.row.periods.length}개 확인</summary>
                      <ul>
                        {entry.row.periods.map((period) => (
                          <li key={period.id}>
                            {period.effective_from > date ? "미래 규칙" : "현재 규칙"} ·{" "}
                            {dateLabel(period.effective_from)}부터{" "}
                            {period.effective_until
                              ? `${dateLabel(period.effective_until)} 전까지`
                              : "종료일 없음"}{" "}
                            ·{" "}
                            {period.expected_amount_krw == null
                              ? "금액 미정"
                              : formatKrw(period.expected_amount_krw)}{" "}
                            · {period.interval_count}
                            {period.frequency === "monthly"
                              ? "개월"
                              : period.frequency === "annual"
                                ? "년"
                                : "일"}
                            마다
                          </li>
                        ))}
                      </ul>
                      <p>그 외 기간 {entry.row.unchanged_period_count}개는 유지해요.</p>
                    </details>
                    {entry.row.blocked_reason && (
                      <p>
                        첫 규칙 시작일 다음 날부터 적용할 수 있어요. 적용일을 바꾸고 다시 확인해
                        주세요.
                      </p>
                    )}
                    {entry.state === "saved" && <p role="status">변경 완료</p>}
                    {entry.state === "gone" && (
                      <p role="status">
                        현재 변경할 연결이 없어요. 규칙 상세에서 결과를 확인해 주세요.
                      </p>
                    )}
                    <CashflowError error={entry.error} />
                    {entry.state === "error" && entry.error?.status !== 409 && (
                      <button
                        type="button"
                        disabled={disabled || busy}
                        onClick={() => void save(entry)}
                      >
                        같은 요청 다시 확인
                      </button>
                    )}
                  </li>
                ))}
              </ul>
              {entries.some((entry) => entry.state === "error") && (
                <button
                  type="button"
                  disabled={disabled || busy}
                  onClick={() => void preview(true)}
                >
                  실패·충돌 항목만 다시 검토
                </button>
              )}
              <button
                type="button"
                disabled={
                  disabled ||
                  busy ||
                  !entries.some(
                    (entry) =>
                      entry.selected && entry.state === "ready" && !entry.row.blocked_reason,
                  )
                }
                onClick={() => void save()}
              >
                선택한 규칙 변경
              </button>
            </>
          )}
        </section>
      )}
    </div>
  );
}
