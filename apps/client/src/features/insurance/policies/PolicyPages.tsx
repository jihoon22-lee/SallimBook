import { FilterPanel } from "../../../shared/TaskLayout";
import { DocumentPanel } from "../../documents/DocumentPanel";
import { useCallback } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../../../platform/api";
import { isUuid } from "../../finance/dates";
import { usePagedList, useResource } from "../../finance/queries";
import { useUrlFilters } from "../../finance/useUrlFilters";
import { PersonSelect } from "../../household/people";
import { useInsuranceApi } from "../api";
import { policyStatuses } from "../model";
import type { PolicyQuery } from "../model";
import { InsuranceError, InsurancePage, MemberSelect } from "../InsuranceSupport";
import { PolicyEditor, PolicySummary } from "./PolicyEditor";
import { PolicyNumber } from "./PolicyNumber";
import { Coverages } from "./Coverages";
import { ClaimsList } from "../claims/ClaimPages";
import { PremiumLinks } from "./PremiumLinks";
function PolicyList() {
  const api = useInsuranceApi();
  const { params, filter, reset } = useUrlFilters();
  const status = params.get("status") ?? "";
  const insured = params.get("insured") ?? "";
  const holder = params.get("holder") ?? "";
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.policies({
          ...(Object.hasOwn(policyStatuses, status)
            ? { status: status as PolicyQuery["status"] }
            : {}),
          ...(isUuid(insured) ? { insured_member_id: insured } : {}),
          ...(isUuid(holder) ? { policyholder_member_id: holder } : {}),
          limit: 50,
          ...(cursor ? { cursor } : {}),
        }),
      [api, status, insured, holder],
    ),
    undefined,
    "insurance-policies",
  );
  return (
    <>
      <Link className="button-link" to="/insurance/policies/new">
        보험 계약 등록
      </Link>
      <FilterPanel
        title="계약 찾기"
        activeCount={
          [
            Object.hasOwn(policyStatuses, status) ? status : "",
            isUuid(insured) ? insured : "",
            isUuid(holder) ? holder : "",
          ].filter(Boolean).length
        }
      >
        <div className="form-grid">
          <div className="form-field">
            <label>
              보험 상태 필터
              <select value={status} onChange={(e) => filter("status", e.target.value)}>
                <option value="">모든 상태</option>
                {Object.entries(policyStatuses).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <PersonSelect
            includeArchived
            label="피보험자 필터"
            value={insured}
            onChange={(v) => filter("insured", v)}
          />
          <MemberSelect label="계약자 필터" value={holder} onChange={(v) => filter("holder", v)} />
        </div>
        <button onClick={reset}>보험 계약 필터 초기화</button>
      </FilterPanel>
      <InsuranceError error={list.error} />
      {list.error && <button onClick={() => void list.reload()}>보험 계약 다시 확인</button>}
      {list.loading && (
        <p className="loading-state" role="status">
          보험 계약을 불러오고 있어요.
        </p>
      )}
      {!list.loading && !list.error && !list.items.length && <p>조건에 맞는 보험 계약이 없어요.</p>}
      <ul className="finance-list">
        {list.items.map((row) => (
          <li key={row.id} className="card">
            <h2>
              <Link to={`/insurance/policies/${row.id}`}>{row.product_name}</Link>
            </h2>
            <p>
              {row.insurer} · {policyStatuses[row.status]} ·{" "}
              {row.masked_number ?? "증권번호 미등록"}
            </p>
          </li>
        ))}
      </ul>
      {list.cursor && (
        <button disabled={list.loading} onClick={() => void list.more()}>
          보험 계약 더 보기
        </button>
      )}
    </>
  );
}
function PolicyDetail({ id, edit }: { id: string; edit: boolean }) {
  const api = useInsuranceApi();
  const resource = useResource(
    useCallback(
      () => (isUuid(id) ? api.policy(id) : Promise.reject(new ApiError(404, "NOT_FOUND"))),
      [api, id],
    ),
  );
  const row = resource.data;
  return (
    <>
      <InsuranceError error={resource.error} />
      {resource.error && (
        <button onClick={() => void resource.reload()}>보험 계약 다시 확인</button>
      )}
      {resource.loading && (
        <p className="loading-state" role="status">
          보험 계약을 확인하고 있어요.
        </p>
      )}
      {row &&
        !resource.loading &&
        !resource.error &&
        (edit ? (
          <PolicyEditor initial={row} />
        ) : (
          <>
            <section className="card">
              <h2>{row.product_name}</h2>
              <PolicySummary row={row} />
              <Link to={`/insurance/policies/${id}/edit`}>보험 계약 수정</Link>
            </section>
            <DocumentPanel kind="policy" id={id} />
            <PolicyNumber policy={row} refresh={() => void resource.reload()} />
            <Coverages policyId={id} />
            <PremiumLinks policy={row} />
            <ClaimsList policyId={id} />
          </>
        ))}
    </>
  );
}
export function PolicyListPage() {
  return (
    <InsurancePage
      title="보험 계약"
      description="계약·보장·납입 기간과 같은 보험료 규칙을 확인해요."
    >
      <PolicyList />
    </InsurancePage>
  );
}
export function PolicyNewPage() {
  return (
    <InsurancePage
      title="보험 계약 등록"
      description="수동으로 계약을 기록하고 필요한 보장을 이어서 추가해요."
    >
      <PolicyEditor />
    </InsurancePage>
  );
}
export function PolicyDetailPage({ edit = false }: { edit?: boolean }) {
  const { id = "" } = useParams();
  return (
    <InsurancePage
      title={edit ? "보험 계약 수정" : "보험 계약 상세"}
      description="계약 상태와 보장·납입 정보를 구분해 확인해요."
    >
      <PolicyDetail key={`${id}:${edit}`} id={id} edit={edit} />
    </InsurancePage>
  );
}
