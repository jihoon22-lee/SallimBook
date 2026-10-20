import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import type { ApiError } from "../../platform/api";
import { authErrorMessage, SessionStatus } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import { MemberLoadError, useHouseholdMembers } from "../finance/FinanceSupport";
import type { HouseholdMember } from "../finance/FinanceSupport";
import { usePagedList } from "../finance/queries";
import { useAuditApi } from "./api";
import { actionLabels, auditDate, emptyFilters, entityLabels, queryFromFilters } from "./model";
import type { AuditFilterDraft, AuditQuery } from "./model";
import "./audit.css";

function AuditError({ error }: { error: ApiError | null }) {
  if (!error) return null;
  const messages: Partial<Record<ApiError["code"], string>> = {
    INVALID_CURSOR: "페이지 기준이 현재 조건과 맞지 않아요. 처음부터 다시 불러와 주세요.",
    INVALID_AUDIT_FILTER:
      "조회 조건을 확인해 주세요. 날짜 범위와 대상·작업 종류를 다시 선택해 주세요.",
    AUDIT_METADATA_INVALID:
      "감사 기록의 형식을 확인하지 못했어요. 기록 내용은 표시하지 않았어요. 잠시 후 다시 시도해 주세요.",
    NATIVE_AUTH_UNAVAILABLE:
      "이 앱에서는 감사 이력 보호 연결을 열 수 없어요. 지원되는 앱 버전을 확인해 주세요.",
    FORBIDDEN: "현재 계정으로 이 감사 이력을 볼 수 없어요.",
    NOT_FOUND:
      "선택한 구성원이나 대상에 접근할 수 없어요. 현재 가계의 조회 조건을 다시 확인해 주세요.",
  };
  return (
    <p className="auth-message" role="alert">
      {messages[error.code] ?? authErrorMessage(error)}
    </p>
  );
}

function AuditResults({ query, members }: { query: AuditQuery; members: HouseholdMember[] }) {
  const api = useAuditApi();
  const list = usePagedList(
    useCallback(
      (cursor?: string) => api.list({ ...query, ...(cursor ? { cursor } : {}) }),
      [api, query],
    ),
    undefined,
    "audit",
  );
  return (
    <section className="card audit-results" aria-label="감사 기록 목록">
      <h2>감사 기록</h2>
      <p>
        최신 기록부터 보여요. 추가 페이지를 읽는 동안 새 기록이 생길 수 있으므로 최신 상태는
        처음부터 다시 확인해 주세요.
      </p>
      <AuditError error={list.error} />
      {list.loading && (
        <p className="loading-state" role="status">
          감사 기록을 불러오고 있어요.
        </p>
      )}
      {!list.loading && !list.error && !list.items.length && (
        <p>이 조건에 맞는 감사 기록이 없어요.</p>
      )}
      {!list.error && (
        <ol className="record-list">
          {list.items.map((row) => (
            <li key={row.id}>
              <h3>
                {entityLabels[row.entity_type] ?? row.entity_type} ·{" "}
                {actionLabels[row.action] ?? row.action}
              </h3>
              <p>
                <time dateTime={row.occurred_at}>{auditDate(row.occurred_at)}</time> (서울 기준)
              </p>
              <p>
                작업 구성원:{" "}
                {members.find((member) => member.member_id === row.actor_member_id)?.display_name ??
                  "이름을 확인할 수 없는 구성원"}
              </p>
              <p>
                버전: {row.before_version ?? "이전 버전 없음"} →{" "}
                {row.after_version ?? "이후 버전 없음"}
              </p>
              <p>
                변경 필드:{" "}
                {row.changed_fields.length ? row.changed_fields.join(", ") : "변경 필드 없음"}
              </p>
              {row.entity_type === "user_export" && row.action === "export" && (
                <p>
                  서버의 파일 발급 기록이에요. 기기에 실제로 저장됐는지는 이 기록으로 확인할 수
                  없어요.
                </p>
              )}
              <details>
                <summary>기록 식별정보</summary>
                <dl className="audit-metadata">
                  <dt>감사 기록 ID</dt>
                  <dd>{row.id}</dd>
                  <dt>대상 ID</dt>
                  <dd>{row.entity_id}</dd>
                  <dt>구성원 ID</dt>
                  <dd>{row.actor_member_id}</dd>
                  <dt>요청 ID</dt>
                  <dd>{row.request_id ?? "기록 없음"}</dd>
                  <dt>대상 종류</dt>
                  <dd>{row.entity_type}</dd>
                  <dt>작업 종류</dt>
                  <dd>{row.action}</dd>
                </dl>
              </details>
            </li>
          ))}
        </ol>
      )}
      <div className="form-actions">
        <button type="button" disabled={list.loading} onClick={() => void list.reload()}>
          처음부터 다시 불러오기
        </button>
        {!list.error && list.cursor && (
          <button type="button" disabled={list.loading} onClick={() => void list.more()}>
            감사 기록 더 보기
          </button>
        )}
      </div>
    </section>
  );
}

