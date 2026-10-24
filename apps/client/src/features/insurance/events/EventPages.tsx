import { FilterPanel } from "../../../shared/TaskLayout";
import { useUrlFilters } from "../../finance/useUrlFilters";
import { DocumentPanel } from "../../documents/DocumentPanel";
import { useCallback, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ApiError } from "../../../platform/api";
import { formatKrw } from "../../assets/months/model";
import { dateLabel, isUuid } from "../../finance/dates";
import { usePagedList, useResource } from "../../finance/queries";
import { InsuranceError, InsurancePage } from "../InsuranceSupport";
import type { Schema } from "../model";
import { AllocationHistory, AllocationLink } from "./AllocationLink";
import { CashSummary, ExpenseSummary, PolicySelect } from "./EventSupport";
import { AllocationSummary, PayoutEditor } from "./PayoutEditor";
import { ExpenseEditor } from "./ExpenseEditor";
import { ReturnEditor } from "./ReturnEditor";
import { EventCashHistory, getters, VoidEvent } from "./EventCommands";
import { claimStates, eventNames, eventPaths } from "./model";
import type { EventKind, EventRow } from "./model";
import { useInsuranceEventsApi } from "./api";
export function ExpenseList({ caseId, nodeId }: { caseId: string; nodeId?: string }) {
  const api = useInsuranceEventsApi();
  const { params, filter } = useUrlFilters();
  const policy = params.get("expense_policy") ?? "";
  const linked = params.get("expense_link") ?? "";
  const filtered = isUuid(policy) && ["yes", "no"].includes(linked);
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.listMedicalExpenses({
          query: {
            case_id: caseId,
            ...(nodeId ? { node_id: nodeId } : {}),
            ...(filtered ? { claim_policy_id: policy, claimed: linked === "yes" } : {}),
            limit: 50,
            ...(cursor ? { cursor } : {}),
          },
        }),
      [api, caseId, nodeId, filtered, policy, linked],
    ),
  );
  return (
    <section className="card" aria-label={nodeId ? "이 진료의 비용 원본" : "사건의 의료비 원본"}>
      <h2>{nodeId ? "이 진료의 비용 원본" : "사건의 의료비 원본"}</h2>
      <Link
        className="button-link secondary-button"
        to={`/insurance/expenses/new?case=${caseId}${nodeId ? `&node=${nodeId}` : ""}`}
      >
        실제 의료비 추가
      </Link>
      <FilterPanel title="비용 청구 연결 확인" activeCount={filtered ? 1 : 0}>
        <PolicySelect
          label="비용 청구 확인 계약"
          value={policy}
          onChange={(value) => filter("expense_policy", value)}
        />
        <label>
          선택 계약의 청구 연결
          <select
            value={linked}
            disabled={!isUuid(policy)}
            onChange={(e) => filter("expense_link", e.target.value)}
          >
            <option value="">모든 비용</option>
            <option value="yes">청구에 연결됨</option>
            <option value="no">청구에 연결 안 됨</option>
          </select>
        </label>
        <p>
          초안·철회를 포함해 현재 청구 근거에 연결된 비용을 확인해요. 연결 여부는 지급 완료나 다른
          계약의 청구 여부를 뜻하지 않아요.
        </p>
        <button
          onClick={() => {
            filter("expense_policy", "");
            filter("expense_link", "");
          }}
        >
          비용 청구 필터 초기화
        </button>
      </FilterPanel>
      {filtered && (
        <p role="status">
          선택 계약의 청구에 {linked === "yes" ? "연결된" : "연결되지 않은"} 비용만 표시해요.
        </p>
      )}
      <InsuranceError error={list.error} />
      {list.error && <button onClick={() => void list.reload()}>의료비 목록 다시 확인</button>}
      {!list.loading && !list.error && !list.items.length && (
        <p>
          {filtered ? "선택한 청구 연결 조건에 맞는 비용이 없어요." : "아직 실제 의료비가 없어요."}
        </p>
      )}
      <ul className="finance-list">
        {list.items.map((row) => (
          <li key={row.id}>
            <h3>
              <Link to={`/insurance/expenses/${row.id}`}>
                {row.provider_name || "의료비"} · {formatKrw(row.cash.amount_krw)}
              </Link>
            </h3>
            <p>
              {dateLabel(row.cash.occurred_on)} · {row.cash.state === "active" ? "활성" : "무효"} ·
              설명 명세 {row.line_count}개
            </p>
            {row.receipt_reference && <p>영수증 {row.receipt_reference}</p>}
          </li>
        ))}
      </ul>
      {list.cursor && (
        <button disabled={list.loading} onClick={() => void list.more()}>
          의료비 더 보기
        </button>
      )}
    </section>
  );
}
export function PayoutList({
  caseId,
  claimId,
  policyId,
}: {
  caseId?: string;
  claimId?: string;
  policyId?: string;
}) {
  const context = new URLSearchParams({
    ...(caseId ? { case: caseId } : {}),
    ...(claimId ? { claim: claimId } : {}),
    ...(policyId ? { policy: policyId } : {}),
  });
  const api = useInsuranceEventsApi();
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.listInsurancePayouts({
          query: {
            ...(caseId ? { case_id: caseId } : {}),
            ...(claimId ? { claim_id: claimId } : {}),
            limit: 50,
            ...(cursor ? { cursor } : {}),
          },
        }),
      [api, caseId, claimId],
    ),
  );
  return (
    <section className="card">
      <h2>실제 보험금 수령 원본</h2>
      <Link
        className="button-link secondary-button"
        to={`/insurance/payouts/new${context.size ? `?${context}` : ""}`}
      >
        실제 보험금 수령 추가
      </Link>
      <p>
        아래 금액은 입금 원본 총액이며 여러 사건의 배분이 포함될 수 있어요. 이 사건의 수령액은 사건
        순부담 요약에서 확인해요.
      </p>
      <InsuranceError error={list.error} />
      {list.error && <button onClick={() => void list.reload()}>수령 목록 다시 확인</button>}
      {!list.loading && !list.error && !list.items.length && (
        <p>실제 수령 기록이 없어요. 청구 상태만으로 수령액을 만들지 않아요.</p>
      )}
      <ul className="finance-list">
        {list.items.map((row) => (
          <li key={row.id}>
            <h3>
              <Link to={`/insurance/payouts/${row.id}`}>
                입금 원본 {formatKrw(row.cash.amount_krw)}
              </Link>
            </h3>
            <p>
              {dateLabel(row.cash.occurred_on)} · {row.cash.state === "active" ? "활성" : "무효"} ·
              배분 {row.allocation_count}개
            </p>
            {row.insurer_note && <p>{row.insurer_note}</p>}
          </li>
        ))}
      </ul>
      {list.cursor && (
        <button disabled={list.loading} onClick={() => void list.more()}>
          수령 원본 더 보기
        </button>
      )}
    </section>
  );
}
function ReturnedList({ kind, parentId }: { kind: "refund" | "return"; parentId: string }) {
  const api = useInsuranceEventsApi();
  const list = usePagedList<Schema["RefundResponse"] | Schema["ReturnResponse"]>(
    useCallback(
      async (cursor?: string) => {
        const options = {
          resourceId: parentId,
          query: { limit: 50, ...(cursor ? { cursor } : {}) },
        };
        return kind === "refund"
          ? api.listMedicalRefunds(options)
          : api.listInsuranceReturns(options);
      },
      [api, kind, parentId],
    ),
  );
  return (
    <section className="card">
      <h2>{eventNames[kind]} 내역</h2>
      <InsuranceError error={list.error} />
      {list.error && (
        <button onClick={() => void list.reload()}>{eventNames[kind]} 목록 다시 확인</button>
      )}
      {!list.loading && !list.error && !list.items.length && (
        <p>등록된 {eventNames[kind]} 기록이 없어요.</p>
      )}
      <ul>
        {list.items.map((row) => (
          <li key={row.id}>
            <Link to={`/insurance/${eventPaths[kind]}/${row.id}`}>
              {formatKrw(row.cash.amount_krw)} · {dateLabel(row.cash.occurred_on)} ·{" "}
              {row.cash.state === "active" ? "활성" : "무효"}
            </Link>
            <p>사유: {row.reason}</p>
          </li>
        ))}
      </ul>
      {list.cursor && (
        <button disabled={list.loading} onClick={() => void list.more()}>
          {eventNames[kind]} 더 보기
        </button>
      )}
    </section>
  );
}
function PayoutAllocations({ row, reload }: { row: Schema["PayoutResponse"]; reload: () => void }) {
  const [editing, setEditing] = useState<Schema["AllocationResponse"] | null>(null);
  return (
    <section className="card">
      <h2>같은 입금의 사건별 배분</h2>
      <ol className="month-history">
        {row.allocations.map((allocation, index) => (
          <li key={allocation.id}>
            <h3>배분 {index + 1}</h3>
            <AllocationSummary row={allocation} />
            {row.cash.state === "active" && (
              <button onClick={() => setEditing(allocation)}>
                배분 {index + 1} 청구 연결 정정
              </button>
            )}
            <AllocationHistory key={`${allocation.id}:${allocation.version}`} id={allocation.id} />
          </li>
        ))}
      </ol>
      {editing && (
        <AllocationLink
          key={`${editing.id}:${editing.version}`}
          initial={editing}
          saved={() => {
            setEditing(null);
            reload();
          }}
          cancel={() => setEditing(null)}
        />
      )}
    </section>
  );
}
function RefundCorrection({
  kind,
  row,
}: {
  kind: "refund" | "return";
  row: Schema["RefundResponse"] | Schema["ReturnResponse"];
}) {
  const api = useInsuranceEventsApi();
  const parentId = "expense_id" in row ? row.expense_id : row.payout_id;
  const parent = useResource(
    useCallback(
      async () =>
        kind === "refund"
          ? api.getMedicalExpense({ resourceId: parentId })
          : api.getInsurancePayout({ resourceId: parentId }),
      [api, kind, parentId],
    ),
  );
  return (
    <>
      <InsuranceError error={parent.error} />
      {parent.error && (
        <button onClick={() => void parent.reload()}>원래 금전 기록 다시 확인</button>
      )}
      {parent.data && !parent.loading && !parent.error && (
        <ReturnEditor kind={kind} initial={row} initialParent={parent.data} />
      )}
    </>
  );
}
function ClaimsCitingExpense({ expense }: { expense: Schema["ExpenseResponse"] }) {
  const api = useInsuranceEventsApi();
  const claims = useResource(
    useCallback(
      () =>
        api.listInsuranceClaims({
          query: { case_id: expense.case_id, expense_id: expense.id, limit: 50 },
        }),
      [api, expense.case_id, expense.id],
    ),
  );
  return (
    <section className="card" aria-label="이 비용을 인용한 청구">
      <h2>이 비용을 인용한 청구</h2>
      <InsuranceError error={claims.error} />
      {claims.error && (
        <button type="button" onClick={() => void claims.reload()}>
          인용한 청구 다시 확인
        </button>
      )}
      {claims.data &&
        (claims.data.items.length ? (
          <ul>
            {claims.data.items.map((claim) => (
              <li key={claim.id}>
                <Link to={`/insurance/claims/${claim.id}`}>
                  {claim.claim_reference || "접수번호 미입력 청구"} ·{" "}
                  {claimStates[claim.claim_state]}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p>이 비용을 근거로 인용한 청구가 없어요.</p>
        ))}
    </section>
  );
}
function EventDetail({ kind, id, edit }: { kind: EventKind; id: string; edit: boolean }) {
  const api = useInsuranceEventsApi();
  const resource = useResource(
    useCallback(async (): Promise<EventRow> => {
      if (!isUuid(id)) throw new ApiError(404, "NOT_FOUND");
      return api[getters[kind]]({ resourceId: id });
    }, [api, kind, id]),
  );
  const row = resource.data;
  const [voiding, setVoiding] = useState(false);
  return (
    <>
      <InsuranceError error={resource.error} />
      {resource.error && (
        <button onClick={() => void resource.reload()}>금전 원본 다시 확인</button>
      )}
      {resource.loading && (
        <p className="loading-state" role="status">
          현재 금전 원본을 확인하고 있어요.
        </p>
      )}
      {row &&
        !resource.loading &&
        !resource.error &&
        (edit ? (
          kind === "expense" && "lines" in row ? (
            <>
              <ExpenseEditor initial={row} />
              <ClaimsCitingExpense expense={row} />
            </>
          ) : kind === "payout" && "allocations" in row ? (
            <PayoutEditor initial={row} />
          ) : (kind === "refund" || kind === "return") && "reason" in row ? (
            <RefundCorrection kind={kind} row={row} />
          ) : null
        ) : (
          <>
            <section className="card">
              <h2>{eventNames[kind]} 원본</h2>
              {"lines" in row ? <ExpenseSummary row={row} /> : <CashSummary cash={row.cash} />}
              {"insurer_note" in row && row.insurer_note && <p>입금 출처: {row.insurer_note}</p>}
              {"expense_id" in row && (
                <Link to={`/insurance/expenses/${row.expense_id}`}>환불 원래 의료비</Link>
              )}
              {"payout_id" in row && (
                <Link to={`/insurance/payouts/${row.payout_id}`}>반환 원래 입금과 배분</Link>
              )}
              {"reason" in row && <p>사유: {row.reason}</p>}
              {row.correction_of_id && (
                <p>
                  <Link to={`/insurance/${eventPaths[kind]}/${row.correction_of_id}`}>
                    정정 전 원본 확인
                  </Link>
                </p>
              )}
              {"correction_reason" in row && row.correction_reason && (
                <p>정정 사유: {row.correction_reason}</p>
              )}
              <div className="form-actions">
                {row.cash.state === "active" && (
                  <>
                    <Link to={`/insurance/${eventPaths[kind]}/${id}/correct`}>
                      {eventNames[kind]} 원본 정정
                    </Link>
                    <button onClick={() => setVoiding(true)}>{eventNames[kind]} 무효 검토</button>
                    {kind === "expense" && (
                      <Link to={`/insurance/expenses/${id}/refunds/new`}>
                        실제 의료비 환불 기록
                      </Link>
                    )}
                    {kind === "payout" && (
                      <Link to={`/insurance/payouts/${id}/returns/new`}>실제 보험금 반환 기록</Link>
                    )}
                  </>
                )}
              </div>
            </section>
            {kind === "expense" && "lines" in row && <ClaimsCitingExpense expense={row} />}
            {voiding && (
              <VoidEvent
                key={`void:${row.version}`}
                kind={kind}
                initial={row}
                saved={() => {
                  setVoiding(false);
                  void resource.reload();
                }}
                cancel={() => setVoiding(false)}
              />
            )}
            {"allocations" in row && (
              <PayoutAllocations
                key={`allocations:${row.version}`}
                row={row}
                reload={() => void resource.reload()}
              />
            )}
            {kind === "expense" && (
              <ReturnedList key={`returns:${row.version}`} kind="refund" parentId={id} />
            )}
            {kind === "payout" && (
              <ReturnedList key={`returns:${row.version}`} kind="return" parentId={id} />
            )}
            {kind === "expense" && <DocumentPanel kind="expense" id={id} />}
            <EventCashHistory key={`history:${row.version}`} kind={kind} id={id} />
          </>
        ))}
    </>
  );
}
export function EventDetailPage({ kind, edit = false }: { kind: EventKind; edit?: boolean }) {
  const { id = "" } = useParams();
  return (
    <InsurancePage
      title={`${eventNames[kind]} ${edit ? "정정" : "상세"}`}
      description="원본과 정정·무효 이력을 보존하고 실제 돈의 흐름을 구분해요."
    >
      <EventDetail key={`${kind}:${id}:${edit}`} kind={kind} id={id} edit={edit} />
    </InsurancePage>
  );
}
export function ExpenseNewPage() {
  const [query] = useSearchParams();
  return (
    <InsurancePage
      title="의료비 기록"
      description="한 번 실제 지불한 금액을 원본 한 건으로 기록해요."
    >
      <ExpenseEditor caseId={query.get("case") ?? ""} nodeId={query.get("node") ?? ""} />
    </InsurancePage>
  );
}
export function PayoutNewPage() {
  const [query] = useSearchParams();
  return (
    <InsurancePage
      title="보험금 수령 입력"
      description="실제 입금 총액과 같은 합계로 사건별 배분을 기록해요."
    >
      <PayoutEditor
        caseId={query.get("case") ?? ""}
        policyId={query.get("policy") ?? ""}
        claimId={query.get("claim") ?? ""}
      />
    </InsurancePage>
  );
}
export function PayoutListPage() {
  return (
    <InsurancePage title="보험금 수령 원본" description="입금 한 번을 원본 한 건으로 확인해요.">
      <PayoutList />
    </InsurancePage>
  );
}
function ReturnNew({ kind, id }: { kind: "refund" | "return"; id: string }) {
  const api = useInsuranceEventsApi();
  const parent = useResource(
    useCallback(async () => {
      if (!isUuid(id)) throw new ApiError(404, "NOT_FOUND");
      return kind === "refund"
        ? api.getMedicalExpense({ resourceId: id })
        : api.getInsurancePayout({ resourceId: id });
    }, [api, kind, id]),
  );
  return (
    <>
      <InsuranceError error={parent.error} />
      {parent.error && (
        <button onClick={() => void parent.reload()}>원래 금전 기록 다시 확인</button>
      )}
      {parent.loading && <p role="status">원래 금전 기록을 확인하고 있어요.</p>}
      {parent.data && !parent.error && !parent.loading && (
        <ReturnEditor kind={kind} initialParent={parent.data} />
      )}
    </>
  );
}
export function ReturnNewPage({ kind }: { kind: "refund" | "return" }) {
  const { id = "" } = useParams();
  return (
    <InsurancePage
      title={`${eventNames[kind]} 기록`}
      description="실제 되돌려받거나 반환한 돈을 원래 기록과 연결해요."
    >
      <ReturnNew key={`${kind}:${id}`} kind={kind} id={id} />
    </InsurancePage>
  );
}
