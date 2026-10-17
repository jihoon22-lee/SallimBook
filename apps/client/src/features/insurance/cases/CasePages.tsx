import { useCallback } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../../../platform/api";
import { isUuid, dateLabel } from "../../finance/dates";
import { useHouseholdMembers } from "../../finance/FinanceSupport";
import { usePagedList, useResource } from "../../finance/queries";
import { useUrlFilters } from "../../finance/useUrlFilters";
import { useInsuranceApi } from "../api";
import { finances, treatments } from "../model";
import type { CaseQuery } from "../model";
import { InsuranceError, InsurancePage, MemberSelect } from "../InsuranceSupport";
import { CaseEditor, CaseSummary } from "./CaseEditor";
import { MedicalTree } from "./MedicalTree";
const historyKey = (row: { id: string; version: number }) => `${row.id}:${row.version}`;
function CaseHistory({ id }: { id: string }) {
  const api = useInsuranceApi(); const members = useHouseholdMembers(); const list = usePagedList(useCallback(async (cursor?: number) => { const response = await api.caseHistory(id, cursor); return { ...response, items: response.items.map((row) => ({ ...row, id: row.case_id })) }; }, [api, id]), historyKey);
  return <section className="card"><h2>사건 변경 이력</h2><InsuranceError error={list.error} />{list.error && <button onClick={() => void list.reload()}>사건 이력 다시 확인</button>}<ol className="month-history">{list.items.map((row) => <li key={historyKey(row)}><h3>사건 버전 {row.version}</h3><p>{new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(row.changed_at))} · {members.members.find((m) => m.member_id === row.changed_by_member_id)?.display_name ?? "가계 구성원"}</p><CaseSummary row={row} />{row.reason && <p>변경 사유: {row.reason}</p>}</li>)}</ol>{list.cursor !== null && <button disabled={list.loading} onClick={() => void list.more()}>사건 이력 더 보기</button>}</section>;
}
function CaseList() {
  const api = useInsuranceApi(); const { params, filter, reset } = useUrlFilters(); const patient = params.get("patient") ?? ""; const treatment = params.get("treatment") ?? ""; const financial = params.get("financial") ?? ""; const members = useHouseholdMembers();
  const list = usePagedList(useCallback((cursor?: string) => api.cases({ ...(isUuid(patient) ? { patient_member_id: patient } : {}), ...(Object.hasOwn(treatments, treatment) ? { treatment_state: treatment as CaseQuery["treatment_state"] } : {}), ...(Object.hasOwn(finances, financial) ? { financial_state: financial as CaseQuery["financial_state"] } : {}), limit: 50, ...(cursor ? { cursor } : {}) }), [api, patient, treatment, financial]));
  return <><Link className="button-link" to="/insurance/cases/new">보험 사건 등록</Link><section className="card"><h2>사건 찾기</h2><div className="form-grid"><MemberSelect label="사건 환자 필터" value={patient} onChange={(v) => filter("patient", v)} /><div className="form-field"><label>치료 상태 필터<select value={treatment} onChange={(e) => filter("treatment", e.target.value)}><option value="">전체 치료 상태</option>{Object.entries(treatments).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div><div className="form-field"><label>정산 상태 필터<select value={financial} onChange={(e) => filter("financial", e.target.value)}><option value="">전체 정산 상태</option>{Object.entries(finances).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div></div><button onClick={reset}>보험 사건 필터 초기화</button></section><InsuranceError error={list.error} />{list.error && <button onClick={() => void list.reload()}>보험 사건 다시 확인</button>}{list.loading && <p role="status">보험 사건을 불러오고 있어요.</p>}{!list.loading && !list.error && !list.items.length && <p>조건에 맞는 사건이 없어요. 계약을 선택하지 않고 사건부터 만들 수 있어요.</p>}<ul className="finance-list">{list.items.map((row) => <li key={row.id} className="card"><h2><Link to={`/insurance/cases/${row.id}`}>{row.title}</Link></h2><p>{members.members.find((m) => m.member_id === row.patient_member_id)?.display_name ?? "가계 구성원"} · {dateLabel(row.start_on)} ~ {dateLabel(row.end_on)}</p><p>{treatments[row.treatment_state]} · {finances[row.financial_state]}</p></li>)}</ul>{list.cursor && <button disabled={list.loading} onClick={() => void list.more()}>보험 사건 더 보기</button>}</>;
}
function CaseDetail({ id, edit, nodeId }: { id: string; edit: boolean; nodeId?: string }) {
  const api = useInsuranceApi(); const record = useResource(useCallback(() => isUuid(id) ? api.case(id) : Promise.reject(new ApiError(404, "NOT_FOUND")), [api, id])); const row = record.data;
  return <><InsuranceError error={record.error} />{record.error && <button onClick={() => void record.reload()}>보험 사건 다시 확인</button>}{record.loading && <p role="status">사건을 확인하고 있어요.</p>}{row && !record.loading && !record.error && (edit ? <CaseEditor initial={row} /> : <><section className="card"><h2>{row.title}</h2><CaseSummary row={row} /><Link to={`/insurance/cases/${id}/edit`}>사건 상태·내용 변경</Link></section><MedicalTree key={`${id}:${nodeId ?? ""}`} caseId={id} selectedId={nodeId} /><CaseHistory id={id} /></>)}</>;
}
export function CaseListPage() { return <InsurancePage title="보험 사건" description="치료와 청구 정산을 독립적으로 관리해요."><CaseList /></InsurancePage>; }
export function CaseNewPage() { return <InsurancePage title="보험 사건 등록" description="계약 선택 없이 사건과 환자부터 기록해요."><CaseEditor /></InsurancePage>; }
export function CaseDetailPage({ edit = false }: { edit?: boolean }) { const { id = "", nodeId } = useParams(); return <InsurancePage title={edit ? "보험 사건 변경" : "보험 사건 상세"} description="진료·약국과 비용·청구·실제 수령을 한 사건에서 확인해요."><CaseDetail key={`${id}:${edit}`} id={id} nodeId={nodeId} edit={edit} /></InsurancePage>; }
