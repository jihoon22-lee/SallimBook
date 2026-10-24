import { useCallback, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { SessionStatus } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import { FinanceError, MemberLoadError, useHouseholdMembers } from "../finance/FinanceSupport";
import { usePagedList } from "../finance/queries";
import { RecordActor } from "../../shared/RecordActor";
import { DateInput } from "../../shared/DateInput";
import { useAuditApi } from "./api";
import {
  actionLabels,
  entityLabels,
  emptyFilters,
  queryFromFilters,
  type AuditQuery,
} from "./model";

function ActivityResults({ query }: { query: AuditQuery }) {
  const api = useAuditApi();
  const list = usePagedList(
    useCallback(
      (cursor?: string) => api.activity({ ...query, ...(cursor ? { cursor } : {}) }),
      [api, query],
    ),
    undefined,
    "activity",
  );
  return (
    <section className="card" aria-label="최근 작업 목록">
      <h2>최근 작업</h2>
      <p className="muted">최신 작업부터 표시해요. 이름은 현재 이름이며, 시각은 서울 기준이에요.</p>
      <FinanceError error={list.error} />
      {list.loading && <p role="status">작업 내역을 불러오고 있어요.</p>}
      {!list.error && !list.loading && !list.items.length && <p>이 조건에 맞는 작업이 없어요.</p>}
      {!list.error && (
        <ol className="record-list">
          {list.items.map((row) => (
            <li key={row.id}>
              <h3>
                {entityLabels[row.entity_type] ?? "가계 기록"} ·{" "}
                {actionLabels[row.action] ?? "변경"}
              </h3>
              <p>
                {row.target_path && row.target_name ? (
                  <Link to={row.target_path}>{row.target_name}</Link>
                ) : (
                  (row.target_name ?? "원본을 확인할 수 없는 기록")
                )}
              </p>
              {!row.target_path && (
                <p className="muted">원본이 삭제되었거나 연결 화면을 확인할 수 없어요.</p>
              )}
              <RecordActor memberId={row.actor_member_id} at={row.occurred_at} label="작업자" />
            </li>
          ))}
        </ol>
      )}
      <div className="form-actions">
        <button type="button" disabled={list.loading} onClick={list.reload}>
          처음부터 다시 불러오기
        </button>
        {!list.error && list.cursor && (
          <button type="button" disabled={list.loading} onClick={list.more}>
            이전 작업 더 보기
          </button>
        )}
      </div>
    </section>
  );
}
function ActivityContent() {
  const members = useHouseholdMembers();
  const [actor, setActor] = useState("");
  const [since, setSince] = useState("");
  const [through, setThrough] = useState("");
  const [query, setQuery] = useState<AuditQuery>({ limit: 50 });
  const [error, setError] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    const result = queryFromFilters({ ...emptyFilters, actor, since, through });
    if (result.error) {
      setError(result.error);
      return;
    }
    setError("");
    setQuery(result.query!);
  }
  return (
    <>
      <section className="card">
        <h1>함께한 최근 작업</h1>
        <p>누가 어떤 기록을 바꿨는지 확인하고 해당 기록으로 이동해요.</p>
        <form className="finance-form" onSubmit={submit}>
          <div className="form-field">
            <label htmlFor="activity-actor">작업한 구성원</label>
            <select
              id="activity-actor"
              value={actor}
              onChange={(event) => setActor(event.target.value)}
              disabled={members.loading || !!members.error}
            >
              <option value="">모든 구성원</option>
              {members.members.map((member) => (
                <option key={member.member_id} value={member.member_id}>
                  {member.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="activity-since">시작 날짜</label>
            <DateInput
              id="activity-since"
              value={since}
              onChange={(event) => setSince(event.target.value)}
            />
          </div>
          <div className="form-field">
            <label htmlFor="activity-through">마지막 날짜</label>
            <DateInput
              id="activity-through"
              value={through}
              onChange={(event) => setThrough(event.target.value)}
            />
          </div>
          {error && <p role="alert">{error}</p>}
          <MemberLoadError error={members.error} retry={members.retry} />
          <button type="submit">작업 내역 조회</button>
        </form>
      </section>
      <ActivityResults query={query} />
      <Link to="/settings/audit">상세 감사 기록 보기</Link>
    </>
  );
}
export function ActivityPage() {
  const { state } = useAuth();
  return state.status === "authenticated" ? <ActivityContent /> : <SessionStatus />;
}
