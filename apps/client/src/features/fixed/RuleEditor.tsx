import { DateInput } from "../../shared/DateInput";
import { OptionalFields } from "../../shared/OptionalFields";
import { useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { Link, useNavigate } from "react-router";
import { toApiError } from "../../platform/api";
import type { ApiError } from "../../platform/api";
import { useMonthCommand, useIdempotencyKey } from "../assets/months/useMonthCommand";
import { CashflowError, SaveControls } from "../finance/FinancialFeedback";
import { dateLabel, todaySeoul } from "../finance/dates";
import { useFixedApi } from "./api";
import {
  changeDraft,
  displayedTerms,
  economicTypes,
  frequencies,
  pendingVersions,
  preparationWindow,
  preserveRuleChanges,
  ruleCommandMessages,
  ruleDraft,
  ruleInput,
  withdrawalPlan,
} from "./model";
import type { Rule, RuleDraft } from "./model";
import { LiabilitySelect, PaymentMethod } from "./PaymentMethod";
import { RuleSummary } from "./RuleSummary";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { AmountField } from "../../shared/AmountField";
import { FormError, useSubmitAttempt } from "../../shared/formValidation";
import { krwFieldError } from "../../shared/krw";
export function RuleCommandError({ error }: { error: ApiError | null }) {
  const message = error && ruleCommandMessages[error.code];
  if (message)
    return (
      <div className="auth-message" role="alert">
        <p>{message}</p>
      </div>
    );
  return <CashflowError error={error} />;
}
export function WithdrawalNotice({ withdrawn }: { withdrawn: { effective_from: string }[] }) {
  if (!withdrawn.length) return null;
  return (
    <p>
      {withdrawn.map((row) => dateLabel(row.effective_from)).join(", ")} 적용 예정 변경은 함께
      철회돼요.
    </p>
  );
}
export function RuleEditor({ initial }: { initial?: Rule }) {
  const [prepare, setPrepare] = useState<{
    input: components["schemas"]["GenerateObligations"];
    key: string;
  } | null>(null);
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const api = useFixedApi();
  const navigate = useNavigate();
  const command = useMonthCommand();
  const [base, setBase] = useState(initial);
  // A change starts from the version it will follow: today's terms until a start date is
  // chosen, then the pending version that date comes after, so that change is not undone.
  const [draft, setDraft] = useState(() => (initial ? changeDraft(initial, "") : ruleDraft()));
  const [reason, setReason] = useState("");
  const [latest, setLatest] = useState<Rule | null>(null);
  const [conflict, setConflict] = useState(false);
  const [validation, setValidation] = useState("");
  const [reviewAck, setReviewAck] = useState(false);
  const attempt = useSubmitAttempt();
  const input = ruleInput(draft);
  const changed: components["schemas"]["RuleChange"] | null = input
    ? (({ effective_until: _until, end_reason: _endReason, ...terms }) => ({
        ...terms,
        reason: reason.trim(),
      }))(input)
    : null;
  const plan = base ? withdrawalPlan(base, draft.from) : null;
  const valid =
    !!input &&
    (!base ||
      (!!reason.trim() &&
        reason.length <= 500 &&
        draft.from >= todaySeoul() &&
        draft.from > plan!.floor &&
        (!base.ended_on || draft.from < base.ended_on) &&
        reviewAck));
  const payload = base ? changed : input;
  const key = useIdempotencyKey(JSON.stringify([base?.id, base?.version, payload]));
  function change(field: keyof RuleDraft, value: string) {
    setDraft((old) => {
      const next = {
        ...old,
        [field]: value,
        ...(field === "until" && !value ? { endReason: "" } : {}),
        ...(field === "economic" && value !== "loan" ? { loan: "" } : {}),
      };
      return base && field === "from"
        ? preserveRuleChanges(changeDraft(base, old.from), next, changeDraft(base, value))
        : next;
    });
    setReviewAck(false);
    setValidation("");
  }
  async function prepareSaved(task: NonNullable<typeof prepare>) {
    const result = await command.run((signal) => api.generate(task.input, task.key, signal));
    if (result.ok && command.mounted.current) {
      guard.release();
      navigate(`/fixed-payments/rules/${task.input.rule_id}`, {
        replace: true,
        state: {
          prepared: `${dateLabel(task.input.start_date)} ~ ${dateLabel(task.input.end_date)} 예정 회차 ${result.value.items.length}건을 확인했어요. 실제 납부는 별도로 기록해 주세요.`,
        },
      });
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    event.preventDefault();
    if (prepare) {
      await prepareSaved(prepare);
      return;
    }
    if (conflict || !valid || !input || !changed) {
      setValidation("필수 정보·날짜·금액과 적용 범위를 확인해 주세요.");
      attempt.reject(form);
      return;
    }
    const result = await command.run((signal) =>
      base
        ? api.changeRule(base.id, changed, base.version, key, signal)
        : api.createRule(input, key, signal),
    );
    if (result.ok && command.mounted.current) {
      // Save and prepare are distinct idempotent commands. Never repeat a known saved rule.
      const task = {
        input: { rule_id: result.value.id, ...preparationWindow(draft.from) },
        key: `prepare:${key}`,
      };
      setPrepare(task);
      setDirty(false);
      guard.release();
      await prepareSaved(task);
    } else if (!result.ok && result.error.code === "VERSION_CONFLICT") setConflict(true);
  }
  async function compare() {
    if (!base) return;
    try {
      const row = await api.rule(base.id);
      if (command.mounted.current) setLatest(row);
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  return (
    <section className="card">
      <h2>{base ? "새 적용기간으로 규칙 변경" : "고정 납부 규칙 등록"}</h2>
      <p>
        짧은 달은 말일로 보정하고 다음 달에는 원래 기준일로 돌아와요. 주말·공휴일은 자동으로
        이동하지 않아요.
      </p>
      <p>
        저장하면 이번 달 또는 적용 시작월부터 12개월의 예정 회차를 함께 준비해요. 실제 납부는 별도로
        확인해 기록해요.
      </p>
      <form onInput={() => setDirty(true)} onSubmit={(event) => void submit(event)}>
        <fieldset disabled={command.busy || Boolean(prepare)}>
          <legend>반복 규칙</legend>
          <div className="form-grid">
            <div className="form-field">
              <label>
                규칙 이름
                <input
                  value={draft.title}
                  maxLength={120}
                  required
                  onChange={(event) => change("title", event.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                납부 분류
                <input
                  value={draft.category}
                  maxLength={40}
                  list="fixed-categories"
                  required
                  onChange={(event) => change("category", event.target.value)}
                />
                <datalist id="fixed-categories">
                  <option value="구독" />
                  <option value="보험료" />
                  <option value="통신비" />
                  <option value="대출" />
                  <option value="연금" />
                </datalist>
              </label>
            </div>
            <div className="form-field">
              <label>
                납부 성격
                <select
                  value={draft.economic}
                  onChange={(event) => change("economic", event.target.value)}
                >
                  {Object.entries(economicTypes).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {draft.economic === "loan" && (
              <LiabilitySelect value={draft.loan} onChange={(value) => change("loan", value)} />
            )}
            <div className="form-field">
              <label>
                예정금액 방식
                <select
                  value={draft.amountMode}
                  onChange={(event) => change("amountMode", event.target.value)}
                >
                  <option value="fixed">고정 금액</option>
                  <option value="variable">변동 금액 · 미정 가능</option>
                </select>
              </label>
            </div>
            <AmountField
              label="원화 예정금액 (원)"
              value={draft.amount}
              required={draft.amountMode === "fixed"}
              hint="변동 금액을 비우면 미정이에요. 0원과 구분해요."
              error={
                attempt.attempted
                  ? krwFieldError(draft.amount, {
                      required: draft.amountMode === "fixed",
                      positive: false,
                    })
                  : null
              }
              onChange={(value) => change("amount", value)}
            />
            <div className="form-field">
              <label>
                반복 주기
                <select
                  value={draft.frequency}
                  onChange={(event) => change("frequency", event.target.value)}
                >
                  {Object.entries(frequencies).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-field">
              <label>
                주기 간격
                <input
                  type="number"
                  min={1}
                  max={3650}
                  step={1}
                  required
                  value={draft.interval}
                  onChange={(event) => change("interval", event.target.value)}
                />
              </label>
              <p>
                {draft.frequency === "monthly"
                  ? "개월마다"
                  : draft.frequency === "annual"
                    ? "년마다"
                    : "일마다"}
              </p>
            </div>
            <div className="form-field">
              <label>
                주기 기준일
                <DateInput
                  required
                  value={draft.anchor}
                  onChange={(event) => change("anchor", event.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                적용 시작일
                <DateInput
                  required
                  value={draft.from}
                  min={base ? todaySeoul() : undefined}
                  onChange={(event) => change("from", event.target.value)}
                />
              </label>
              {base && plan && (
                <>
                  <p className="muted">
                    현재 적용 중인 시작일 {dateLabel(plan.floor)}보다 뒤여야 해요. 시작 전 예정
                    변경과 같거나 앞선 날짜를 고르면 그 예정 변경은 철회돼요.
                    {base.ended_on
                      ? ` 종료 적용일 ${dateLabel(base.ended_on)}은 유지되며 그 전의 적용일만 사용할 수 있어요.`
                      : ""}
                  </p>
                  <WithdrawalNotice withdrawn={plan.withdrawn} />
                </>
              )}
            </div>
            <PaymentMethod
              method={draft.method}
              id={draft.methodId}
              onChange={(method, methodId) => {
                setDraft((old) => ({ ...old, method, methodId }));
                setReviewAck(false);
              }}
            />
            <OptionalFields
              title="종료일·외화 참고·메모"
              hasError={Boolean(validation)}
              hasValues={Boolean(
                draft.until ||
                draft.endReason ||
                draft.currency ||
                draft.foreignAmount ||
                draft.note,
              )}
            >
              {!base && (
                <>
                  <div className="form-field">
                    <label>
                      처음 등록하는 종료 적용일 (선택)
                      <DateInput
                        value={draft.until}
                        min={draft.from || undefined}
                        onChange={(event) => change("until", event.target.value)}
                      />
                    </label>
                  </div>
                  {draft.until && (
                    <div className="form-field">
                      <label>
                        종료 사유
                        <textarea
                          maxLength={500}
                          required
                          value={draft.endReason}
                          onChange={(event) => change("endReason", event.target.value)}
                        />
                      </label>
                    </div>
                  )}
                </>
              )}
              <div className="form-field">
                <label>
                  외화 참고 통화 (선택)
                  <input
                    maxLength={3}
                    value={draft.currency}
                    placeholder="USD"
                    onChange={(event) => change("currency", event.target.value.toUpperCase())}
                  />
                </label>
              </div>
              <div className="form-field">
                <label>
                  외화 참고금액 (선택)
                  <input
                    inputMode="decimal"
                    maxLength={40}
                    value={draft.foreignAmount}
                    onChange={(event) => change("foreignAmount", event.target.value)}
                  />
                </label>
              </div>
              <div className="form-field">
                <label>
                  규칙 메모
                  <textarea
                    value={draft.note}
                    maxLength={2000}
                    onChange={(event) => change("note", event.target.value)}
                  />
                </label>
              </div>
              <p className="muted">외화 참고금액은 원화 예정·실제 금액으로 자동 환산하지 않아요.</p>
            </OptionalFields>
          </div>
          {base && (
            <>
              <div className="form-field">
                <label>
                  규칙 변경 사유
                  <textarea
                    maxLength={500}
                    required
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                  />
                </label>
              </div>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={reviewAck}
                  onChange={(event) => setReviewAck(event.target.checked)}
                />
                새 적용기간의 미래 미납 회차가 바뀌며, 과거·실제 납부·수동 예외는 보존됨을
                확인했어요.
              </label>
            </>
          )}
        </fieldset>
        {prepare && (
          <section className="review-panel">
            <p role="status">규칙은 저장됐어요. 예정 회차 준비 결과를 확인해 주세요.</p>
            <p>
              {dateLabel(prepare.input.start_date)} ~ {dateLabel(prepare.input.end_date)} · 실제
              납부액은 생기지 않아요.
            </p>
            {!command.busy && (
              <Link to={`/fixed-payments/rules/${prepare.input.rule_id}`}>
                저장된 규칙 확인 · 회차는 월별 화면에서 준비 가능
              </Link>
            )}
          </section>
        )}
        <FormError message={validation} />
        <RuleCommandError error={command.error} />
        {conflict && (
          <section className="review-panel">
            <h3>현재 규칙과 변경 비교</h3>
            <button type="button" disabled={command.busy} onClick={() => void compare()}>
              현재 규칙 다시 확인
            </button>
            {latest && (
              <>
                <h4>{displayedTerms(latest).title}</h4>
                <RuleSummary terms={displayedTerms(latest)} />
                {pendingVersions(latest).map((row) => (
                  <div key={row.id}>
                    <h5>{dateLabel(row.effective_from)}부터 적용 예정</h5>
                    <RuleSummary terms={row} />
                  </div>
                ))}
                <button
                  type="button"
                  disabled={!!latest.ended_on && latest.ended_on <= todaySeoul()}
                  onClick={() => {
                    setDraft(
                      preserveRuleChanges(
                        changeDraft(base!, draft.from),
                        draft,
                        changeDraft(latest, draft.from),
                      ),
                    );
                    setBase(latest);
                    setLatest(null);
                    setConflict(false);
                    setReviewAck(false);
                    command.setError(null);
                  }}
                >
                  비교한 규칙 변경 유지
                </button>
              </>
            )}
          </section>
        )}
        <SaveControls
          backTo={base ? `/fixed-payments/rules/${base.id}` : "/fixed-payments/rules"}
          busy={command.busy}
          cancel={command.cancel}
          disabled={conflict}
          label={
            prepare ? "예정 회차 준비 다시 확인" : base ? "새 적용기간 저장" : "납부 규칙 저장"
          }
        />
      </form>
    </section>
  );
}
