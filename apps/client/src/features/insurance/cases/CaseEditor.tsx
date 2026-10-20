import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { toApiError } from "../../../platform/api";
import { dateLabel, isUuid, todaySeoul } from "../../finance/dates";
import type { HouseholdMember } from "../../finance/FinanceSupport";
import { useHouseholdMembers } from "../../finance/FinanceSupport";
import { useInsuranceApi } from "../api";
import {
  changedFields,
  finances,
  optional,
  preserveDraft,
  treatments,
  validPeriod,
} from "../model";
import type { InsuranceCase, Schema } from "../model";
import {
  ConflictReview,
  MemberSelect,
  MetadataFeedback,
  useMetadataCommand,
} from "../InsuranceSupport";
import { useUnsavedChangesGuard } from "../../../shared/UnsavedChanges";
export type CaseDraft = {
  title: string;
  patient: string;
  diagnosis: string;
  code: string;
  start: string;
  end: string;
  treatment: InsuranceCase["treatment_state"];
  financial: InsuranceCase["financial_state"];
};
export function caseDraft(row?: InsuranceCase): CaseDraft {
  return {
    title: row?.title ?? "",
    patient: row?.patient_member_id ?? "",
    diagnosis: row?.diagnosis_note ?? "",
    code: row?.diagnosis_code ?? "",
    start: row?.start_on ?? todaySeoul(),
    end: row?.end_on ?? "",
    treatment: row?.treatment_state ?? "ongoing",
    financial: row?.financial_state ?? "open",
  };
}
export function caseInput(d: CaseDraft): Schema["CaseInput"] | null {
  if (
    !d.title.trim() ||
    d.title.trim().length > 120 ||
    !isUuid(d.patient) ||
    d.diagnosis.length > 2000 ||
    d.code.length > 80 ||
    !validPeriod(d.start, d.end, true) ||
    d.start > todaySeoul() ||
    d.end > todaySeoul() ||
    (d.treatment === "ended") !== !!d.end
  )
    return null;
  return {
    title: d.title.trim(),
    patient_member_id: d.patient,
    diagnosis_note: optional(d.diagnosis),
    diagnosis_code: optional(d.code),
    start_on: d.start,
    end_on: optional(d.end),
    treatment_state: d.treatment,
    financial_state: d.financial,
  };
}
export function CaseSummary({
  row,
  members,
}: {
  row: Schema["CaseInput"];
  members: HouseholdMember[];
}) {
  return (
    <dl className="metadata-grid">
      <div>
        <dt>사건명</dt>
        <dd>{row.title}</dd>
      </div>
      <div>
        <dt>환자</dt>
        <dd>
          {members.find((m) => m.member_id === row.patient_member_id)?.display_name ??
            "구성원 확인 필요"}
        </dd>
      </div>
      <div>
        <dt>치료 상태</dt>
        <dd>{treatments[row.treatment_state ?? "ongoing"]}</dd>
      </div>
      <div>
        <dt>정산 상태</dt>
        <dd>{finances[row.financial_state ?? "open"]}</dd>
      </div>
      <div>
        <dt>사건 기간</dt>
        <dd>
          {dateLabel(row.start_on)} ~ {dateLabel(row.end_on ?? null)}
        </dd>
      </div>
      <div>
        <dt>진단명·설명</dt>
        <dd>{row.diagnosis_note || "미입력"}</dd>
      </div>
      <div>
        <dt>진단 코드</dt>
        <dd>{row.diagnosis_code || "미입력"}</dd>
      </div>
    </dl>
  );
}
export function CaseEditor({ initial }: { initial?: InsuranceCase }) {
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const members = useHouseholdMembers();
  const api = useInsuranceApi();
  const navigate = useNavigate();
  const command = useMetadataCommand();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => caseDraft(initial));
  const [reason, setReason] = useState("");
  const [latest, setLatest] = useState<InsuranceCase | null>(null);
  const input = caseInput(draft);
  const changes = input && base ? changedFields(caseInput(caseDraft(base))!, input) : null;
  const change = <K extends keyof CaseDraft>(key: K, value: CaseDraft[K]) =>
    setDraft((old) => ({
      ...old,
      [key]: value,
      ...(key === "treatment" && value === "ongoing" ? { end: "" } : {}),
    }));
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (
      !input ||
      (base && (!reason.trim() || !Object.keys(changes ?? {}).length)) ||
      command.error?.status === 409
    )
      return;
    const result = await command.run(
      () =>
        base && changes
          ? api.updateCase(base.id, { ...changes, reason: reason.trim() }, base.version)
          : api.createCase(input),
      !base,
    );
    if (result && command.mounted.current) {
      guard.release();
      navigate(`/insurance/cases/${result.id}`, { replace: true });
    }
  }
  async function compare() {
    if (!base) return;
    try {
      const result = await api.case(base.id);
      if (command.mounted.current) setLatest(result);
    } catch (error) {
      if (command.mounted.current) command.setError(toApiError(error));
    }
  }
  function adopt(keep: boolean) {
    if (!latest) return;
    setDraft(keep ? preserveDraft(caseDraft(base), draft, caseDraft(latest)) : caseDraft(latest));
    setBase(latest);
    setLatest(null);
    command.setError(null);
  }
  return (
    <section className="card">
      <h2>독립 보험 사건</h2>
      <p>
        여러 보험계약의 청구와 지급을 한 사건에 연결할 수 있어요. 치료 종료와 정산 종료는 각각
        기록해요.
      </p>
      <form onInput={() => setDirty(true)} onSubmit={(e) => void submit(e)}>
        <fieldset disabled={command.busy}>
          <legend>사건 내용</legend>
          <div className="form-grid">
            <div className="form-field">
              <label>
                사건 이름
                <input
                  required
                  maxLength={120}
                  value={draft.title}
                  onChange={(e) => change("title", e.target.value)}
                />
              </label>
            </div>
            <MemberSelect
              label="사건 환자"
              required
              value={draft.patient}
              onChange={(v) => change("patient", v)}
            />
            <div className="form-field">
              <label>
                진단명·설명 (선택)
                <textarea
                  maxLength={2000}
                  value={draft.diagnosis}
                  onChange={(e) => change("diagnosis", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                진단 코드 (선택)
                <input
                  maxLength={80}
                  value={draft.code}
                  onChange={(e) => change("code", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                사건 시작일
                <input
                  required
                  type="date"
                  max={todaySeoul()}
                  value={draft.start}
                  onChange={(e) => change("start", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                치료 상태
                <select
                  value={draft.treatment}
                  onChange={(e) => change("treatment", e.target.value as CaseDraft["treatment"])}
                >
                  {Object.entries(treatments).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {draft.treatment === "ended" && (
              <div className="form-field">
                <label>
                  치료 종료일
                  <input
                    required
                    type="date"
                    min={draft.start}
                    max={todaySeoul()}
                    value={draft.end}
                    onChange={(e) => change("end", e.target.value)}
                  />
                </label>
              </div>
            )}
            <div className="form-field">
              <label>
                정산 상태
                <select
                  value={draft.financial}
                  onChange={(e) => change("financial", e.target.value as CaseDraft["financial"])}
                >
                  {Object.entries(finances).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {base && (
              <div className="form-field">
                <label>
                  사건 변경 사유
                  <textarea
                    required
                    maxLength={500}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                </label>
              </div>
            )}
          </div>
        </fieldset>
        <MetadataFeedback command={command} listPath="/insurance/cases" />
        <ConflictReview
          error={command.error}
          compare={() => void compare()}
          latest={!!latest}
          adopt={() => adopt(true)}
          replace={() => adopt(false)}
        >
          {latest && <CaseSummary row={latest} members={members.members} />}
        </ConflictReview>
        <div className="form-actions save-actions">
          <button
            type="submit"
            disabled={
              !input ||
              (!!base && (!reason.trim() || !Object.keys(changes ?? {}).length)) ||
              command.busy ||
              command.uncertain ||
              command.error?.status === 409
            }
          >
            {base ? "사건 변경 저장" : "보험 사건 등록"}
          </button>
          {!command.busy && (
            <Link
              replace
              className="button-link secondary-button"
              to={base ? `/insurance/cases/${base.id}` : "/insurance/cases"}
            >
              입력 취소
            </Link>
          )}
        </div>
      </form>
    </section>
  );
}
