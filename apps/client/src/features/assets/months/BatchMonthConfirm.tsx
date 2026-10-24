import { useEffect, useRef, useState } from "react";
import type { components } from "@sallimbook/api-client";
import { toApiError } from "../../../platform/api";
import { useUnsavedChangesGuard } from "../../../shared/UnsavedChanges";
import { scrollBehavior } from "../../../shared/motion";
import { useMounted } from "../../auth/AuthFeedback";
import { amountBases, shareToPercent } from "../model";
import { useAssetMonthsApi } from "./api";
import { formatKrw, maxAsOfDate, valueInput } from "./model";
import type { MonthRecord, MonthValue, MonthValueInput } from "./model";

type Entry = {
  row: MonthValue;
  body: MonthValueInput;
  state: "pending" | "saved" | "retry" | "review";
};
export function BatchMonthConfirm({
  initial,
  saved,
  refresh,
  close,
  review,
}: {
  initial: MonthRecord;
  saved: (result: components["schemas"]["MonthValueResult"], revisionId: string) => void;
  refresh: () => Promise<MonthRecord>;
  close: () => void;
  review: (row: MonthValue, date: string) => void;
}) {
  const api = useAssetMonthsApi();
  const mounted = useMounted();
  const section = useRef<HTMLElement>(null);
  const running = useRef(false);
  const stop = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [date, setDate] = useState("");
  const [ack, setAck] = useState(false);
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const candidates = initial.values.filter(
    (row) =>
      row.inclusion_status === "included" &&
      row.verification_state === "carried_unconfirmed" &&
      row.input_amount_krw !== null,
  );
  const complete = entries !== null && entries.every((entry) => entry.state === "saved");
  const guard = useUnsavedChangesGuard(
    busy || (!complete && (selected.length > 0 || Boolean(date))),
  );
  useEffect(() => {
    section.current?.focus();
    section.current?.scrollIntoView({ block: "start", behavior: scrollBehavior() });
    return () => {
      stop.current = true;
      controller.current?.abort();
    };
  }, []);
  const valid =
    selected.length > 0 &&
    ack &&
    candidates
      .filter((row) => selected.includes(row.id))
      .every((row) =>
        valueInput(
          initial.revision_id,
          row,
          { mode: "unchanged", amount: "", asOf: date, reason: "" },
          initial.month,
        ),
      );
  async function submit() {
    if (running.current || (!entries && !valid)) return;
    const work: Entry[] = entries
      ? entries.map((entry) => ({ ...entry }))
      : candidates
          .filter((row) => selected.includes(row.id))
          .map((row) => ({
            row: { ...row },
            body: valueInput(
              initial.revision_id,
              row,
              { mode: "unchanged", amount: "", asOf: date, reason: "" },
              initial.month,
            )!,
            state: "pending",
          }));
    const requestController = new AbortController();
    controller.current = requestController;
    running.current = true;
    stop.current = false;
    setBusy(true);
    setEntries(work.map((entry) => ({ ...entry })));
    try {
      for (const entry of work) {
        if (!mounted.current || stop.current) break;
        if (entry.state === "saved" || entry.state === "review") continue;
        try {
          // Each update retains the original value identity and version. An ambiguous
          // response must never be retried with a newer version without human review.
          const result = await api.update(
            initial.month,
            entry.row.asset_id,
            entry.body,
            entry.row.version,
            requestController.signal,
          );
          if (!mounted.current) return;
          entry.state = "saved";
          saved(result, initial.revision_id);
        } catch (failure) {
          if (!mounted.current) return;
          const error = toApiError(failure);
          entry.state = error.status === 0 || error.status >= 500 ? "retry" : "review";
          if (error.status === 401 || error.status === 403) stop.current = true;
        }
        setEntries(work.map((item) => ({ ...item })));
      }
      if (mounted.current) {
        if (work.every((entry) => entry.state === "saved")) guard.release();
        await refresh().catch(() => undefined);
      }
    } finally {
      running.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <section
      ref={section}
      tabIndex={-1}
      className="card month-row-editor"
      aria-labelledby="batch-month-title"
    >
      <h2 id="batch-month-title">선택한 항목 변동 없음</h2>
      <p>
        금액이 있는 미확인 항목 중 직접 확인한 항목만 선택해 주세요. 미입력·합계 제외 항목은 개별
        입력에서 확인해요. 월 확정은 별도로 진행해요.
      </p>
      <fieldset className="finance-fields" disabled={busy || entries !== null}>
        <legend>확인할 항목과 실제 날짜</legend>
        {candidates.map((row) => (
          <label className="checkbox-field" key={row.id}>
            <input
              type="checkbox"
              aria-label={`${row.name} 선택`}
              checked={selected.includes(row.id)}
              onChange={(event) =>
                setSelected((old) =>
                  event.target.checked ? [...old, row.id] : old.filter((id) => id !== row.id),
                )
              }
            />
            <span>
              {row.name} · 입력 {formatKrw(row.input_amount_krw)} · {amountBases[row.amount_basis]}{" "}
              · 지분 {shareToPercent(row.household_share)}% · 가계 보유분{" "}
              {formatKrw(row.owned_amount_krw)}
            </span>
          </label>
        ))}
        <div className="form-field">
          <label htmlFor="batch-month-date">공통 실제 확인 기준일</label>
          <input
            id="batch-month-date"
            type="date"
            min={`${initial.month}-01`}
            max={maxAsOfDate(initial.month)}
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </div>
        <label className="checkbox-field">
          <input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} />
          선택한 금액이 기준일에도 같음을 직접 확인했어요.
        </label>
      </fieldset>
      {!entries && (
        <p>{selected.length}개 선택 · 항목마다 입력 기준과 가계 지분을 확인해 주세요.</p>
      )}
      {entries && (
        <>
          <p role="status">
            {entries.filter((entry) => entry.state === "saved").length} / {entries.length}개 저장
            완료{busy ? " · 처리 중" : ""}
          </p>
          <p>
            항목별로 저장해요. 완료한 항목은 다시 보내지 않아요. 응답을 확인하지 못한 항목은 이미
            저장됐을 수 있으며, 충돌하면 개별 입력에서 현재 기록을 확인해 주세요. 개별 비교를 열면
            이 선택 작업은 닫히며 저장 완료한 항목은 유지돼요.
          </p>
          <ul>
            {entries.map((entry) => (
              <li key={entry.row.id}>
                {entry.row.name} ·{" "}
                {entry.state === "saved" ? (
                  "저장 완료"
                ) : entry.state === "review" ? (
                  <span>현재 기록을 개별 확인해 주세요.</span>
                ) : entry.state === "retry" ? (
                  "응답 확인 필요"
                ) : (
                  "아직 보내지 않음"
                )}
                {entry.state === "review" && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      guard.release();
                      review(entry.row, entry.body.as_of_date!);
                    }}
                  >
                    {entry.row.name} 입력 보존하고 개별 비교
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="form-actions">
        {!entries && (
          <button type="button" disabled={!valid || busy} onClick={() => void submit()}>
            선택한 금액 확인 저장
          </button>
        )}
        {entries?.some((entry) => entry.state === "retry" || entry.state === "pending") && (
          <button type="button" disabled={busy} onClick={() => void submit()}>
            미완료 항목만 다시 시도
          </button>
        )}
        {busy && (
          <button
            type="button"
            onClick={() => {
              stop.current = true;
            }}
          >
            현재 항목 처리 후 멈추기
          </button>
        )}
        <button
          type="button"
          className="secondary-button"
          disabled={busy}
          onClick={() => {
            guard.release();
            close();
          }}
        >
          {entries ? "결과 확인하고 닫기" : "선택 취소"}
        </button>
      </div>
    </section>
  );
}
