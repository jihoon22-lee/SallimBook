import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { toApiError } from "../../../platform/api";
import { useAssetsApi } from "../../assets/api";
import { allPages, useResource } from "../../finance/queries";
import { useHouseholdMembers, dateLabel } from "../../finance/FinanceSupport";
import { useInsuranceApi } from "../api";
import { changedFields, policyStatuses, preserveDraft } from "../model";
import type { Policy } from "../model";
import {
  ConflictReview,
  InsuranceError,
  MemberSelect,
  MetadataFeedback,
  useMetadataCommand,
} from "../InsuranceSupport";
import { policyDraft, policyInput } from "./model";
import type { PolicyDraft } from "./model";
export function PolicySummary({ row }: { row: Policy }) {
  const members = useHouseholdMembers();
  const name = (id: string | null | undefined) =>
    id
      ? (members.members.find((m) => m.member_id === id)?.display_name ?? "구성원 확인 필요")
      : "미지정";
  return (
    <>
      <dl className="metadata-grid">
        <div>
          <dt>보험사·상품명</dt>
          <dd>
            {row.insurer} · {row.product_name}
          </dd>
        </div>
        <div>
          <dt>계약 상태</dt>
          <dd>{policyStatuses[row.status]}</dd>
        </div>
        <div>
          <dt>계약자 / 피보험자</dt>
          <dd>
            {name(row.policyholder_member_id)} / {name(row.insured_member_id)}
          </dd>
        </div>
        <div>
          <dt>수익자</dt>
          <dd>{row.beneficiary_note || "미입력"}</dd>
        </div>
        <div>
          <dt>계약 기간</dt>
          <dd>
            {dateLabel(row.contract_start ?? null)} ~ {dateLabel(row.contract_end ?? null)}
          </dd>
        </div>
        <div>
          <dt>보장 기간</dt>
          <dd>
            {dateLabel(row.coverage_start ?? null)} ~ {dateLabel(row.coverage_end ?? null)}
          </dd>
        </div>
        <div>
          <dt>납입 기간</dt>
          <dd>
            {dateLabel(row.payment_start ?? null)} ~ {dateLabel(row.payment_end ?? null)}
          </dd>
        </div>
        <div>
          <dt>평가액 연결</dt>
          <dd>
            {row.valuation_asset_id ? (
              <Link to={`/assets/${row.valuation_asset_id}`}>확인한 환급·적립 자산</Link>
            ) : (
              "연결 없음"
            )}
          </dd>
        </div>
        <div>
          <dt>메모</dt>
          <dd>{row.note || "미입력"}</dd>
        </div>
      </dl>
      <p className="muted">
        납입 보험료 누계로 자산 평가액을 만들지 않아요. 확인한 환급·적립액만 별도 자산에 기록해요.
      </p>
    </>
  );
}
export function PolicyEditor({ initial }: { initial?: Policy }) {
  const api = useInsuranceApi();
  const assetsApi = useAssetsApi();
  const navigate = useNavigate();
  const command = useMetadataCommand();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => policyDraft(initial));
  const [latest, setLatest] = useState<Policy | null>(null);
  const [validation, setValidation] = useState("");
  const assets = useResource(
    useCallback(
      () =>
        allPages((cursor) =>
          assetsApi.list({
            category: "financial",
            kind: "asset",
            status: "all",
            limit: 200,
            ...(cursor ? { cursor } : {}),
          }),
        ),
      [assetsApi],
    ),
  );
  const change = (key: keyof PolicyDraft, value: string) => {
    setDraft((old) => ({ ...old, [key]: value }));
    setValidation("");
  };
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (command.error?.status === 409) return;
    const input = policyInput(draft);
    if (!input) {
      setValidation("보험사·상품명·보장 시작일과 각 기간을 확인해 주세요.");
      return;
    }
    const changes = base ? changedFields(policyInput(policyDraft(base))!, input) : null;
    if (changes && !Object.keys(changes).length) {
      setValidation("변경한 내용이 없어요.");
      return;
    }
    const result = await command.run(
      () =>
        base && changes
          ? api.updatePolicy(base.id, changes, base.version)
          : api.createPolicy(input),
      !base,
    );
    if (result && command.mounted.current) navigate(`/insurance/policies/${result.id}`);
  }
  async function compare() {
    if (!base) return;
    try {
      const value = await api.policy(base.id);
      if (command.mounted.current) setLatest(value);
    } catch (error) {
      if (command.mounted.current) command.setError(toApiError(error));
    }
  }
  function adopt(keep: boolean) {
    if (!latest) return;
    setDraft(
      keep ? preserveDraft(policyDraft(base), draft, policyDraft(latest)) : policyDraft(latest),
    );
    setBase(latest);
    setLatest(null);
    command.setError(null);
  }
  const periods: [keyof PolicyDraft, string, boolean][] = [
    ["contractStart", "계약 시작일", false],
    ["contractEnd", "계약 종료일", false],
    ["coverageStart", "보장 시작일", true],
    ["coverageEnd", "보장 종료일", false],
    ["paymentStart", "납입 시작일", false],
    ["paymentEnd", "납입 종료일", false],
  ];
  return (
    <section className="card">
      <h2>보험 계약 기본정보</h2>
      <p>증권번호는 계약 저장 후 별도 보호 화면에서 관리해요.</p>
      <form onSubmit={(e) => void submit(e)}>
        <fieldset disabled={command.busy}>
          <legend>계약 내용</legend>
          <div className="form-grid">
            <div className="form-field">
              <label>
                보험사
                <input
                  required
                  maxLength={120}
                  value={draft.insurer}
                  onChange={(e) => change("insurer", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                보험 상품명
                <input
                  required
                  maxLength={120}
                  value={draft.product}
                  onChange={(e) => change("product", e.target.value)}
                />
              </label>
            </div>
            <MemberSelect
              label="보험 계약자"
              value={draft.holder}
              onChange={(v) => change("holder", v)}
            />
            <MemberSelect
              label="보험 피보험자"
              value={draft.insured}
              onChange={(v) => change("insured", v)}
            />
            <div className="form-field">
              <label>
                수익자 메모
                <textarea
                  maxLength={1000}
                  value={draft.beneficiary}
                  onChange={(e) => change("beneficiary", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                보험 계약 상태
                <select value={draft.status} onChange={(e) => change("status", e.target.value)}>
                  {Object.entries(policyStatuses).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {periods.map(([key, label, required]) => (
              <div className="form-field" key={key}>
                <label>
                  {label}
                  <input
                    type="date"
                    required={required}
                    value={draft[key]}
                    onChange={(e) => change(key, e.target.value)}
                  />
                </label>
              </div>
            ))}
            <div className="form-field">
              <label>
                환급·적립 평가액 자산
                <select
                  value={draft.asset}
                  disabled={assets.loading}
                  onChange={(e) => change("asset", e.target.value)}
                >
                  <option value="">자산 연결 안 함</option>
                  {assets.data
                    ?.filter((a) => a.status === "active" || a.id === draft.asset)
                    .map((a) => (
                      <option key={a.id} value={a.id} disabled={a.status !== "active"}>
                        {a.name}
                        {a.status === "active" ? "" : " · 사용 종료"}
                      </option>
                    ))}
                  {draft.asset && !assets.data?.some((a) => a.id === draft.asset) && (
                    <option value={draft.asset}>현재 연결 자산 · 다시 확인 필요</option>
                  )}
                </select>
              </label>
              <InsuranceError error={assets.error} />
              {assets.error && (
                <button type="button" onClick={() => void assets.reload()}>
                  평가액 자산 다시 확인
                </button>
              )}
            </div>
            <div className="form-field">
              <label>
                보험 계약 메모
                <textarea
                  maxLength={2000}
                  value={draft.note}
                  onChange={(e) => change("note", e.target.value)}
                />
              </label>
            </div>
          </div>
        </fieldset>
        {validation && <p role="alert">{validation}</p>}
        <MetadataFeedback command={command} listPath="/insurance/policies" />
        <ConflictReview
          error={command.error}
          compare={() => void compare()}
          latest={!!latest}
          adopt={() => adopt(true)}
          replace={() => adopt(false)}
        >
          {latest && <PolicySummary row={latest} />}
        </ConflictReview>
        <div className="form-actions save-actions">
          <button
            type="submit"
            disabled={command.busy || command.uncertain || command.error?.status === 409}
          >
            {base ? "보험 계약 수정 저장" : "보험 계약 등록"}
          </button>
          {!command.busy && (
            <Link
              className="button-link secondary-button"
              to={base ? `/insurance/policies/${base.id}` : "/insurance/policies"}
            >
              입력 취소
            </Link>
          )}
        </div>
      </form>
    </section>
  );
}
