import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";
import { toApiError } from "../../platform/api";
import { useMonth, isValidMonth } from "../../shared/MonthContext";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { formatKrw } from "../assets/months/model";
import { allPages } from "../finance/queries";
import {
  AuthenticatedFinance,
  CashflowError,
  RecordedMoneyNotice,
  SaveControls,
} from "../finance/FinancialFeedback";
import { isUuid, useHouseholdMembers, MemberLoadError, dateLabel } from "../finance/FinanceSupport";
import { useIncomeApi } from "./api";
import { conversionTotal, incomeDraft, incomeInput, manualKinds } from "./model";
import type { Income, IncomeConversion, IncomeDraft } from "./model";
import { IncomeFields } from "./IncomeFields";
function ConversionWorkspace() {
  const api = useIncomeApi();
  const command = useMonthCommand();
  const navigate = useNavigate();
  const { month } = useMonth();
  const members = useHouseholdMembers();
  const [period, setPeriod] = useState(month);
  const [member, setMember] = useState("");
  const [kind, setKind] = useState<IncomeDraft["kind"]>("salary");
  const [sources, setSources] = useState<Income[] | null>(null);
  const [replacements, setReplacements] = useState<IncomeDraft[]>([]);
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [loading, setLoading] = useState(false);
  const sourceReady =
    !!sources?.length &&
    sources.length <= 100 &&
    sources.every((row) => row.editable && row.date_precision === sources[0]!.date_precision);
  const destination = sources?.[0]?.date_precision === "month" ? "day" : "month";
  const replacementScopeValid = replacements.every(
    (row) =>
      row.month === period &&
      row.member === member &&
      row.kind === kind &&
      row.precision === destination,
  );
  const sourceTotal = sources ? conversionTotal(sources) : "0";
  const parsed = replacements.map(incomeInput);
  const replacementTotal = parsed.every((item) => item !== null) ? conversionTotal(parsed) : null;
  const payload: IncomeConversion | null =
    sources && replacementScopeValid && parsed.every((item) => item !== null)
      ? {
          sources: sources.map((row) => ({ id: row.id, version: row.version })),
          replacements: parsed.map(({ duplicate_acknowledged: _acknowledged, ...row }) => row),
          reason: reason.trim(),
        }
      : null;
  const key = useIdempotencyKey(JSON.stringify(payload));
  function scopeChange(update: () => void) {
    update();
    setSources(null);
    setReplacements([]);
    setAck(false);
    command.setError(null);
  }
  async function loadSources(keep = false) {
    if (!isValidMonth(period) || !isUuid(member)) return;
    setLoading(true);
    command.setError(null);
    setAck(false);
    try {
      const rows = await allPages((cursor) =>
        api.list({
          month: period,
          kind,
          member_id: member,
          state: "active",
          limit: 200,
          ...(cursor ? { cursor } : {}),
        }),
      );
      if (!command.mounted.current) return;
      setSources(rows);
      if (!keep)
        setReplacements(
          rows.length
            ? [
                {
                  ...incomeDraft(period),
                  member,
                  kind,
                  precision: rows[0]!.date_precision === "month" ? "day" : "month",
                  amount: conversionTotal(rows),
                },
              ]
            : [],
        );
    } catch (error) {
      if (command.mounted.current) command.setError(toApiError(error));
    } finally {
      if (command.mounted.current) setLoading(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!payload || !sourceReady || !ack || !reason.trim() || sourceTotal !== replacementTotal)
      return;
    const result = await command.run((signal) => api.convert(payload, key, signal));
    if (result.ok && command.mounted.current) navigate("/income");
  }
  return (
    <>
      <RecordedMoneyNotice />
      <section className="card">
        <h2>전환할 수입 범위</h2>
        <p>
          같은 월·구성원·종류의 모든 활성 수입을 함께 전환해요. 원본은 사유와 함께 무효로 남기고
          같은 합계의 새 기록을 만들어요.
        </p>
        <fieldset disabled={command.busy || loading}>
          <legend>원본 선택</legend>
          <div className="form-grid">
            <div className="form-field">
              <label>
                전환 귀속월
                <input
                  type="month"
                  value={period}
                  onChange={(event) => scopeChange(() => setPeriod(event.target.value))}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                전환 구성원
                <select
                  value={member}
                  onChange={(event) => scopeChange(() => setMember(event.target.value))}
                >
                  <option value="">구성원 선택</option>
                  {members.members.map((m) => (
                    <option key={m.member_id} value={m.member_id}>
                      {m.display_name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-field">
              <label>
                전환 수입 종류
                <select
                  value={kind}
                  onChange={(event) =>
                    scopeChange(() => setKind(event.target.value as IncomeDraft["kind"]))
                  }
                >
                  {Object.entries(manualKinds).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <button
            type="button"
            disabled={!isUuid(member) || !isValidMonth(period)}
            onClick={() => void loadSources()}
          >
            원본 수입 전체 확인
          </button>
        </fieldset>
        <MemberLoadError error={members.error} retry={members.retry} />
      </section>
      {loading && (
        <p className="loading-state" role="status">
          전환할 원본을 불러오고 있어요.
        </p>
      )}
      <CashflowError error={command.error} />
      {sources && (
        <section className="card">
          <h2>전환 전 원본 {sources.length}개</h2>
          <ul>
            {sources.map((row) => (
              <li key={row.id}>
                {formatKrw(row.amount_krw)} ·{" "}
                {row.date_precision === "month" ? "월합계" : dateLabel(row.occurred_on)} · 버전{" "}
                {row.version}
              </li>
            ))}
          </ul>
          <p>원본 합계: {formatKrw(sourceTotal)}</p>
          {!sourceReady && (
            <p role="alert">
              활성 반환이 있거나 날짜 정밀도가 섞였거나 원본이 없으면 전환할 수 없어요. 한 번에
              100개까지 전환할 수 있어요. 원본 기록을 먼저 정리해 주세요.
            </p>
          )}
        </section>
      )}
      {sourceReady && (
        <section className="card">
          <h2>{destination === "day" ? "실제 입금일별 기록으로 전환" : "월합계 기록으로 전환"}</h2>
          <form onSubmit={(event) => void submit(event)}>
            {replacements.map((draft, index) => (
              <section className="conversion-row" key={index} aria-label={`대체 수입 ${index + 1}`}>
                <h3>대체 수입 {index + 1}</h3>
                <IncomeFields
                  draft={draft}
                  fixedScope
                  disabled={command.busy || loading}
                  onChange={(next) => {
                    setReplacements((rows) => rows.map((row, i) => (i === index ? next : row)));
                    setAck(false);
                  }}
                />
                {replacements.length > 1 && (
                  <button
                    type="button"
                    disabled={command.busy || loading}
                    onClick={() => {
                      setReplacements((rows) => rows.filter((_, i) => i !== index));
                      setAck(false);
                    }}
                  >
                    대체 수입 {index + 1} 제거
                  </button>
                )}
              </section>
            ))}
            <button
              type="button"
              disabled={command.busy || loading || replacements.length >= 100}
              onClick={() => {
                setReplacements((rows) => [
                  ...rows,
                  { ...incomeDraft(period), member, kind, precision: destination },
                ]);
                setAck(false);
              }}
            >
              대체 수입 추가
            </button>
            {!replacementScopeValid && (
              <p role="alert">
                원본의 날짜 정밀도가 바뀌었어요. 현재 원본을 기준으로 대체 입력을 다시 만들어
                주세요.{" "}
                <button
                  type="button"
                  disabled={command.busy || loading}
                  onClick={() => void loadSources()}
                >
                  대체 입력 새로 만들기
                </button>
              </p>
            )}
            <p>
              전환 전 {formatKrw(sourceTotal)} · 전환 후{" "}
              {replacementTotal === null ? "금액 확인 필요" : formatKrw(replacementTotal)}
            </p>
            {replacementTotal !== null && replacementTotal !== sourceTotal && (
              <p role="alert">전환 전후 합계가 같아야 해요.</p>
            )}
            <div className="form-field">
              <label>
                전환 사유
                <textarea
                  maxLength={500}
                  required
                  value={reason}
                  disabled={command.busy || loading}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
            </div>
            <label className="checkbox-field">
              <input
                type="checkbox"
                checked={ack}
                disabled={command.busy || loading}
                onChange={(event) => setAck(event.target.checked)}
              />
              원본 전체와 같은 합계의 대체 기록을 확인했어요.
            </label>
            {command.error?.status === 409 && (
              <button
                type="button"
                disabled={command.busy || loading}
                onClick={() => void loadSources(true)}
              >
                현재 원본 다시 비교
              </button>
            )}
            <SaveControls
              backTo={"/income"}
              busy={command.busy}
              cancel={command.cancel}
              disabled={
                loading || !ack || !reason.trim() || !payload || sourceTotal !== replacementTotal
              }
              label="합계를 유지하고 전환"
            />
          </form>
        </section>
      )}
    </>
  );
}
export function IncomeConversionPage() {
  return (
    <AuthenticatedFinance
      title="월합계·일별 수입 전환"
      description="같은 수입을 두 번 더하지 않고 입력 방식을 바꿔요."
    >
      <ConversionWorkspace />
    </AuthenticatedFinance>
  );
}
