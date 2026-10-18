import { FilterPanel, TaskNotice, TaskPanel } from "../../shared/TaskLayout";
import { useCallback, useRef, useState } from "react";
import type { components } from "@sallimbook/api-client";
import { Link, useParams } from "react-router";
import { ApiError } from "../../platform/api";
import { MonthPicker, useMonth, formatMonth } from "../../shared/MonthContext";
import { formatKrw } from "../assets/months/model";
import { AuthenticatedFinance, CashflowError, RecordedMoneyNotice } from "../finance/FinancialFeedback";
import { useAccountChoices } from "../finance/AccountChoices";
import { dateLabel, isUuid, MemberLoadError, useHouseholdMembers } from "../finance/FinanceSupport";
import type { HouseholdMember } from "../finance/FinanceSupport";
import { usePagedList, useResource } from "../finance/queries";
import { useUrlFilters } from "../finance/useUrlFilters";
import { useIncomeApi } from "./api";
import { incomeActions, incomeKinds, manualIncome } from "./model";
import type { Income, IncomeQuery } from "./model";
import { IncomeEditor } from "./IncomeEditor";
import { IncomeCommand } from "./IncomeCommands";
export function IncomeSummaryPanel() {
  const api = useIncomeApi(); const { month } = useMonth();
  const summary = useResource(useCallback(() => api.summary(month), [api, month]));
  const members = useHouseholdMembers(); const data = summary.data;
  return <section className="card task-summary" aria-label="등록 수입 요약">
    <h2>{formatMonth(month)} 등록 수입</h2><CashflowError error={summary.error} />
    {summary.loading && <p role="status">수입 요약을 확인하고 있어요.</p>}
    {summary.error && <button type="button" onClick={() => void summary.reload()}>수입 요약 다시 확인</button>}
    {data && !summary.loading && !summary.error && <>
      <dl className="metric-strip">
        <div className="metric-primary"><dt>등록 유입 순액</dt><dd>{formatKrw(data.totals.net_inflow_krw)}</dd></div>
        <div><dt>근로·부수입 순액</dt><dd>{formatKrw(data.totals.earned_net_krw)}</dd></div>
        <div><dt>보험금 순유입</dt><dd>{formatKrw(data.totals.insurance_net_krw)}</dd></div>
      </dl>
      <details className="summary-details"><summary>수입 종류·구성원별 상세</summary>
        <dl className="metadata-grid compact-metadata">
          <div><dt>급여</dt><dd>{formatKrw(data.totals.salary_krw)}</dd></div>
          <div><dt>상여</dt><dd>{formatKrw(data.totals.bonus_krw)}</dd></div>
          <div><dt>기타 수입</dt><dd>{formatKrw(data.totals.other_income_krw)}</dd></div>
          <div><dt>수입 반환</dt><dd>{formatKrw(data.totals.income_returns_krw)}</dd></div>
          <div><dt>보험금 수령 / 반환</dt><dd>{formatKrw(data.totals.insurance_receipts_krw)} / {formatKrw(data.totals.insurance_returns_krw)}</dd></div>
        </dl>
        {data.members.length > 0 && <div className="table-scroll"><table><caption>구성원별 등록 수입</caption><thead><tr><th>구성원</th><th>근로·부수입 순액</th><th>보험금 순유입</th></tr></thead><tbody>{data.members.map((row) => <tr key={row.member_id ?? "unassigned"}><th>{row.member_id ? members.members.find((m) => m.member_id === row.member_id)?.display_name ?? "구성원 확인 필요" : "구성원 미지정"}</th><td>{formatKrw(row.totals.earned_net_krw)}</td><td>{formatKrw(row.totals.insurance_net_krw)}</td></tr>)}</tbody></table></div>}
      </details>
      <p className="muted">활성 기록 {data.totals.record_count}개 기준이에요. 아래 목록 필터와 별개인 가계 전체 요약이며, 전체 입출금이나 저축액이 아니에요.</p>
    </>}
  </section>;
}
export function IncomeRecordSummary({ row, members, accounts = [] }: { row: Income; members: HouseholdMember[]; accounts?: components["schemas"]["AccountResponse"][] }) {
  const account = accounts.find((item) => item.id === row.account_id);
  return <dl className="metadata-grid"><div><dt>금액</dt><dd>{formatKrw(row.amount_krw)} · {row.flow === "in" ? "유입" : "반환"}</dd></div><div><dt>구성원</dt><dd>{members.find((member) => member.member_id === row.member_id)?.display_name ?? "구성원 미지정"}</dd></div><div><dt>귀속월</dt><dd>{formatMonth(row.period_month)}</dd></div><div><dt>날짜 정밀도</dt><dd>{row.date_precision === "month" ? "월합계 · 실제 날짜 미지정" : `실제 날짜 ${dateLabel(row.occurred_on)}`}</dd></div><div><dt>연결 계좌</dt><dd>{row.account_id ? <Link to={`/accounts/${row.account_id}`}>{account ? `${account.asset.name} · ${account.institution_name}` : "연결 계좌 확인"}</Link> : "연결 안 함"}</dd></div><div><dt>현재 상태</dt><dd>{row.state === "active" ? "활성 기록" : "무효 기록"} · 버전 {row.version}</dd></div></dl>;
}
function IncomeList() {
  const api = useIncomeApi(); const { month } = useMonth(); const members = useHouseholdMembers(); const accounts = useAccountChoices(); const { params, filter, reset } = useUrlFilters();
  const member = isUuid(params.get("member") ?? "") ? params.get("member")! : ""; const kind = Object.hasOwn(incomeKinds, params.get("kind") ?? "") ? params.get("kind") as IncomeQuery["kind"] : undefined; const state = ["active", "void", "all"].includes(params.get("state") ?? "") ? params.get("state") as IncomeQuery["state"] : "active";
  const list = usePagedList(useCallback((cursor?: string) => api.list({ month, state, ...(member ? { member_id: member } : {}), ...(kind ? { kind } : {}), ...(cursor ? { cursor } : {}), limit: 50 }), [api, month, member, kind, state]));
  return <><MonthPicker /><div className="form-actions"><Link className="button-link" to="/income/new">수입 입력</Link><Link className="button-link secondary-button" to="/income/convert">월합계·일별 전환</Link></div><IncomeSummaryPanel /><RecordedMoneyNotice />
    <FilterPanel title="수입 기록 찾기" defaultLabel="활성 기록" activeCount={[member, kind, state !== "active" ? state : ""].filter(Boolean).length}><div className="filter-grid"><div className="form-field"><label>수입 구성원 필터<select value={member} onChange={(event) => filter("member", event.target.value)}><option value="">전체 구성원</option>{members.members.map((m) => <option key={m.member_id} value={m.member_id}>{m.display_name}</option>)}</select></label></div><div className="form-field"><label>수입 종류 필터<select value={kind ?? ""} onChange={(event) => filter("kind", event.target.value)}><option value="">모든 수입·반환</option>{Object.entries(incomeKinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div><div className="form-field"><label>수입 상태 필터<select value={state} onChange={(event) => filter("state", event.target.value)}><option value="active">활성 기록</option><option value="void">무효 기록</option><option value="all">모든 기록</option></select></label></div></div><div className="form-actions"><button onClick={() => void list.reload()} disabled={list.loading}>수입 목록 다시 확인</button><button className="secondary-button" onClick={reset}>수입 필터 초기화</button></div></FilterPanel><MemberLoadError error={members.error} retry={members.retry} />
    <CashflowError error={list.error} />{list.error && <button type="button" onClick={() => void list.reload()}>수입 다시 확인</button>}{list.loading && <p className="loading-state" role="status">수입 기록을 불러오고 있어요.</p>}{!list.loading && !list.error && list.items.length === 0 && <p>조건에 맞는 수입 기록이 없어요.</p>}
    <ul className="finance-list task-records">{list.items.map((row) => <li className="card" key={row.id}>
      <div className="item-heading"><h2><Link to={`/income/${row.id}`}>{incomeKinds[row.kind as keyof typeof incomeKinds]} · {formatKrw(row.amount_krw)}</Link></h2>{row.state === "void" && <span className="status-chip">무효 기록</span>}</div>
      <p className="record-subline">{members.members.find((member) => member.member_id === row.member_id)?.display_name ?? "구성원 미지정"} · {row.date_precision === "month" ? `${formatMonth(row.period_month)} 월합계` : dateLabel(row.occurred_on)}</p>
      <details className="record-details"><summary>날짜·계좌·기록 상세</summary><IncomeRecordSummary row={row} members={members.members} accounts={accounts.data ?? []} /></details>
      {row.kind.startsWith("insurance") && <p className="muted">보험 영역에서 기록된 유입·반환이에요. 수입으로 다시 등록하지 않아요.</p>}
    </li>)}</ul>{list.cursor && <button onClick={() => void list.more()} disabled={list.loading}>수입 더 보기</button>}
  </>;
}
const historyKey = (row: Income) => `${row.id}:${row.version}`;
function IncomeHistory({ id }: { id: string }) {
  const api = useIncomeApi(); const history = usePagedList(useCallback((cursor?: number) => api.history(id, cursor), [api, id]), historyKey);
  return <section className="card"><h2>수입 변경 이력</h2><CashflowError error={history.error} />{history.error && <button onClick={() => void history.reload()}>수입 이력 다시 확인</button>}<ol className="month-history">{history.items.map((row) => <li key={historyKey(row)}><h3>버전 {row.version} · {incomeActions[row.action]}</h3><p>{formatKrw(row.amount_krw)} · {row.period_month} · {row.date_precision === "month" ? "월합계" : dateLabel(row.occurred_on)}</p>{row.reason && <p>사유: {row.reason}</p>}<p>{new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(row.updated_at))} · 서울</p></li>)}</ol>{history.cursor !== null && <button disabled={history.loading} onClick={() => void history.more()}>수입 이력 더 보기</button>}</section>;
}
function IncomeDetail({ id, edit }: { id: string; edit: boolean }) {
  const api = useIncomeApi(); const resource = useResource(useCallback(() => isUuid(id) ? api.get(id) : Promise.reject(new ApiError(404, "NOT_FOUND")), [api, id])); const members = useHouseholdMembers(); const accounts = useAccountChoices(); const [action, setAction] = useState<"return" | "void" | "">("");
  const actionTrigger = useRef<HTMLButtonElement>(null);
  const row = resource.data; const [commandBusy, setCommandBusy] = useState(false); const [notice, setNotice] = useState("");
  return <><CashflowError error={resource.error} /><TaskNotice message={notice} />{resource.error && <button onClick={() => void resource.reload()}>현재 수입 다시 확인</button>}{resource.loading && <p className="loading-state" role="status">현재 수입 기록을 불러오고 있어요.</p>}{row && !resource.error && !resource.loading && <>
    <section className="card"><h2>{incomeKinds[row.kind as keyof typeof incomeKinds]}</h2><IncomeRecordSummary row={row} members={members.members} accounts={accounts.data ?? []} />{row.note && <p>메모: {row.note}</p>}{row.reason && <p>변경 사유: {row.reason}</p>}{row.reverses_id && <Link to={`/income/${row.reverses_id}`}>반환 원본 수입 확인</Link>}<RecordedMoneyNotice />
      {row.kind.startsWith("insurance") && <p>보험 영역의 실제 수령·반환 기록을 그대로 보여줘요. <Link to="/insurance/cases">보험 사건에서 관리</Link></p>}
      {!edit && <div className="form-actions">{row.editable && (action ? <button type="button" disabled>수입 정정</button> : <Link className="button-link" to={`/income/${id}/edit`}>수입 정정</Link>)}{row.state === "active" && manualIncome(row) && <button disabled={Boolean(action)} onClick={(event) => { actionTrigger.current = event.currentTarget; setNotice(""); setAction("return"); }}>수입 반환 기록</button>}{row.voidable && <button className="secondary-button" disabled={Boolean(action)} onClick={(event) => { actionTrigger.current = event.currentTarget; setNotice(""); setAction("void"); }}>무효 처리 검토</button>}</div>}
      {row.state === "active" && manualIncome(row) && !row.editable && <p>연결된 반환 등 현재 상태로 정정·무효가 제한돼요. 반환 내역을 먼저 확인해 주세요.</p>}
    </section>{edit ? row.editable ? <IncomeEditor initial={row} /> : <p>현재 기록은 정정할 수 없어요. <Link to={`/income/${id}`}>현재 상세로 돌아가기</Link></p> : action ? <TaskPanel key={`${id}:${action}`} label="수입 반환·무효 입력"><IncomeCommand initial={row} action={action} onBusyChange={setCommandBusy} onSaved={() => { setCommandBusy(false); setAction(""); setNotice("수입 기록의 무효 처리를 저장했어요."); void resource.reload(); }} /><div className="form-actions"><button className="secondary-button" disabled={commandBusy} onClick={() => { const target = actionTrigger.current; setAction(""); requestAnimationFrame(() => { if (target?.isConnected) target.focus(); }); }}>작업 닫기</button></div></TaskPanel> : null}
    <IncomeHistory key={`${id}:${row.version}`} id={id} />
  </>}</>;
}
export function IncomeListPage() { return <AuthenticatedFinance title="월간 수입" description="등록한 수입과 반환, 보험금 유입을 나누어 확인해요."><IncomeList /></AuthenticatedFinance>; }
export function IncomeNewPage() { return <AuthenticatedFinance title="수입 입력" description="월합계 또는 실제 입금일로 직접 기록해요."><IncomeEditor /></AuthenticatedFinance>; }
export function IncomeDetailPage({ edit = false }: { edit?: boolean }) { const { id = "" } = useParams(); return <AuthenticatedFinance title={edit ? "수입 정정" : "수입 상세"} description="현재 기록과 변경 사유를 함께 확인해요."><IncomeDetail key={`${id}:${edit}`} id={id} edit={edit} /></AuthenticatedFinance>; }
