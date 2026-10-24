import { LastModified } from "../../../shared/RecordActor";
import { ExistingReceipt } from "./ExistingReceipt";
import { DocumentPanel } from "../../documents/DocumentPanel";
import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, toApiError } from "../../../platform/api";
import { formatKrw, parseKrw } from "../../assets/months/model";
import { isDateOnly, isUuid, dateLabel, todaySeoul } from "../../finance/dates";
import { useHouseholdMembers } from "../../finance/FinanceSupport";
import { allPages, usePagedList, useResource } from "../../finance/queries";
import {
  ConflictReview,
  InsuranceError,
  InsurancePage,
  MetadataFeedback,
  useMetadataCommand,
} from "../InsuranceSupport";
import { changedFields, optional, preserveDraft } from "../model";
import type { Schema } from "../model";
import { useInsuranceEventsApi } from "../events/api";
import { CaseSelect, PolicySelect } from "../events/EventSupport";
import { PayoutList } from "../events/EventPages";
import { claimStates, exactSum, needsCompare } from "../events/model";
import { useIdempotencyKey } from "../../assets/months/useMonthCommand";
import { useUnsavedChangesGuard } from "../../../shared/UnsavedChanges";
import { AmountField } from "../../../shared/AmountField";
import { FormError, useSubmitAttempt } from "../../../shared/formValidation";
import { krwFieldError } from "../../../shared/krw";
import { formatSeoulDateTime } from "../../../shared/format";
type Draft = {
  caseId: string;
  policyId: string;
  reference: string;
  date: string;
  requested: string;
  decided: string;
  state: Schema["ClaimState"];
  note: string;
  expenses: string[];
};
function draftOf(row?: Schema["ClaimResponse"], caseId = "", policyId = ""): Draft {
  return {
    caseId: row?.case_id ?? caseId,
    policyId: row?.policy_id ?? policyId,
    reference: row?.claim_reference ?? "",
    date: row?.submitted_on ?? "",
    requested: row?.requested_krw ?? "",
    decided: row?.decided_krw ?? "",
    state: row?.claim_state ?? "draft",
    note: row?.decision_note ?? "",
    expenses: row?.expense_ids ?? [],
  };
}
export function claimInput(d: Draft): Schema["ClaimCreate"] | null {
  if (
    !isUuid(d.caseId) ||
    !isUuid(d.policyId) ||
    d.reference.length > 120 ||
    d.note.length > 2000 ||
    (d.date && (!isDateOnly(d.date) || d.date > todaySeoul())) ||
    (d.requested && parseKrw(d.requested) === null) ||
    (d.decided && parseKrw(d.decided) === null) ||
    d.expenses.length > 200 ||
    new Set(d.expenses).size !== d.expenses.length
  )
    return null;
  return {
    case_id: d.caseId,
    policy_id: d.policyId,
    claim_reference: optional(d.reference),
    submitted_on: optional(d.date),
    requested_krw: d.requested ? parseKrw(d.requested) : null,
    decided_krw: d.decided ? parseKrw(d.decided) : null,
    claim_state: d.state,
    decision_note: optional(d.note),
    expense_ids: d.expenses,
  };
}
export function ClaimSummary({
  row,
}: {
  row: Schema["ClaimResponse"] | Schema["ClaimRevisionResponse"];
}) {
  return (
    <>
      <dl className="metadata-grid">
        <div>
          <dt>청구 상태</dt>
          <dd>{claimStates[row.claim_state ?? "draft"]}</dd>
        </div>
        <div>
          <dt>접수 참고번호</dt>
          <dd>{row.claim_reference || "미입력"}</dd>
        </div>
        <div>
          <dt>실제 접수일</dt>
          <dd>{dateLabel(row.submitted_on ?? null)}</dd>
        </div>
        <div>
          <dt>청구액</dt>
          <dd>{formatKrw(row.requested_krw ?? null)}</dd>
        </div>
        <div>
          <dt>심사 결정액</dt>
          <dd>{formatKrw(row.decided_krw ?? null)}</dd>
        </div>
        <div>
          <dt>심사·결정 메모</dt>
          <dd>{row.decision_note || "미입력"}</dd>
        </div>
        <LastModified
          record={
            "updated_at" in row
              ? row
              : { updated_at: row.changed_at, updated_by_member_id: row.changed_by_member_id }
          }
        />
      </dl>
      <div className="form-actions">
        <Link to={`/insurance/cases/${row.case_id}`}>청구 사건</Link>
        <Link to={`/insurance/policies/${row.policy_id}`}>청구 계약</Link>
      </div>
      <p>현재 비용 근거 {row.expense_ids.length}개</p>
      {"received_krw" in row && (
        <p className="record-facts">
          이 청구의 실제 수령 {formatKrw(row.received_krw)} · 반환 {formatKrw(row.returned_krw)} ·
          순수령 {formatKrw(row.net_received_krw)}
        </p>
      )}
      <ul>
        {row.expense_ids.map((id, index) => (
          <li key={id}>
            <Link to={`/insurance/expenses/${id}`}>근거 의료비 {index + 1}</Link>
          </li>
        ))}
      </ul>
      <p className="muted">
        청구액과 결정액은 실제 입금이 아니에요. 같은 근거를 여러 청구에 연결해도 의료비는 한 번만
        합산해요.
      </p>
    </>
  );
}
export function ClaimEditor({
  initial,
  caseId = "",
  policyId = "",
}: {
  initial?: Schema["ClaimResponse"];
  caseId?: string;
  policyId?: string;
}) {
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const api = useInsuranceEventsApi();
  const command = useMetadataCommand();
  const navigate = useNavigate();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => draftOf(initial, caseId, policyId));
  const [reason, setReason] = useState("");
  const [latest, setLatest] = useState<Schema["ClaimResponse"] | null>(null);
  const [message, setMessage] = useState("");
  const attempt = useSubmitAttempt();
  const expenses = useResource(
    useCallback(
      () =>
        isUuid(draft.caseId)
          ? allPages((cursor) =>
              api.listMedicalExpenses({
                query: {
                  case_id: draft.caseId,
                  state: "active",
                  limit: 200,
                  ...(cursor ? { cursor } : {}),
                },
              }),
            )
          : Promise.resolve([]),
      [api, draft.caseId],
    ),
  );
  const input = claimInput(draft);
  // A retry of the same unsaved claim reuses its key, so the server records it once.
  const key = useIdempotencyKey(JSON.stringify(input));
  const changes = base && input ? changedFields(claimInput(draftOf(base))!, input) : null;
  const valid =
    !!input &&
    !expenses.loading &&
    !expenses.error &&
    draft.expenses.every((id) => expenses.data?.some((e) => e.id === id)) &&
    (!base || (!!reason.trim() && !!Object.keys(changes ?? {}).length));
  const change = <K extends keyof Draft>(field: K, value: Draft[K]) =>
    setDraft((old) => ({ ...old, [field]: value }));
  async function submit(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    event.preventDefault();
    if (needsCompare(command.error)) return;
    if (!input || !valid) {
      setMessage(
        base
          ? "바꾼 청구 내용과 정정 사유를 확인해 주세요."
          : "청구 보험계약·근거 비용·접수일·금액을 확인해 주세요.",
      );
      attempt.reject(form);
      return;
    }
    const result = await command.run(
      () =>
        base && changes
          ? api.updateInsuranceClaim({
              claimId: base.id,
              input: { ...changes, reason: reason.trim() },
              ifMatch: `"${base.version}"`,
            })
          : api.createInsuranceClaim({ input, idempotencyKey: key }),
      !base,
    );
    if (result && command.mounted.current) {
      guard.release();
      navigate(`/insurance/claims/${result.id}`, { replace: true });
    }
  }
  async function compare() {
    if (!base) return;
    try {
      const row = await api.getInsuranceClaim({ claimId: base.id });
      if (command.mounted.current) setLatest(row);
    } catch (error) {
      command.setError(toApiError(error));
    }
  }
  function adopt(keep: boolean) {
    if (!latest) return;
    setDraft(keep ? preserveDraft(draftOf(base), draft, draftOf(latest)) : draftOf(latest));
    setBase(latest);
    setLatest(null);
    command.setError(null);
    void expenses.reload();
  }
  return (
    <section className="card">
      <h2>{base ? "청구 상태·근거 정정" : "청구 기록"}</h2>
      <form
        onInput={() => {
          setDirty(true);
          setMessage("");
        }}
        onSubmit={(e) => void submit(e)}
      >
        <fieldset disabled={command.busy}>
          <legend>청구와 근거</legend>
          {base ? (
            <p>
              청구의 사건·계약은 유지해요. 잘못 선택했다면 사유를 남겨 철회하고 새 청구를 기록해
              주세요.
            </p>
          ) : (
            <>
              <CaseSelect
                label="청구 사건"
                value={draft.caseId}
                onChange={(id) => setDraft((old) => ({ ...old, caseId: id, expenses: [] }))}
              />
              <PolicySelect
                required
                value={draft.policyId}
                onChange={(id) => change("policyId", id)}
              />
            </>
          )}
          <div className="form-grid">
            <div className="form-field">
              <label>
                청구 상태
                <select
                  value={draft.state}
                  onChange={(e) => change("state", e.target.value as Draft["state"])}
                >
                  {Object.entries(claimStates).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-field">
              <label>
                청구 접수번호 (선택)
                <input
                  maxLength={120}
                  value={draft.reference}
                  onChange={(e) => change("reference", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                실제 청구 접수일
                <input
                  type="date"
                  max={todaySeoul()}
                  value={draft.date}
                  onChange={(e) => change("date", e.target.value)}
                />
              </label>
            </div>
            <AmountField
              label="직접 입력한 청구액 (원)"
              value={draft.requested}
              error={
                attempt.attempted
                  ? krwFieldError(draft.requested, { required: false, positive: false })
                  : null
              }
              onChange={(value) => change("requested", value)}
            />
            <AmountField
              label="심사 결정액 (원)"
              value={draft.decided}
              error={
                attempt.attempted
                  ? krwFieldError(draft.decided, { required: false, positive: false })
                  : null
              }
              onChange={(value) => change("decided", value)}
            />
            <div className="form-field">
              <label>
                청구·심사 메모
                <textarea
                  maxLength={2000}
                  value={draft.note}
                  onChange={(e) => change("note", e.target.value)}
                />
              </label>
            </div>
          </div>
          <p>미입력은 0원이 아니에요. 청구 종료를 실제 지급 완료로 바꾸지 않아요.</p>
          <h3>같은 사건의 실제 비용 근거</h3>
          {!expenses.loading && !expenses.error && (
            <p role="status">
              선택 근거 {draft.expenses.length}개 · 실제 지불금 합계{" "}
              {formatKrw(
                exactSum(
                  (expenses.data ?? [])
                    .filter((e) => draft.expenses.includes(e.id))
                    .map((e) => e.cash.amount_krw),
                ),
              )}
            </p>
          )}
          <p className="muted">
            근거 합계는 실제 지불금 원본의 합계예요. 병원 환불·보장 조건을 반영한 청구액을 자동
            입력하지 않아요.
          </p>
          <InsuranceError error={expenses.error} />
          {expenses.error && (
            <button type="button" onClick={() => void expenses.reload()}>
              근거 비용 다시 확인
            </button>
          )}
          {expenses.loading && <p role="status">모든 비용 근거를 확인하고 있어요.</p>}
          <ul className="finance-list">
            {expenses.data?.map((expense) => (
              <li key={expense.id}>
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={draft.expenses.includes(expense.id)}
                    disabled={!draft.expenses.includes(expense.id) && draft.expenses.length >= 200}
                    onChange={(e) =>
                      change(
                        "expenses",
                        e.target.checked
                          ? [...draft.expenses, expense.id]
                          : draft.expenses.filter((id) => id !== expense.id),
                      )
                    }
                  />
                  {expense.provider_name || "의료비"} · {dateLabel(expense.cash.occurred_on)} ·{" "}
                  {formatKrw(expense.cash.amount_krw)}
                  {expense.receipt_reference ? ` · 영수증 ${expense.receipt_reference}` : ""}
                </label>
              </li>
            ))}
          </ul>
          {draft.expenses.some((id) => !expenses.data?.some((e) => e.id === id)) &&
            !expenses.loading && (
              <p role="alert">
                현재 활성 비용에 없는 근거가 있어요.{" "}
                <button
                  type="button"
                  onClick={() =>
                    change(
                      "expenses",
                      draft.expenses.filter((id) => expenses.data?.some((e) => e.id === id)),
                    )
                  }
                >
                  사용할 수 없는 근거 제외
                </button>
              </p>
            )}
          {base && (
            <div className="form-field">
              <label>
                청구 정정 사유
                <textarea
                  required
                  maxLength={500}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            </div>
          )}
        </fieldset>
        <FormError message={message} />
        <MetadataFeedback command={command} listPath={`/insurance/cases/${draft.caseId}`} />
        <ConflictReview
          error={command.error}
          compare={() => void compare()}
          latest={!!latest}
          adopt={() => adopt(true)}
          replace={() => adopt(false)}
        >
          {latest && <ClaimSummary row={latest} />}
        </ConflictReview>
        <div className="form-actions save-actions">
          <button
            type="submit"
            disabled={
              expenses.loading ||
              !!expenses.error ||
              command.busy ||
              command.uncertain ||
              needsCompare(command.error)
            }
          >
            {base ? "청구 정정 저장" : "청구 기록 저장"}
          </button>
          {!command.busy && (
            <Link
              replace
              className="button-link secondary-button"
              to={
                base
                  ? `/insurance/claims/${base.id}`
                  : isUuid(caseId)
                    ? `/insurance/cases/${caseId}`
                    : "/insurance/cases"
              }
            >
              입력 취소
            </Link>
          )}
        </div>
      </form>
    </section>
  );
}
const historyKey = (row: { id: string; version: number }) => `${row.id}:${row.version}`;
function ClaimHistory({ id }: { id: string }) {
  const api = useInsuranceEventsApi();
  const members = useHouseholdMembers();
  const history = usePagedList(
    useCallback(
      async (cursor?: number) => {
        const result = await api.insuranceClaimHistory({
          claimId: id,
          query: { limit: 50, ...(cursor ? { cursor } : {}) },
        });
        return { ...result, items: result.items.map((row) => ({ ...row, id: row.claim_id })) };
      },
      [api, id],
    ),
    historyKey,
  );
  return (
    <section className="card">
      <h2>청구 정정 이력</h2>
      <InsuranceError error={history.error} />
      {history.error && <button onClick={() => void history.reload()}>청구 이력 다시 확인</button>}
      <ol className="month-history">
        {history.items.map((row) => (
          <li key={historyKey(row)}>
            <h3>청구 버전 {row.version}</h3>
            <ClaimSummary row={row} />
            <p>
              {formatSeoulDateTime(row.changed_at)} ·{" "}
              {members.members.find((m) => m.member_id === row.changed_by_member_id)
                ?.display_name ?? "가계 구성원"}
            </p>
            {row.reason && <p>정정 사유: {row.reason}</p>}
          </li>
        ))}
      </ol>
      {history.cursor !== null && (
        <button onClick={() => void history.more()} disabled={history.loading}>
          청구 이력 더 보기
        </button>
      )}
    </section>
  );
}
export function ClaimsList({ caseId, policyId }: { caseId?: string; policyId?: string }) {
  const api = useInsuranceEventsApi();
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.listInsuranceClaims({
          query: {
            ...(caseId ? { case_id: caseId } : {}),
            ...(policyId ? { policy_id: policyId } : {}),
            limit: 50,
            ...(cursor ? { cursor } : {}),
          },
        }),
      [api, caseId, policyId],
    ),
  );
  const query = new URLSearchParams({
    ...(caseId ? { case: caseId } : {}),
    ...(policyId ? { policy: policyId } : {}),
  });
  return (
    <section className="card">
      <h2>청구 기록</h2>
      <Link to="/insurance/claims">전체 청구 작업 목록</Link>
      <Link className="button-link secondary-button" to={`/insurance/claims/new?${query}`}>
        청구 추가
      </Link>
      <InsuranceError error={list.error} />
      {list.error && <button onClick={() => void list.reload()}>청구 목록 다시 확인</button>}
      {!list.loading && !list.error && !list.items.length && (
        <p>등록된 청구가 없어요. 청구 없이 실제 수령부터 기록할 수도 있어요.</p>
      )}
      <ul className="finance-list">
        {list.items.map((row) => (
          <li key={row.id}>
            <Link to={`/insurance/claims/${row.id}`}>
              {row.claim_reference || "접수번호 미입력"} · {claimStates[row.claim_state ?? "draft"]}
            </Link>
            <p>
              근거 {row.expense_count}개 · 청구 {formatKrw(row.requested_krw ?? null)} · 결정{" "}
              {formatKrw(row.decided_krw ?? null)}
            </p>
          </li>
        ))}
      </ul>
      {list.cursor && (
        <button disabled={list.loading} onClick={() => void list.more()}>
          청구 더 보기
        </button>
      )}
    </section>
  );
}
function ClaimDetail({ id, edit }: { id: string; edit: boolean }) {
  const api = useInsuranceEventsApi();
  const result = useResource(
    useCallback(
      () =>
        isUuid(id)
          ? api.getInsuranceClaim({ claimId: id })
          : Promise.reject(new ApiError(404, "NOT_FOUND")),
      [api, id],
    ),
  );
  const row = result.data;
  return (
    <>
      <InsuranceError error={result.error} />
      {result.error && <button onClick={() => void result.reload()}>청구 다시 확인</button>}
      {result.loading && (
        <p className="loading-state" role="status">
          청구 기록을 확인하고 있어요.
        </p>
      )}
      {row &&
        !result.loading &&
        !result.error &&
        (edit ? (
          <ClaimEditor initial={row} />
        ) : (
          <>
            <section className="card">
              <h2>{row.claim_reference || "접수번호 미입력 청구"}</h2>
              <ClaimSummary row={row} />
              <div className="form-actions">
                <Link to={`/insurance/claims/${id}/edit`}>청구 상태·근거 정정</Link>
                <Link
                  to={`/insurance/payouts/new?case=${row.case_id}&policy=${row.policy_id}&claim=${id}`}
                >
                  이 청구의 실제 수령 기록
                </Link>
              </div>
            </section>
            <ExistingReceipt claim={row} saved={() => void result.reload()} />
            <PayoutList caseId={row.case_id} claimId={id} policyId={row.policy_id} />
            <section id="claim-documents" tabIndex={-1}>
              <DocumentPanel kind="claim" id={id} />
            </section>
            <ClaimHistory id={id} />
          </>
        ))}
    </>
  );
}
export function ClaimNewPage() {
  const [query] = useSearchParams();
  return (
    <InsurancePage title="보험 청구 기록" description="접수와 심사 결과를 실제 수령과 구분해요.">
      <ClaimEditor caseId={query.get("case") ?? ""} policyId={query.get("policy") ?? ""} />
    </InsurancePage>
  );
}
export function ClaimDetailPage({ edit = false }: { edit?: boolean }) {
  const { id = "" } = useParams();
  return (
    <InsurancePage
      title={edit ? "보험 청구 정정" : "보험 청구 상세"}
      description="근거 비용과 청구 상태·정정 이력을 확인해요."
    >
      <ClaimDetail key={`${id}:${edit}`} id={id} edit={edit} />
    </InsurancePage>
  );
}
