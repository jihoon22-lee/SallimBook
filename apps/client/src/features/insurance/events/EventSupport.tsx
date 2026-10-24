import { SearchableSelect } from "../../../shared/SearchableSelect";
import { useCallback, useId } from "react";
import { Link } from "react-router";
import type { Schema } from "../model";
import { benefits, policyStatuses, treatments, finances } from "../model";
import { InsuranceError } from "../InsuranceSupport";
import { useInsuranceApi } from "../api";
import { useInsuranceEventsApi } from "./api";
import { formatKrw } from "../../assets/months/model";
import { dateLabel, todaySeoul } from "../../finance/dates";
import { AccountSelect } from "../../finance/AccountChoices";
import { PaymentMethod } from "../../fixed/PaymentMethod";
import { allPages, useResource } from "../../finance/queries";
import type { ActualDraft } from "./model";
import { useHouseholdPeople } from "../../household/people";
import { AmountField } from "../../../shared/AmountField";
export function ActualFields({
  draft,
  onChange,
  title,
  accountOnly = false,
  disabled = false,
  amountError = null,
}: {
  draft: ActualDraft;
  onChange: (next: ActualDraft) => void;
  title: string;
  accountOnly?: boolean;
  disabled?: boolean;
  amountError?: string | null;
}) {
  return (
    <fieldset disabled={disabled}>
      <legend>{title} 실제 금전 기록</legend>
      <div className="form-grid">
        <AmountField
          label={`${title} 금액 (원)`}
          required
          value={draft.amount}
          error={amountError}
          onChange={(amount) => onChange({ ...draft, amount })}
        />
        <div className="form-field">
          <label>
            {title} 실제 날짜
            <input
              required
              type="date"
              max={todaySeoul()}
              value={draft.date}
              onChange={(e) => onChange({ ...draft, date: e.target.value })}
            />
          </label>
        </div>
        {accountOnly ? (
          <AccountSelect
            label={`${title} 계좌`}
            value={draft.methodId}
            onChange={(id) => onChange({ ...draft, method: id ? "account" : "none", methodId: id })}
            on={draft.date}
          />
        ) : (
          <PaymentMethod
            method={draft.method}
            id={draft.methodId}
            onChange={(method, methodId) => onChange({ ...draft, method, methodId })}
            on={draft.date}
          />
        )}
        <div className="form-field">
          <label>
            {title} 메모
            <textarea
              maxLength={2000}
              value={draft.note}
              onChange={(e) => onChange({ ...draft, note: e.target.value })}
            />
          </label>
        </div>
      </div>
    </fieldset>
  );
}
export function CashSummary({ cash }: { cash: Schema["CashResponse"] }) {
  return (
    <dl className="metadata-grid">
      <div>
        <dt>원본 금액</dt>
        <dd>{formatKrw(cash.amount_krw)}</dd>
      </div>
      <div>
        <dt>실제 날짜</dt>
        <dd>{dateLabel(cash.occurred_on)}</dd>
      </div>
      <div>
        <dt>원본 상태</dt>
        <dd>{cash.state === "active" ? "활성" : "무효"}</dd>
      </div>
      <div>
        <dt>금전 수단</dt>
        <dd>
          {cash.account_id ? (
            <Link to={`/accounts/${cash.account_id}`}>연결 계좌</Link>
          ) : cash.card_id ? (
            <Link to={`/cards/${cash.card_id}`}>연결 카드</Link>
          ) : (
            "연결 없음"
          )}
        </dd>
      </div>
      <div>
        <dt>원본 메모</dt>
        <dd>{cash.note || "미입력"}</dd>
      </div>
    </dl>
  );
}
export function PolicySelect({
  value,
  onChange,
  label = "청구 보험계약",
  disabled = false,
  required = false,
}: {
  value: string;
  onChange: (id: string) => void;
  label?: string;
  disabled?: boolean;
  required?: boolean;
}) {
  const api = useInsuranceApi();
  const noteId = useId();
  const people = useHouseholdPeople();
  const rows = useResource(
    useCallback(
      () => allPages((cursor) => api.policies({ limit: 200, ...(cursor ? { cursor } : {}) })),
      [api],
    ),
  );
  // Claims and benefits for care before the end are often recorded later, so ended or
  // lapsed policies stay selectable with their status spelled out.
  const selected = rows.data?.find((row) => row.id === value);
  const inactive = selected && selected.status !== "active" ? policyStatuses[selected.status] : "";
  return (
    <div className="form-field">
      <SearchableSelect
        label={label}
        value={value}
        onChange={onChange}
        required={required}
        placeholder={required ? "계약 선택" : "계약 미지정"}
        disabled={disabled || rows.loading || !!rows.error}
        describedBy={inactive ? noteId : undefined}
        options={[
          ...(rows.data ?? []).map((row) => ({
            value: row.id,
            label: `${row.insurer} · ${row.product_name} · ${people.people.find((p) => p.id === row.insured_member_id)?.display_name ?? "가족 확인 필요"} · ${row.contract_start ? `계약 시작 ${dateLabel(row.contract_start)}` : "계약 시작 미입력"} · ${policyStatuses[row.status]}`,
          })),
          ...(value && !rows.data?.some((row) => row.id === value)
            ? [{ value, label: "현재 연결 계약 · 다시 확인 필요", disabled: true }]
            : []),
        ]}
      />
      {inactive && (
        <p className="muted" id={noteId}>
          선택한 계약은 {inactive} 상태예요. 종료 전 진료에 대한 청구·보험금은 나중에도 기록할 수
          있어요.
        </p>
      )}
      <InsuranceError error={rows.error} />
      {rows.error && (
        <button type="button" onClick={() => void rows.reload()}>
          계약 선택 목록 다시 확인
        </button>
      )}
    </div>
  );
}
export function CaseSelect({
  value,
  onChange,
  disabled = false,
  label = "대상 사건",
}: {
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  label?: string;
}) {
  const api = useInsuranceApi();
  const people = useHouseholdPeople();
  const rows = useResource(
    useCallback(
      () => allPages((cursor) => api.cases({ limit: 200, ...(cursor ? { cursor } : {}) })),
      [api],
    ),
  );
  return (
    <div className="form-field">
      <SearchableSelect
        label={label}
        value={value}
        onChange={onChange}
        required
        placeholder="사건 선택"
        disabled={disabled || rows.loading || !!rows.error}
        options={[
          ...(rows.data ?? []).map((row) => ({
            value: row.id,
            label: `${row.title} · ${people.people.find((p) => p.id === row.patient_member_id)?.display_name ?? "가족 확인 필요"} · 진료 시작 ${dateLabel(row.start_on)} · ${treatments[row.treatment_state]} · ${finances[row.financial_state]}`,
          })),
          ...(value && !rows.data?.some((row) => row.id === value)
            ? [{ value, label: "현재 연결 사건 · 다시 확인 필요", disabled: true }]
            : []),
        ]}
      />
      <InsuranceError error={rows.error} />
      {rows.error && (
        <button type="button" onClick={() => void rows.reload()}>
          사건 선택 목록 다시 확인
        </button>
      )}
    </div>
  );
}
export function CaseMoneySummary({ caseId }: { caseId: string }) {
  const api = useInsuranceEventsApi();
  const result = useResource(
    useCallback(() => api.insuranceCaseSummary({ caseId }), [api, caseId]),
  );
  const row = result.data;
  return (
    <section className="card task-summary" aria-label="사건 실제 비용과 순부담">
      <h2>실제 비용과 순현금부담</h2>
      <InsuranceError error={result.error} />
      {result.error && <button onClick={() => void result.reload()}>사건 합계 다시 확인</button>}
      {result.loading && (
        <p className="loading-state" role="status">
          실제 원본의 합계를 확인하고 있어요.
        </p>
      )}
      {row && !result.error && !result.loading && (
        <>
          {/* Screen spec order: paid − refunded = net medical; net medical − net benefit = burden. */}
          <dl className="metric-strip">
            <div>
              <dt>의료 지불금</dt>
              <dd>{formatKrw(row.medical_paid_krw)}</dd>
            </div>
            <div>
              <dt>환불</dt>
              <dd>{formatKrw(row.medical_refunded_krw)}</dd>
            </div>
            <div>
              <dt>순의료비</dt>
              <dd>{formatKrw(row.net_medical_krw)}</dd>
            </div>
            <div>
              <dt>순보험금</dt>
              <dd>{formatKrw(row.net_received_krw)}</dd>
            </div>
            <div className="metric-primary">
              <dt>순현금부담</dt>
              <dd>{formatKrw(row.net_burden_krw)}</dd>
            </div>
          </dl>
          <details className="summary-details">
            <summary>보험금 수령·반환과 급부유형별 계산 내역</summary>
            <dl className="metadata-grid">
              <div>
                <dt>실제 보험금 수령</dt>
                <dd>{formatKrw(row.insurance_received_krw)}</dd>
              </div>
              <div>
                <dt>보험사 반환</dt>
                <dd>{formatKrw(row.insurance_returned_krw)}</dd>
              </div>
            </dl>
            <ul>
              {row.benefits.map((b) => (
                <li key={b.benefit_type}>
                  {benefits[b.benefit_type]}: 수령 {formatKrw(b.received_krw)} − 반환{" "}
                  {formatKrw(b.returned_krw)} = {formatKrw(b.net_received_krw)}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
      <p className="muted">
        같은 비용을 여러 청구에 연결해도 한 번만 합산해요. 청구액·결정액·보험료는 실제 수령에 더하지
        않아요. 음수 부담은 그대로 표시하며 보상 적정성을 판단하지 않아요.
      </p>
    </section>
  );
}
export function NodeMoneySummary({ caseId, nodeId }: { caseId: string; nodeId: string }) {
  const api = useInsuranceEventsApi();
  const result = useResource(
    useCallback(() => api.medicalNodeSummary({ caseId, nodeId }), [api, caseId, nodeId]),
  );
  return (
    <section aria-label="진료 하위 비용 합계">
      <h3>이 진료와 하위 진료의 실제 비용</h3>
      <InsuranceError error={result.error} />
      {result.error && <button onClick={() => void result.reload()}>진료 합계 다시 확인</button>}
      {result.data && !result.loading && !result.error && (
        <p>
          {result.data.subtree_node_count}개 진료 · 지불 {formatKrw(result.data.medical_paid_krw)} −
          환불 {formatKrw(result.data.medical_refunded_krw)} = 순의료비{" "}
          {formatKrw(result.data.net_medical_krw)}
        </p>
      )}
      <p className="muted">하위 합계를 별도 지출로 다시 등록하지 않아요.</p>
    </section>
  );
}

export function ExpenseSummary({ row }: { row: Schema["ExpenseResponse"] }) {
  return (
    <>
      <CashSummary cash={row.cash} />
      <dl className="metadata-grid">
        <div>
          <dt>의료기관</dt>
          <dd>{row.provider_name || "미입력"}</dd>
        </div>
        <div>
          <dt>영수증 참고번호</dt>
          <dd>{row.receipt_reference || "미입력"}</dd>
        </div>
        <div>
          <dt>총진료비 참고</dt>
          <dd>{formatKrw(row.gross_medical_krw)}</dd>
        </div>
        <div>
          <dt>공단 부담액 참고</dt>
          <dd>{formatKrw(row.public_coverage_krw)}</dd>
        </div>
      </dl>
      <div className="form-actions">
        <Link to={`/insurance/cases/${row.case_id}`}>의료비 사건</Link>
        <Link to={`/insurance/cases/${row.case_id}/nodes/${row.node_id}`}>비용 귀속 진료</Link>
      </div>
      <h3>원본 지불금의 설명용 명세</h3>
      {row.lines.length ? (
        <ul>
          {row.lines.map((line) => (
            <li key={line.id}>
              {line.label} · {line.detail_type} · {formatKrw(line.amount_krw)}
            </li>
          ))}
        </ul>
      ) : (
        <p>별도 분해 명세가 없어요.</p>
      )}
      <p className="muted">명세는 원본 지불금의 분해예요. 별도 지출로 다시 합산하지 않아요.</p>
    </>
  );
}
