import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { toApiError } from "../../../platform/api";
import { formatKrw, parseKrw } from "../../assets/months/model";
import { dateLabel } from "../../finance/dates";
import { allPages, useResource } from "../../finance/queries";
import { useInsuranceApi } from "../api";
import { benefits, changedFields, optional, preserveDraft, validPeriod } from "../model";
import type { Coverage, Schema } from "../model";
import {
  ConflictReview,
  InsuranceError,
  MetadataFeedback,
  useMetadataCommand,
} from "../InsuranceSupport";
type Draft = {
  name: string;
  benefit: Coverage["benefit_type"];
  amount: string;
  start: string;
  end: string;
  note: string;
  active: boolean;
};
const draftOf = (row?: Coverage): Draft => ({
  name: row?.name ?? "",
  benefit: row?.benefit_type ?? "reimbursement",
  amount: row?.insured_amount_krw ?? "",
  start: row?.coverage_start ?? "",
  end: row?.coverage_end ?? "",
  note: row?.note ?? "",
  active: row?.active ?? true,
});
const inputOf = (d: Draft): Schema["CoverageInput"] => ({
  name: d.name.trim(),
  benefit_type: d.benefit,
  insured_amount_krw: d.amount ? parseKrw(d.amount) : null,
  coverage_start: optional(d.start),
  coverage_end: optional(d.end),
  note: optional(d.note),
  active: d.active,
});
function CoverageSummary({ row }: { row: Coverage }) {
  return (
    <>
      <p>
        {row.name} · {benefits[row.benefit_type]} · {row.active ? "유효" : "보장 종료"}
      </p>
      <p>
        기록한 보장금액 {formatKrw(row.insured_amount_krw ?? null)} ·{" "}
        {dateLabel(row.coverage_start ?? null)} ~ {dateLabel(row.coverage_end ?? null)}
      </p>
      {row.note && <p>보장 메모: {row.note}</p>}
    </>
  );
}
function CoverageEditor({
  policyId,
  initial,
  saved,
  cancel,
}: {
  policyId: string;
  initial?: Coverage;
  saved: () => void;
  cancel: () => void;
}) {
  const api = useInsuranceApi();
  const command = useMetadataCommand();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => draftOf(initial));
  const [latest, setLatest] = useState<Coverage | null>(null);
  const input = inputOf(draft);
  const changes = base ? changedFields(inputOf(draftOf(base)), input) : null;
  const valid =
    !!draft.name.trim() &&
    draft.name.trim().length <= 120 &&
    draft.note.length <= 2000 &&
    (!draft.amount || parseKrw(draft.amount) !== null) &&
    validPeriod(draft.start, draft.end) &&
    (!changes || Object.keys(changes).length > 0);
  const change = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((old) => ({ ...old, [key]: value }));
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || command.error?.status === 409) return;
    const result = await command.run(
      () =>
        base && changes
          ? api.updateCoverage(policyId, base.id, changes, base.version)
          : api.createCoverage(policyId, input),
      !base,
    );
    if (result && command.mounted.current) saved();
  }
  async function compare() {
    try {
      const rows = await allPages((cursor) => api.coverages(policyId, cursor));
      const row = rows.find((r) => r.id === base?.id);
      if (command.mounted.current) {
        if (row) setLatest(row);
        else command.setError(toApiError(new Error()));
      }
    } catch (error) {
      if (command.mounted.current) command.setError(toApiError(error));
    }
  }
  function adopt(keep: boolean) {
    if (!latest) return;
    setDraft(keep ? preserveDraft(draftOf(base), draft, draftOf(latest)) : draftOf(latest));
    setBase(latest);
    setLatest(null);
    command.setError(null);
  }
  return (
    <section className="review-panel">
      <h3>{initial ? "보장 항목 수정" : "보장 항목 등록"}</h3>
      <form onSubmit={(e) => void submit(e)}>
        <fieldset disabled={command.busy}>
          <legend>보장 내용</legend>
          <div className="form-grid">
            <div className="form-field">
              <label>
                보장 이름
                <input
                  required
                  maxLength={120}
                  value={draft.name}
                  onChange={(e) => change("name", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                보장 급부유형
                <select
                  value={draft.benefit}
                  onChange={(e) => change("benefit", e.target.value as Draft["benefit"])}
                >
                  {Object.entries(benefits).map(([k, v]) => (
                    <option value={k} key={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-field">
              <label>
                기록한 보장금액 (원)
                <input
                  inputMode="numeric"
                  value={draft.amount}
                  onChange={(e) => change("amount", e.target.value)}
                />
              </label>
              <p className="muted">
                미입력과 0원은 달라요. 실제 보험금이나 자동 예상 지급액이 아니에요.
              </p>
            </div>
            <div className="form-field">
              <label>
                항목 보장 시작일
                <input
                  type="date"
                  value={draft.start}
                  onChange={(e) => change("start", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                항목 보장 종료일
                <input
                  type="date"
                  value={draft.end}
                  onChange={(e) => change("end", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                보장 메모
                <textarea
                  maxLength={2000}
                  value={draft.note}
                  onChange={(e) => change("note", e.target.value)}
                />
              </label>
            </div>
          </div>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={draft.active}
              onChange={(e) => change("active", e.target.checked)}
            />
            보장 항목 사용 중
          </label>
        </fieldset>
        <MetadataFeedback command={command} listPath={`/insurance/policies/${policyId}`} />
        <ConflictReview
          error={command.error}
          compare={() => void compare()}
          latest={!!latest}
          adopt={() => adopt(true)}
          replace={() => adopt(false)}
        >
          {latest && <CoverageSummary row={latest} />}
        </ConflictReview>
        <div className="form-actions">
          <button
            type="submit"
            disabled={!valid || command.busy || command.uncertain || command.error?.status === 409}
          >
            보장 항목 저장
          </button>
          <button type="button" onClick={cancel} disabled={command.busy}>
            보장 편집 취소
          </button>
        </div>
      </form>
    </section>
  );
}
export function Coverages({ policyId }: { policyId: string }) {
  const api = useInsuranceApi();
  const rows = useResource(
    useCallback(() => allPages((cursor) => api.coverages(policyId, cursor)), [api, policyId]),
  );
  const [editing, setEditing] = useState<Coverage | "new" | null>(null);
  return (
    <section className="card">
      <h2>보장 항목</h2>
      <InsuranceError error={rows.error} />
      {rows.error && <button onClick={() => void rows.reload()}>보장 목록 다시 확인</button>}
      {rows.loading && <p role="status">보장 항목을 불러오고 있어요.</p>}
      <button onClick={() => setEditing("new")}>보장 항목 추가</button>
      {editing && (
        <CoverageEditor
          key={typeof editing === "string" ? "new" : `${editing.id}:${editing.version}`}
          policyId={policyId}
          initial={editing === "new" ? undefined : editing}
          saved={() => {
            setEditing(null);
            void rows.reload();
          }}
          cancel={() => setEditing(null)}
        />
      )}
      {!rows.loading && !rows.error && rows.data?.length === 0 && <p>등록된 보장 항목이 없어요.</p>}
      <ul className="finance-list">
        {rows.data?.map((row) => (
          <li key={row.id}>
            <CoverageSummary row={row} />
            <button onClick={() => setEditing(row)}>보장 수정: {row.name}</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