function AuditForm() {
  const household = useHouseholdMembers();
  const [draft, setDraft] = useState<AuditFilterDraft>({ ...emptyFilters });
  const [query, setQuery] = useState<AuditQuery>({ limit: 50 });
  const [error, setError] = useState("");
  function change(name: keyof AuditFilterDraft, value: string) {
    setDraft((old) => ({ ...old, [name]: value }));
    setError("");
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    const result = queryFromFilters(draft);
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
        <h2>조회 조건</h2>
        <p>
          날짜는 서울 기준이며 마지막 날짜까지 포함해요. 조건은 이 화면에만 두고 주소나 브라우저
          저장소에 보관하지 않아요.
        </p>
        <MemberLoadError error={household.error} retry={household.retry} />
        <form className="finance-form" onSubmit={submit}>
          <div className="form-grid">
            <div className="form-field">
              <label htmlFor="audit-entity-type">대상 종류</label>
              <select
                id="audit-entity-type"
                value={draft.entityType}
                onChange={(event) => change("entityType", event.target.value)}
              >
                <option value="">모든 대상</option>
                {Object.entries(entityLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="audit-action">작업 종류</label>
              <select
                id="audit-action"
                value={draft.action}
                onChange={(event) => change("action", event.target.value)}
              >
                <option value="">모든 작업</option>
                {Object.entries(actionLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="audit-actor">작업 구성원</label>
              <select
                id="audit-actor"
                value={draft.actor}
                disabled={household.loading || !!household.error}
                onChange={(event) => change("actor", event.target.value)}
              >
                <option value="">모든 구성원</option>
                {household.members.map((member) => (
                  <option key={member.member_id} value={member.member_id}>
                    {member.display_name}
                  </option>
                ))}
              </select>
            </div>
            <label className="form-field">
              대상 ID (선택)
              <input
                value={draft.entityId}
                maxLength={36}
                spellCheck={false}
                autoComplete="off"
                onChange={(event) => change("entityId", event.target.value)}
                placeholder="UUID"
              />
            </label>
            <label className="form-field">
              시작 날짜
              <input
                type="date"
                value={draft.since}
                onChange={(event) => change("since", event.target.value)}
              />
            </label>
            <label className="form-field">
              마지막 날짜 (포함)
              <input
                type="date"
                value={draft.through}
                onChange={(event) => change("through", event.target.value)}
              />
            </label>
          </div>
          {error && <p role="alert">{error}</p>}
          <div className="form-actions">
            <button type="submit">조건 적용</button>
            <button
              type="button"
              onClick={() => {
                setDraft({ ...emptyFilters });
                setQuery({ limit: 50 });
                setError("");
              }}
            >
              조건 초기화
            </button>
          </div>
        </form>
      </section>
      <AuditResults key={JSON.stringify(query)} query={query} members={household.members} />
    </>
  );
}

export function AuditPage() {
  const { state } = useAuth();
  return (
    <div className="audit-page">
      <div className="intro">
        <p className="eyebrow">공동 가계의 변경 기록</p>
        <h1>감사 이력</h1>
        <p>
          누가 언제 어떤 대상에 작업했는지 확인해요. 변경된 필드 이름과 버전만 보여 주며, 변경 전후
          값이나 보관함 비밀은 표시하지 않아요.
        </p>
      </div>
      {state.status === "authenticated" ? (
        <AuditForm key={state.member.member_id} />
      ) : (
        <SessionStatus />
      )}
    </div>
  );
}
