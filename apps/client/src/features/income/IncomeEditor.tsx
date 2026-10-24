import { useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { Link, useNavigate } from "react-router";
import { toApiError } from "../../platform/api";
import { useMonth } from "../../shared/MonthContext";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { formatKrw } from "../assets/months/model";
import { CashflowError, RecordedMoneyNotice, SaveControls } from "../finance/FinancialFeedback";
import { dateLabel } from "../finance/dates";
import { useAuth } from "../auth/AuthProvider";
import { allPages } from "../finance/queries";
import { PreviousIncome } from "./PreviousIncome";
import { IncomeFields } from "./IncomeFields";
import { useIncomeApi } from "./api";
import { excludeSelf, incomeDraft, incomeInput, incomePatch, preserveIncomeChanges } from "./model";
import type { DuplicateResponse, Income, IncomeDraft, IncomeInput } from "./model";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { FormError, useSubmitAttempt } from "../../shared/formValidation";
import { krwFieldError } from "../../shared/krw";
import { rememberFocus } from "../../shared/focusKeeper";

export function IncomeEditor({ initial }: { initial?: Income }) {
  const api = useIncomeApi();
  const navigate = useNavigate();
  const { month } = useMonth();
  const command = useMonthCommand();
  const { state } = useAuth();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => ({
    ...incomeDraft(month, initial),
    ...(!initial && state.status === "authenticated" ? { member: state.member.member_id } : {}),
  }));
  const [showPrevious, setShowPrevious] = useState(false);
  const [copySource, setCopySource] = useState<Income | null>(null);
  const [reason, setReason] = useState("");
  const [duplicates, setDuplicates] = useState<DuplicateResponse | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [checking, setChecking] = useState(false);
  const [latest, setLatest] = useState<Income | null>(null);
  const [validation, setValidation] = useState("");
  const attempt = useSubmitAttempt();
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const input = incomeInput(draft);
  const body = base
    ? incomePatch(incomeDraft(base.period_month, base), draft, reason, acknowledged)
    : input
      ? { ...input, duplicate_acknowledged: acknowledged }
      : null;
  const key = useIdempotencyKey(JSON.stringify([base?.id, base?.version, body]));
  function change(next: IncomeDraft) {
    setDraft(next);
    setDuplicates(null);
    setAcknowledged(false);
    setValidation("");
  }
  async function check(form: HTMLFormElement | null) {
    if (!input) {
      setValidation("구성원·월·금액·실제 날짜를 확인해 주세요.");
      if (form) attempt.reject(form);
      return null;
    }
    setChecking(true);
    command.setError(null);
    try {
      let result = excludeSelf(
        await api.duplicates({
          month: input.period_month,
          member_id: input.member_id,
          kind: input.kind,
          date_precision: input.date_precision,
        }),
        base?.id,
      );
      if (copySource && !base) {
        const existing = await allPages((cursor) =>
          api.list({
            month: input.period_month,
            member_id: input.member_id,
            kind: input.kind,
            state: "active",
            limit: 200,
            ...(cursor ? { cursor } : {}),
          }),
        );
        const items = [
          ...new Map([...result.items, ...existing].map((row) => [row.id, row])).values(),
        ];
        result = { ...result, items, suspected: items.length > 0 || result.truncated };
      }
      if (command.mounted.current) setDuplicates(result);
      return result;
    } catch (error) {
      if (command.mounted.current) command.setError(toApiError(error));
      return null;
    } finally {
      if (command.mounted.current) setChecking(false);
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    event.preventDefault();
    if (checking || command.busy) return;
    if (!body) {
      setValidation(
        base
          ? "변경한 수입 내용과 정정 사유를 확인해 주세요."
          : "구성원·월·금액·실제 날짜를 확인해 주세요.",
      );
      attempt.reject(form);
      return;
    }
    // The duplicate check disables the form before the save does, so keep the focus here.
    const restoreFocus = rememberFocus();
    try {
      await save(form);
    } finally {
      restoreFocus();
    }
  }
  async function save(form: HTMLFormElement) {
    const checked = duplicates ?? (await check(form));
    if (!checked || !command.mounted.current) return;
    if (checked.suspected && !acknowledged) {
      setValidation("아래 기존 기록을 확인하고 중복 여부를 선택해 주세요.");
      return;
    }
    const result = await command.run((signal) =>
      base
        ? api.correct(
            base.id,
            body as components["schemas"]["IncomePatch"],
            base.version,
            key,
            signal,
          )
        : api.create(body as IncomeInput, key, signal),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      navigate(`/income/${result.value.id}`, { replace: true });
    }
  }
  async function compareLatest() {
    if (!base) return;
    setChecking(true);
    try {
      const row = await api.get(base.id);
      if (command.mounted.current) setLatest(row);
    } catch (error) {
      command.setError(toApiError(error));
    } finally {
      if (command.mounted.current) setChecking(false);
    }
  }
  return (
    <section className="card">
      <h2>{base ? "수입 정정" : "새 수입 기록"}</h2>
      <RecordedMoneyNotice />
      {!base && (
        <>
          <button
            type="button"
            className="secondary-button"
            disabled={command.busy || checking}
            onClick={() => setShowPrevious(true)}
          >
            지난달 수입에서 초안 불러오기
          </button>
          {showPrevious && !command.busy && !checking && (
            <PreviousIncome
              key={draft.month}
              month={draft.month}
              close={() => setShowPrevious(false)}
              choose={(row) => {
                change({ ...incomeDraft(draft.month, row), month: draft.month, date: "" });
                setCopySource(row);
                setShowPrevious(false);
                setDirty(true);
              }}
            />
          )}
          {copySource && (
            <p role="status">
              {copySource.period_month} 수입을 새 초안으로 불러왔어요. 아직 저장하지 않았어요.{" "}
              <Link to={`/income/${copySource.id}`}>불러온 원본 확인</Link>
            </p>
          )}
        </>
      )}
      <form onInput={() => setDirty(true)} onSubmit={(event) => void submit(event)}>
        <IncomeFields
          draft={draft}
          onChange={change}
          disabled={command.busy || checking}
          amountError={
            attempt.attempted
              ? krwFieldError(draft.amount, { required: true, positive: true })
              : null
          }
        />
        {base && (
          <div className="form-field">
            <label>
              정정 사유
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={500}
                required
                disabled={command.busy || checking}
              />
            </label>
          </div>
        )}
        <button
          type="button"
          className="secondary-button"
          disabled={checking || command.busy}
          onClick={(event) => void check(event.currentTarget.form)}
        >
          중복 기록 확인
        </button>
        {checking && <p role="status">기존 기록을 확인하고 있어요.</p>}
        {duplicates && (
          <section className="review-panel" aria-label="수입 중복 검토">
            <h3>
              {duplicates.suspected
                ? copySource
                  ? "이번 달에 같은 구성원·종류의 수입이 있어요"
                  : "월합계와 일별 기록이 함께 있어요"
                : copySource
                  ? "이번 달에 같은 구성원·종류의 기존 수입은 없어요"
                  : "날짜 정밀도가 다른 기존 기록은 없어요"}
            </h3>
            {duplicates.items.map((row) => (
              <p key={row.id}>
                <Link to={`/income/${row.id}`}>
                  {formatKrw(row.amount_krw)} ·{" "}
                  {row.date_precision === "month" ? "월합계" : dateLabel(row.occurred_on)}
                </Link>
              </p>
            ))}
            {duplicates.truncated && (
              <p>
                일부 후보만 표시했어요. 수입 목록에서 같은 월·구성원·종류의 기록 전체를 확인해
                주세요.
              </p>
            )}
            {duplicates.suspected && (
              <>
                <p>같은 수입의 입력 방식을 바꾸려면 합계를 유지하는 전환 기능을 이용해 주세요.</p>
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={acknowledged}
                    onChange={(event) => setAcknowledged(event.target.checked)}
                    disabled={command.busy}
                  />
                  기존 기록과 별개의 수입임을 확인했어요.
                </label>
              </>
            )}
          </section>
        )}
        <FormError message={validation} />
        <CashflowError error={command.error} />
        {base && command.error?.status === 409 && (
          <button
            type="button"
            disabled={checking || command.busy}
            onClick={() => void compareLatest()}
          >
            최신 수입과 비교
          </button>
        )}
        {latest && (
          <section className="review-panel">
            <h3>다른 곳에서 저장한 현재 수입</h3>
            <p>
              {formatKrw(latest.amount_krw)} · {latest.period_month} ·{" "}
              {latest.date_precision === "month" ? "월합계" : dateLabel(latest.occurred_on)} · 버전{" "}
              {latest.version}
            </p>
            <p>{latest.note || "메모 없음"}</p>
            <p>
              내가 바꾼 필드는 유지하고 나머지는 현재 기록을 사용해요. 반환 등으로 정정이 제한되면
              현재 상세에서 확인해 주세요.
            </p>
            <button
              type="button"
              disabled={!latest.editable}
              onClick={() => {
                change(
                  preserveIncomeChanges(
                    incomeDraft(base!.period_month, base),
                    draft,
                    incomeDraft(latest.period_month, latest),
                  ),
                );
                setBase(latest);
                setLatest(null);
                command.setError(null);
              }}
            >
              비교한 내 변경 유지
            </button>
            <Link to={`/income/${latest.id}`}>현재 상세 보기</Link>
          </section>
        )}
        <SaveControls
          backTo={base ? `/income/${base.id}` : "/income"}
          busy={command.busy}
          cancel={command.cancel}
          disabled={checking || (!!base && !base.editable)}
          label={base ? "수입 정정 저장" : "수입 기록 저장"}
        />
      </form>
    </section>
  );
}
