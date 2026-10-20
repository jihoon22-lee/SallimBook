import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { amountBases, shareToPercent } from "../model";
import { dateLabel } from "../../finance/dates";
import { useAssetMonthsApi } from "./api";
import type { HouseholdMember } from "../../finance/FinanceSupport";
import { ScopeChanges } from "./ScopeChanges";
import { MonthError } from "./MonthFeedback";
import {
  formatKrw,
  maxAsOfDate,
  ownedPreview,
  scopeIdentity,
  valueDraft,
  valueInput,
  verificationStates,
} from "./model";
import type { MonthRecord, MonthValue, ValueDraft } from "./model";
import { useMonthCommand } from "./useMonthCommand";
import { useUnsavedChangesGuard } from "../../../shared/UnsavedChanges";
import { AmountField } from "../../../shared/AmountField";
import { FormError, useSubmitAttempt } from "../../../shared/formValidation";
import { krwFieldError } from "../../../shared/krw";
export type EditingValue = { revisionId: string; row: MonthValue };
export function MonthRowEditor({
  month,
  initial,
  reload,
  saved,
  close,
  members,
}: {
  month: string;
  members: HouseholdMember[];
  initial: EditingValue;
  reload: () => Promise<MonthRecord>;
  saved: (result: components["schemas"]["MonthValueResult"], revisionId: string) => void;
  close: () => void;
}) {
  const api = useAssetMonthsApi();
  const command = useMonthCommand();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => valueDraft(initial.row));
  const [conflict, setConflict] = useState(false);
  const [latest, setLatest] = useState<MonthRecord | null>(null);
  const [ackScope, setAckScope] = useState(false);
  const [formError, setFormError] = useState("");
  const attempt = useSubmitAttempt();
  const [dirty, setDirty] = useState(false);
  useUnsavedChangesGuard(dirty);
  const section = useRef<HTMLElement>(null);
  useEffect(() => {
    section.current?.focus();
    section.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, []);
  const currentRow = latest?.values.find((row) => row.asset_id === base.row.asset_id);
  const scopeChanged = currentRow ? scopeIdentity(currentRow) !== scopeIdentity(base.row) : false;
  const preview =
    draft.mode === "missing"
      ? null
      : ownedPreview(
          draft.mode === "unchanged" ? (base.row.input_amount_krw ?? "") : draft.amount,
          base.row.household_share,
          base.row.amount_basis,
        );
  async function submit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    event.preventDefault();
    if (command.busy || conflict) return;
    const body = valueInput(base.revisionId, base.row, draft, month);
    if (!body) {
      setFormError(
        "금액은 0 이상의 정수 원으로 입력하고, 선택한 월의 실제 확인 날짜를 정해 주세요.",
      );
      attempt.reject(form);
      return;
    }
    setFormError("");
    const result = await command.run((signal) =>
      api.update(month, base.row.asset_id, body, base.row.version, signal),
    );
    if (!command.mounted.current) return;
    if (result.ok) saved(result.value, base.revisionId);
    else if (result.error.status === 409 || result.error.code === "NOT_FOUND") setConflict(true);
  }
  async function compare() {
    const result = await command.run(() => reload());
    if (result.ok && command.mounted.current) {
      setLatest(result.value);
      setAckScope(false);
    }
  }
  function adopt(keep: boolean) {
    if (
      !latest ||
      !currentRow ||
      latest.state === "confirmed" ||
      (keep && scopeChanged && !ackScope)
    )
      return;
    if (
      keep &&
      draft.mode === "unchanged" &&
      (currentRow.verification_state !== "carried_unconfirmed" ||
        currentRow.input_amount_krw !== base.row.input_amount_krw)
    ) {
      setFormError(
        "최신 행의 불러온 금액이나 확인 상태가 달라졌어요. 금액 직접 확인으로 바꾸거나 서버 값으로 돌아가 주세요.",
      );
      return;
    }
    setBase({ revisionId: latest.revision_id, row: currentRow });
    if (!keep) setDraft(valueDraft(currentRow));
    setLatest(null);
    setConflict(false);
    setAckScope(false);
    command.setError(null);
    setFormError("");
  }
  return (
    <section
      ref={section}
      tabIndex={-1}
      className="card month-row-editor"
      aria-labelledby="month-row-editor-title"
    >
      <h2 id="month-row-editor-title">{base.row.name} 금액 확인</h2>
      <p>
        이 기록의 지분 {shareToPercent(base.row.household_share)}% ·{" "}
        {amountBases[base.row.amount_basis]} ·{" "}
        {base.row.inclusion_status === "included" ? "합계 포함" : "합계 제외"}
      </p>
      <form
        className="finance-form"
        onInput={() => setDirty(true)}
        onSubmit={(event) => void submit(event)}
      >
        <fieldset className="finance-fields" disabled={command.busy}>
          <legend>확인한 금액과 날짜</legend>
          <div className="form-field">
            <label htmlFor="month-value-mode">입력 방식</label>
            <select
              id="month-value-mode"
              value={draft.mode}
              onChange={(event) =>
                setDraft({ ...draft, mode: event.target.value as ValueDraft["mode"] })
              }
            >
              <option value="amount">금액 직접 확인</option>
              {base.row.verification_state === "carried_unconfirmed" &&
                base.row.input_amount_krw !== null && (
                  <option value="unchanged">불러온 금액과 변동 없음</option>
                )}
              <option value="missing">미입력으로 남기기</option>
            </select>
          </div>
          {draft.mode === "amount" && (
            <AmountField
              label="확인 금액 (원)"
              required
              value={draft.amount}
              hint="세 자리마다 쉼표를 써도 돼요. 0원도 직접 확인한 값으로 저장해요."
              error={
                attempt.attempted
                  ? krwFieldError(draft.amount, { required: true, positive: false })
                  : null
              }
              onChange={(amount) => setDraft({ ...draft, amount })}
            />
          )}
          {draft.mode === "unchanged" && (
            <p>
              불러온 입력 금액 {formatKrw(base.row.input_amount_krw)}이 현재도 같음을 확인해요. 새
              기준일을 반드시 입력해 주세요.
            </p>
          )}
          {draft.mode === "missing" ? (
            <p>금액과 기준일을 지우고 미입력 상태로 남겨요. 0원으로 저장하지 않아요.</p>
          ) : (
            <div className="form-field">
              <label htmlFor="month-value-date">실제 확인 기준일</label>
              <input
                id="month-value-date"
                type="date"
                required
                min={`${month}-01`}
                max={maxAsOfDate(month)}
                value={draft.asOf}
                onChange={(event) => setDraft({ ...draft, asOf: event.target.value })}
              />
              <p className="muted">
                입력한 오늘의 시각과 별개예요. 선택한 월 안에서 실제 확인한 날짜를 정해 주세요.
              </p>
            </div>
          )}
          <div className="form-field">
            <label htmlFor="month-value-reason">값 변경 사유 (선택)</label>
            <textarea
              id="month-value-reason"
              maxLength={1000}
              rows={3}
              value={draft.reason}
              onChange={(event) => setDraft({ ...draft, reason: event.target.value })}
            />
          </div>
        </fieldset>
        {draft.mode !== "missing" && preview !== null && (
          <p className="amount-preview">
            저장 전 가계 보유분 참고: {formatKrw(preview)} · 최종 계산은 서버에서 확인해요.
          </p>
        )}
        <FormError message={formError} />
        <MonthError error={command.error} />
        {conflict && (
          <section className="conflict-panel">
            <h3>작성한 값과 현재 기록 비교</h3>
            <p>
              작성한 금액과 날짜를 유지했어요. 다른 정정본이나 범위 변경을 확인하기 전에는 저장하지
              않아요.
            </p>
            <button type="button" disabled={command.busy} onClick={() => void compare()}>
              최신 월 기록과 비교
            </button>
            {latest && (
              <>
                <p>
                  현재 {latest.revision_no}차 기록 ·{" "}
                  {latest.state === "confirmed"
                    ? "확정 상태라 직접 수정할 수 없어요."
                    : "작성 가능한 상태예요."}
                </p>
                {currentRow ? (
                  <>
                    <div
                      className="table-scroll"
                      tabIndex={0}
                      role="region"
                      aria-label="월 금액 충돌 비교 표"
                    >
                      <table>
                        <caption>내 입력 기준과 서버 최신 기록</caption>
                        <thead>
                          <tr>
                            <th scope="col">항목</th>
                            <th scope="col">내 작성 내용</th>
                            <th scope="col">서버 최신 값</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <th scope="row">이름</th>
                            <td>{base.row.name}</td>
                            <td>{currentRow.name}</td>
                          </tr>
                          <tr>
                            <th scope="row">금액</th>
                            <td>
                              {draft.mode === "missing"
                                ? "미입력"
                                : formatKrw(
                                    draft.mode === "unchanged"
                                      ? base.row.input_amount_krw
                                      : /^\d+$/.test(draft.amount)
                                        ? BigInt(draft.amount).toString()
                                        : null,
                                  )}
                            </td>
                            <td>{formatKrw(currentRow.input_amount_krw)}</td>
                          </tr>
                          <tr>
                            <th scope="row">기준일</th>
                            <td>{draft.mode === "missing" ? "미입력" : dateLabel(draft.asOf)}</td>
                            <td>{dateLabel(currentRow.as_of_date)}</td>
                          </tr>
                          <tr>
                            <th scope="row">가계 지분</th>
                            <td>{shareToPercent(base.row.household_share)}%</td>
                            <td>{shareToPercent(currentRow.household_share)}%</td>
                          </tr>
                          <tr>
                            <th scope="row">금액 입력 기준</th>
                            <td>{amountBases[base.row.amount_basis]}</td>
                            <td>{amountBases[currentRow.amount_basis]}</td>
                          </tr>
                          <tr>
                            <th scope="row">합계 반영</th>
                            <td>{base.row.inclusion_status === "included" ? "포함" : "제외"}</td>
                            <td>{currentRow.inclusion_status === "included" ? "포함" : "제외"}</td>
                          </tr>
                          <tr>
                            <th scope="row">확인 상태</th>
                            <td>{draft.mode === "missing" ? "미입력" : "작성 중"}</td>
                            <td>{verificationStates[currentRow.verification_state]}</td>
                          </tr>
                          <tr>
                            <th scope="row">변경 사유</th>
                            <td>{draft.reason || "미입력"}</td>
                            <td>{currentRow.change_reason || "미입력"}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    {scopeChanged && (
                      <ScopeChanges before={base.row} after={currentRow} members={members} />
                    )}
                    {scopeChanged && (
                      <label className="checkbox-field">
                        <input
                          type="checkbox"
                          checked={ackScope}
                          onChange={(event) => setAckScope(event.target.checked)}
                        />
                        이름·지분·금액 기준 등 변경된 범위를 확인했어요. 내 금액이 최신 기준에도
                        맞아요.
                      </label>
                    )}
                    {latest.state !== "confirmed" && (
                      <div className="form-actions">
                        <button
                          type="button"
                          disabled={scopeChanged && !ackScope}
                          onClick={() => adopt(true)}
                        >
                          비교한 내 입력 유지
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => adopt(false)}
                        >
                          내 입력 버리고 최신 값 사용
                        </button>
                      </div>
                    )}
                  </>
                ) : (
                  <p>
                    이 자산은 현재 작성 범위에 없어요. 작성한 내용은 위에 남아 있지만 현재 기록에
                    저장할 수 없어요.
                  </p>
                )}
              </>
            )}
          </section>
        )}
        <div className="form-actions">
          <button type="submit" disabled={command.busy || conflict}>
            금액 확인 저장
          </button>
          {command.busy && (
            <button type="button" onClick={command.cancel}>
              요청 대기 중단
            </button>
          )}
          <button
            type="button"
            className="secondary-button"
            disabled={command.busy}
            onClick={close}
          >
            입력 닫기
          </button>
        </div>
      </form>
    </section>
  );
}
