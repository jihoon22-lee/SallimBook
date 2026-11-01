import { useCallback, useState } from "react";
import { Link } from "react-router";
import { useExpensePlanApi } from "../../fixed/expensePlanApi";
import { displayedTerms, shownPlanTerms } from "../../fixed/model";
import type { PlanTerms } from "../../fixed/model";
import { RuleSummary } from "../../fixed/RuleSummary";
import { NamedReference } from "../../finance/RelatedRecords";
import { allPages, useResource } from "../../finance/queries";
import { todaySeoul } from "../../finance/dates";
import { formatKrw } from "../../assets/months/model";
import { useInsuranceApi } from "../api";
import { InsuranceError, MetadataFeedback, useMetadataCommand } from "../InsuranceSupport";
import type { Policy, Schema } from "../model";
type PremiumLink = Schema["PremiumLinkResponse"];
function planAmount(terms: PlanTerms) {
  const every =
    terms.frequency === "days"
      ? `${terms.interval_count}일마다`
      : terms.frequency === "annual"
        ? `${terms.interval_count}년마다`
        : terms.interval_count > 1
          ? `${terms.interval_count}개월마다`
          : "매달";
  return `${every} ${terms.expected_amount_krw == null ? "금액 미정" : formatKrw(terms.expected_amount_krw)}`;
}
function PlanSummary({ terms }: { terms: PlanTerms }) {
  return (
    <dl className="metadata-grid">
      <div>
        <dt>분류</dt>
        <dd>{terms.category}</dd>
      </div>
      <div>
        <dt>계획 금액</dt>
        <dd>{planAmount(terms)}</dd>
      </div>
      <div>
        <dt>납부수단</dt>
        <dd>
          {terms.card_id ? (
            <NamedReference kind="cards" id={terms.card_id} />
          ) : terms.account_id ? (
            <NamedReference kind="accounts" id={terms.account_id} />
          ) : (
            "미지정"
          )}
        </dd>
      </div>
      <div>
        <dt>관리 방식</dt>
        <dd>{terms.tracking_mode === "scheduled" ? "납부 일정도 관리" : "월 계획만"}</dd>
      </div>
    </dl>
  );
}
export function PremiumLinks({ policy }: { policy: Policy }) {
  const api = useInsuranceApi();
  const plansApi = useExpensePlanApi();
  const command = useMetadataCommand();
  const [rule, setRule] = useState("");
  const [changing, setChanging] = useState<PremiumLink | null>(null);
  const [ack, setAck] = useState(false);
  const links = useResource(
    useCallback(() => allPages((cursor) => api.premiums(policy.id, cursor)), [api, policy.id]),
  );
  // Monthly plans and payment schedules share one store; one paged read names both kinds.
  const plans = useResource(
    useCallback(
      () => allPages((cursor) => plansApi.rules({ limit: 200, ...(cursor ? { cursor } : {}) })),
      [plansApi],
    ),
  );
  const today = todaySeoul();
  const planTerms = (id: string) => {
    const plan = plans.data?.find((row) => row.id === id);
    return plan && shownPlanTerms(plan, today);
  };
  const candidates = (plans.data ?? [])
    .flatMap((plan) => {
      const terms = shownPlanTerms(plan, today);
      return terms &&
        (!plan.ended_on || plan.ended_on > today) &&
        !links.data?.some((link) => link.rule_id === plan.id)
        ? [{ id: plan.id, terms }]
        : [];
    })
    .sort(
      (a, b) =>
        Number(b.terms.category === "보험료") - Number(a.terms.category === "보험료") ||
        a.terms.title.localeCompare(b.terms.title, "ko"),
    );
  // A plan-only item has no schedule versions; its terms come from the monthly plan.
  const scheduled = (row: PremiumLink) => row.rule.versions.length > 0;
  const title = (row: PremiumLink) =>
    scheduled(row)
      ? displayedTerms(row.rule).title
      : (planTerms(row.rule_id)?.title ?? "월 계획 항목");
  function terms(row: PremiumLink) {
    if (scheduled(row)) return <RuleSummary terms={displayedTerms(row.rule)} />;
    const plan = planTerms(row.rule_id);
    if (plan) return <PlanSummary terms={plan} />;
    return plans.loading ? (
      <p role="status">월 계획 내용을 불러오고 있어요.</p>
    ) : (
      <p className="muted">금액과 납부수단은 월 계획에서 확인할 수 있어요.</p>
    );
  }
  async function attach() {
    if (!rule) return;
    const result = await command.run(() => api.createPremium(policy.id, rule), true);
    if (result && command.mounted.current) {
      setRule("");
      void links.reload();
    }
  }
  async function toggle() {
    if (!changing || !ack) return;
    const result = await command.run(() =>
      api.updatePremium(policy.id, changing.id, !changing.active, changing.version),
    );
    if (result && command.mounted.current) {
      setChanging(null);
      setAck(false);
      void links.reload();
    }
  }
  return (
    <section className="card">
      <h2>보험료 항목</h2>
      <p>
        월 계획에 등록한 항목을 이 계약의 보험료로 연결해요. 금액·주기·납부수단은 월 계획에서
        바꾸고, 연결을 해제해도 월 계획과 지난 납부 기록은 그대로 남아요.
      </p>
      <InsuranceError error={links.error} />
      {links.error && <button onClick={() => void links.reload()}>보험료 연결 다시 확인</button>}
      <InsuranceError error={plans.error} />
      {plans.error && <button onClick={() => void plans.reload()}>월 계획 다시 확인</button>}
      <Link to="/fixed-payments?new=1">월 계획에 보험료 항목 추가</Link>
      {policy.status === "active" && (
        <div className="form-actions">
          <label>
            연결할 월 계획 항목
            <select
              value={rule}
              disabled={plans.loading || links.loading || command.busy}
              onChange={(e) => setRule(e.target.value)}
            >
              <option value="">항목 선택</option>
              {candidates.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.terms.title} · {planAmount(row.terms)}
                </option>
              ))}
            </select>
          </label>
          <button
            disabled={!rule || command.busy || command.uncertain || !!plans.error || !!links.error}
            onClick={() => void attach()}
          >
            보험료 항목 연결
          </button>
        </div>
      )}
      <MetadataFeedback command={command} listPath={`/insurance/policies/${policy.id}`} />
      {command.error?.status === 409 && (
        <button
          onClick={() => {
            setChanging(null);
            setAck(false);
            command.setError(null);
            void links.reload();
          }}
        >
          최신 보험료 연결 다시 확인
        </button>
      )}
      {changing && (
        <section className="review-panel">
          <h3>보험료 연결 {changing.active ? "해제" : "복원"}</h3>
          {terms(changing)}
          <label className="checkbox-field">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            같은 월 계획 항목과 지난 납부 기록이 그대로 남는 것을 확인했어요.
          </label>
          <button
            disabled={!ack || command.busy || command.error?.status === 409}
            onClick={() => void toggle()}
          >
            보험료 연결 변경 저장
          </button>
          <button
            onClick={() => {
              setChanging(null);
              setAck(false);
            }}
          >
            연결 변경 취소
          </button>
        </section>
      )}
      {!links.loading && !links.error && links.data?.length === 0 && (
        <p>연결된 보험료 항목이 없어요.</p>
      )}
      <ul className="finance-list">
        {links.data?.map((row) => (
          <li key={row.id}>
            <h3>
              {title(row)} · {row.active ? "연결 중" : "연결 해제"}
            </h3>
            {terms(row)}
            <div className="form-actions">
              <Link to={`/fixed-payments?plan=${row.rule_id}`}>월 계획에서 보기</Link>
              {scheduled(row) && (
                <Link to={`/fixed-payments/rules/${row.rule_id}`}>같은 보험료 규칙과 이력</Link>
              )}
              {scheduled(row) && (!row.rule.ended_on || row.rule.ended_on > today) && (
                <Link to={`/fixed-payments/rules/${row.rule_id}/edit`}>보험료 적용기간 변경</Link>
              )}
              <button
                disabled={command.busy || (!row.active && policy.status !== "active")}
                onClick={() => {
                  setChanging(row);
                  setAck(false);
                }}
              >
                보험료 연결 {row.active ? "해제" : "복원"} 검토
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
