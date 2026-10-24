import { useCallback, type ReactNode } from "react";
import { Link } from "react-router";
import type { components } from "@sallimbook/api-client";
import { ApiError } from "../../platform/api";
import { formatMonth, useMonth } from "../../shared/MonthContext";
import { useAuth } from "../auth/AuthProvider";
import { useAssetComparisonApi } from "../assets/comparison/api";
import { monthsBefore } from "../assets/comparison/model";
import { formatKrw } from "../assets/months/model";
import { dateLabel, FinanceError } from "../finance/FinanceSupport";
import { allPages, useResource } from "../finance/queries";
import { useFixedApi } from "../fixed/api";
import { useSeoulDayRefresh } from "../homecare/HomecareSupport";
import { useInsuranceEventsApi } from "../insurance/events/api";

type OverduePage = components["schemas"]["OverdueObligationListResponse"];
export async function completeOverdue(read: (cursor?: string) => Promise<OverduePage>) {
  let asOf: string | null = null;
  const items = await allPages(async (cursor) => {
    const page = await read(cursor);
    if (asOf !== null && asOf !== page.as_of) throw new ApiError(409, "VERSION_CONFLICT");
    asOf = page.as_of;
    return page;
  });
  return { as_of: asOf!, items };
}
function TaskSection<T>({
  title,
  result,
  count,
  empty,
  children,
}: {
  title: string;
  result: ReturnType<typeof useResource<T>>;
  count: (value: T) => number;
  empty: string;
  children: (value: T) => ReactNode;
}) {
  const ready = result.data !== null && !result.loading && !result.error;
  return (
    <section className="home-task" aria-label={title} aria-busy={result.loading}>
      <div className="item-heading">
        <h3>{title}</h3>
        {ready && <span className="status-chip">{count(result.data!)}건</span>}
      </div>
      <FinanceError error={result.error} />
      {result.loading && <p role="status">확인 중이에요.</p>}
      {ready && (count(result.data!) ? children(result.data!) : <p className="muted">{empty}</p>)}
      <button
        type="button"
        className="text-button"
        disabled={result.loading}
        onClick={() => void result.reload()}
      >
        {title} 새로고침
      </button>
    </section>
  );
}
function TaskLinks({ rows }: { rows: { id: string; to: string; name: string; detail: string }[] }) {
  const list = (items: typeof rows) => (
    <ul className="home-task-links">
      {items.map((row) => (
        <li key={row.id}>
          <Link to={row.to}>{row.name}</Link>
          <span className="muted">{row.detail}</span>
        </li>
      ))}
    </ul>
  );
  return (
    <>
      {list(rows.slice(0, 3))}
      {rows.length > 3 && (
        <details>
          <summary>나머지 {rows.length - 3}건 보기</summary>
          {list(rows.slice(3))}
        </details>
      )}
    </>
  );
}
function OverdueTasks() {
  const api = useFixedApi();
  const result = useResource(
    useCallback(
      () => completeOverdue((cursor) => api.overdue({ limit: 200, ...(cursor ? { cursor } : {}) })),
      [api],
    ),
  );
  useSeoulDayRefresh(result.reload);
  return (
    <TaskSection
      title="지난 예정일 납부 확인"
      result={result}
      count={(data) => data.items.length}
      empty="지난 예정일의 미납·부분 납부가 없어요."
    >
      {(data) => (
        <>
          <p className="muted">{dateLabel(data.as_of)} 전 예정일 · 이전 달 포함</p>
          <TaskLinks
            rows={data.items.map((row) => ({
              id: row.id,
              to: `/fixed-payments/${row.id}`,
              name: row.title,
              detail: `${dateLabel(row.scheduled_date)} 예정 · ${row.status === "partial" ? "부분 납부" : "미납"}`,
            }))}
          />
        </>
      )}
    </TaskSection>
  );
}
function PreviousMonthTask() {
  const { currentMonth } = useMonth();
  const previous = monthsBefore(currentMonth, 1);
  const api = useAssetComparisonApi();
  const result = useResource(
    useCallback(async () => {
      const data = await api.trend({ from: previous, to: previous });
      const point = data.points.find((row) => row.month === previous);
      if (!point) throw new ApiError(0, "REQUEST_FAILED");
      return point;
    }, [api, previous]),
  );
  useSeoulDayRefresh(result.reload);
  return (
    <TaskSection
      title="지난달 월 기록"
      result={result}
      count={(point) => (point.state === "confirmed" ? 0 : 1)}
      empty={`${formatMonth(previous)} 기록을 확정했어요.`}
    >
      {(point) => (
        <p>
          <Link to={`/assets/months/${previous}`}>{formatMonth(previous)} 기록 확인</Link>
          <span className="muted">
            {" "}
            ·{" "}
            {point.state === "missing"
              ? "아직 작성하지 않았어요"
              : point.state === "reopened"
                ? "정정본 확인이 필요해요"
                : "아직 확정하지 않았어요"}
          </span>
        </p>
      )}
    </TaskSection>
  );
}
function DocumentTasks() {
  const api = useInsuranceEventsApi();
  const result = useResource(
    useCallback(
      () =>
        allPages((cursor) =>
          api.listInsuranceClaims({
            query: { claim_state: "documents_required", limit: 200, ...(cursor ? { cursor } : {}) },
          }),
        ),
      [api],
    ),
  );
  return (
    <TaskSection
      title="추가 서류 필요 청구"
      result={result}
      count={(rows) => rows.length}
      empty="추가 서류가 필요한 청구가 없어요."
    >
      {(rows) => (
        <TaskLinks
          rows={rows.map((row) => ({
            id: row.id,
            to: `/insurance/claims/${row.id}`,
            name: row.claim_reference || "접수번호 미입력 청구",
            detail: `제출일 ${dateLabel(row.submitted_on ?? null)} · 추가 서류 필요`,
          }))}
        />
      )}
    </TaskSection>
  );
}
function ExpenseTasks() {
  const api = useInsuranceEventsApi();
  const result = useResource(
    useCallback(
      () =>
        allPages((cursor) =>
          api.listMedicalExpenses({
            query: {
              state: "active",
              unclaimed_any_policy: true,
              limit: 200,
              ...(cursor ? { cursor } : {}),
            },
          }),
        ),
      [api],
    ),
  );
  return (
    <TaskSection
      title="청구 연결 검토 비용"
      result={result}
      count={(rows) => rows.length}
      empty="청구에 연결하지 않은 활성 의료비가 없어요."
    >
      {(rows) => (
        <>
          <p className="muted">
            청구 연결이 없는 비용이에요. 보장 대상인지 원본과 계약을 확인해 주세요.
          </p>
          <TaskLinks
            rows={rows.map((row) => ({
              id: row.id,
              to: `/insurance/expenses/${row.id}`,
              name: row.provider_name || "의료기관 미입력 비용",
              detail: `${dateLabel(row.cash.occurred_on)} · ${formatKrw(row.cash.amount_krw)}`,
            }))}
          />
        </>
      )}
    </TaskSection>
  );
}
export function HomeAttention() {
  const { state } = useAuth();
  if (state.status !== "authenticated") return null;
  return (
    <section className="card home-attention" aria-label="확인할 일">
      <h2>확인할 일</h2>
      <p className="muted">
        현재 등록 상태예요. 자산에서 선택한 월과 별도로, 원본을 처리한 뒤 다시 확인해요.
      </p>
      <div className="home-attention-grid">
        <OverdueTasks />
        <PreviousMonthTask />
        <DocumentTasks />
        <ExpenseTasks />
      </div>
    </section>
  );
}
