import { SearchableSelect } from "../../../shared/SearchableSelect";
import { treatments, finances, policyStatuses } from "../model";
import { useCallback } from "react";
import { Link } from "react-router";
import { FilterPanel } from "../../../shared/TaskLayout";
import { formatKrw } from "../../assets/months/model";
import { dateLabel, isDateOnly, isUuid } from "../../finance/dates";
import { allPages, useResource } from "../../finance/queries";
import { useUrlFilters } from "../../finance/useUrlFilters";
import { useHouseholdPeople } from "../../household/people";
import { InsuranceError, InsurancePage } from "../InsuranceSupport";
import { useInsuranceApi } from "../api";
import { useInsuranceEventsApi } from "../events/api";
import { claimStates } from "../events/model";
import type { Schema } from "../model";

function ClaimTasks() {
  const api = useInsuranceEventsApi();
  const core = useInsuranceApi();
  const people = useHouseholdPeople();
  const { params, filter, reset } = useUrlFilters();
  const state = params.get("state") ?? "";
  const caseId = params.get("case") ?? "";
  const policyId = params.get("policy") ?? "";
  const patient = params.get("patient") ?? "";
  const receipt = params.get("receipt") ?? "";
  const from = params.get("from") ?? "";
  const until = params.get("until") ?? "";
  const order = params.get("order") ?? "priority";
  const result = useResource(
    useCallback(async () => {
      const [claims, cases, policies] = await Promise.all([
        allPages((cursor) =>
          api.listInsuranceClaims({
            query: {
              limit: 200,
              ...(cursor ? { cursor } : {}),
              ...(Object.hasOwn(claimStates, state)
                ? { claim_state: state as Schema["ClaimState"] }
                : {}),
              ...(isUuid(caseId) ? { case_id: caseId } : {}),
              ...(isUuid(policyId) ? { policy_id: policyId } : {}),
            },
          }),
        ),
        allPages((cursor) => core.cases({ limit: 200, ...(cursor ? { cursor } : {}) })),
        allPages((cursor) => core.policies({ limit: 200, ...(cursor ? { cursor } : {}) })),
      ]);
      return { claims, cases, policies };
    }, [api, core, state, caseId, policyId]),
  );
  const personName = (id: string | null | undefined) =>
    people.people.find((p) => p.id === id)?.display_name ?? "가족 확인 필요";
  const caseLabel = (row: Schema["CaseListItem"]) =>
    `${row.title} · ${personName(row.patient_member_id)} · 진료 시작 ${dateLabel(row.start_on)} · ${treatments[row.treatment_state]} · ${finances[row.financial_state]}`;
  const policyLabel = (row: Schema["PolicyResponse"]) =>
    `${row.insurer} · ${row.product_name} · ${personName(row.insured_member_id)} · 계약 시작 ${dateLabel(row.contract_start ?? null)} · ${policyStatuses[row.status]}`;
  const dateError = isDateOnly(from) && isDateOnly(until) && from > until;
  const rows = (result.data?.claims ?? [])
    .filter((row) => {
      const incident = result.data?.cases.find((c) => c.id === row.case_id);
      return (
        (!isUuid(patient) || incident?.patient_member_id === patient) &&
        (receipt !== "none" || row.received_krw === "0") &&
        (receipt !== "received" || BigInt(row.received_krw) > 0n) &&
        (!isDateOnly(from) || (!!row.submitted_on && row.submitted_on >= from)) &&
        (!isDateOnly(until) || (!!row.submitted_on && row.submitted_on <= until))
      );
    })
    .sort((a, b) => {
      if (order === "priority") {
        const priority =
          Number(b.claim_state === "documents_required") -
          Number(a.claim_state === "documents_required");
        if (priority) return priority;
      }
      if (!a.submitted_on !== !b.submitted_on) return a.submitted_on ? -1 : 1;
      const date = (a.submitted_on ?? "").localeCompare(b.submitted_on ?? "");
      return (order === "newest" ? -date : date) || a.id.localeCompare(b.id);
    });
  const ready =
    !!result.data && !result.loading && !result.error && !people.loading && !people.error;
  return (
    <>
      <div className="form-actions">
        <Link className="button-link" to="/insurance/claims/new">
          청구 추가
        </Link>
        <Link to="/insurance/cases">사건별 진료·비용</Link>
        <Link to="/insurance/payouts">수령 원본 목록</Link>
      </div>
      <FilterPanel
        title="청구 찾기"
        activeCount={
          [
            state,
            caseId,
            policyId,
            patient,
            receipt,
            from,
            until,
            order !== "priority" ? order : "",
          ].filter(Boolean).length
        }
      >
        <div className="form-grid">
          <label>
            청구 상태 필터
            <select value={state} onChange={(e) => filter("state", e.target.value)}>
              <option value="">모든 상태</option>
              {Object.entries(claimStates).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="form-field">
            <SearchableSelect
              label="청구 사건 필터"
              value={caseId}
              onChange={(value) => filter("case", value)}
              placeholder="모든 사건"
              options={(result.data?.cases ?? []).map((row) => ({
                value: row.id,
                label: caseLabel(row),
              }))}
            />
          </div>
          <div className="form-field">
            <SearchableSelect
              label="청구 계약 필터"
              value={policyId}
              onChange={(value) => filter("policy", value)}
              placeholder="모든 계약"
              options={(result.data?.policies ?? []).map((row) => ({
                value: row.id,
                label: policyLabel(row),
              }))}
            />
          </div>
          <label>
            청구 환자 필터
            <select value={patient} onChange={(e) => filter("patient", e.target.value)}>
              <option value="">모든 가족</option>
              {people.people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                  {p.active ? "" : " · 보관됨"}
                </option>
              ))}
            </select>
          </label>
          <label>
            실제 수령 여부
            <select value={receipt} onChange={(e) => filter("receipt", e.target.value)}>
              <option value="">모두</option>
              <option value="none">수령 기록 없음</option>
              <option value="received">수령 기록 있음 (반환 포함)</option>
            </select>
          </label>
          <label>
            접수 시작일
            <input type="date" value={from} onChange={(e) => filter("from", e.target.value)} />
          </label>
          <label>
            접수 종료일
            <input
              type="date"
              min={from || undefined}
              value={until}
              onChange={(e) => filter("until", e.target.value)}
            />
          </label>
          <label>
            청구 정렬
            <select value={order} onChange={(e) => filter("order", e.target.value)}>
              <option value="priority">추가 서류 우선 · 오래된 접수순</option>
              <option value="oldest">오래된 접수순</option>
              <option value="newest">최근 접수순</option>
            </select>
          </label>
        </div>
        <button type="button" onClick={reset}>
          청구 조건 초기화
        </button>
      </FilterPanel>
      <InsuranceError error={result.error ?? people.error} />
      <button
        type="button"
        disabled={result.loading || people.loading}
        onClick={() => {
          void result.reload();
          void people.reload();
        }}
      >
        청구 작업 목록 새로고침
      </button>
      {(result.loading || people.loading) && (
        <p role="status">모든 페이지의 청구와 연결 정보를 확인하고 있어요.</p>
      )}
      {dateError && <p role="alert">접수 종료일은 시작일 이후로 선택해 주세요.</p>}
      {ready && !dateError && (
        <section className="card" aria-label="청구 작업 결과">
          <h2>청구 {rows.length}건</h2>
          <p>
            청구액·결정액은 입금이 아니에요. 수령 기록이 있어도 지급 완료로 판단하지 않아요. 접수일
            미입력은 날짜 조건에서 제외해요.
          </p>
          {!rows.length && <p>조건에 맞는 청구가 없어요.</p>}
          <ul className="finance-list">
            {rows.map((row) => {
              const incident = result.data?.cases.find((c) => c.id === row.case_id);
              const policy = result.data?.policies.find((p) => p.id === row.policy_id);
              return (
                <li key={row.id}>
                  <h3>
                    <Link to={`/insurance/claims/${row.id}`}>
                      {row.claim_reference || "접수번호 미입력"} · {claimStates[row.claim_state]}
                    </Link>
                  </h3>
                  <p>
                    <Link to={`/insurance/cases/${row.case_id}`}>
                      {incident ? caseLabel(incident) : "사건 확인"}
                    </Link>
                  </p>
                  <p>
                    <Link to={`/insurance/policies/${row.policy_id}`}>
                      {policy ? policyLabel(policy) : "계약 확인"}
                    </Link>
                  </p>
                  <p>
                    실제 접수일 {dateLabel(row.submitted_on ?? null)} · 근거 {row.expense_count}개
                  </p>
                  <p>
                    청구 {formatKrw(row.requested_krw ?? null)} · 결정{" "}
                    {formatKrw(row.decided_krw ?? null)}
                  </p>
                  <p>
                    실제 수령 {formatKrw(row.received_krw)} · 반환 {formatKrw(row.returned_krw)} ·
                    순수령 {formatKrw(row.net_received_krw)}
                  </p>
                  {row.claim_state === "documents_required" && (
                    <Link to={`/insurance/claims/${row.id}#claim-documents`}>추가 서류 확인</Link>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </>
  );
}

export function ClaimWorkbench() {
  return (
    <InsurancePage
      title="보험 청구 작업 목록"
      description="추가 서류와 접수·심사 상태를 확인하고, 실제 받은 보험금을 따로 살펴봐요."
    >
      <ClaimTasks />
    </InsurancePage>
  );
}
