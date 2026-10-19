import { useCallback, useState } from "react";
import { Link } from "react-router";
import { useFixedApi } from "../../fixed/api";
import { displayedTerms } from "../../fixed/model";
import { RuleSummary } from "../../fixed/RuleSummary";
import { allPages, useResource } from "../../finance/queries";
import { todaySeoul } from "../../finance/dates";
import { useInsuranceApi } from "../api";
import { InsuranceError, MetadataFeedback, useMetadataCommand } from "../InsuranceSupport";
import type { Policy, Schema } from "../model";
export function PremiumLinks({ policy }: { policy: Policy }) {
  const api = useInsuranceApi();
  const fixed = useFixedApi();
  const command = useMetadataCommand();
  const [rule, setRule] = useState("");
  const [changing, setChanging] = useState<Schema["PremiumLinkResponse"] | null>(null);
  const [ack, setAck] = useState(false);
  const links = useResource(
    useCallback(() => allPages((cursor) => api.premiums(policy.id, cursor)), [api, policy.id]),
  );
  const rules = useResource(
    useCallback(
      () => allPages((cursor) => fixed.rules({ limit: 200, ...(cursor ? { cursor } : {}) })),
      [fixed],
    ),
  );
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
      <h2>보험료 납부 규칙</h2>
      <p>
        금액·주기·수단은 같은 고정 납부 규칙에서 관리해요. 연결 해제는 납부 규칙을 종료하거나 과거
        납부를 삭제하지 않아요.
      </p>
      <InsuranceError error={links.error} />
      {links.error && <button onClick={() => void links.reload()}>보험료 연결 다시 확인</button>}
      <InsuranceError error={rules.error} />
      {rules.error && <button onClick={() => void rules.reload()}>보험료 규칙 다시 확인</button>}
      <Link to="/fixed-payments/rules/new">보험료 납부 규칙 새로 등록</Link>
      {policy.status === "active" && (
        <div className="form-actions">
          <label>
            연결할 보험료 규칙
            <select
              value={rule}
              disabled={rules.loading || links.loading || command.busy}
              onChange={(e) => setRule(e.target.value)}
            >
              <option value="">규칙 선택</option>
              {rules.data
                ?.filter(
                  (r) =>
                    (!r.ended_on || r.ended_on > todaySeoul()) &&
                    !links.data?.some((l) => l.rule_id === r.id),
                )
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {displayedTerms(r).title}
                  </option>
                ))}
            </select>
          </label>
          <button
            disabled={!rule || command.busy || command.uncertain || !!rules.error || !!links.error}
            onClick={() => void attach()}
          >
            보험료 규칙 연결
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
          <RuleSummary terms={displayedTerms(changing.rule)} />
          <label className="checkbox-field">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            같은 납부 규칙의 과거 기록이 보존되는 것을 확인했어요.
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
        <p>연결된 보험료 규칙이 없어요.</p>
      )}
      <ul className="finance-list">
        {links.data?.map((row) => (
          <li key={row.id}>
            <h3>
              {displayedTerms(row.rule).title} · {row.active ? "연결 중" : "연결 해제"}
            </h3>
            <RuleSummary terms={displayedTerms(row.rule)} />
            <div className="form-actions">
              <Link to={`/fixed-payments/rules/${row.rule_id}`}>같은 보험료 규칙과 이력</Link>
              {(!row.rule.ended_on || row.rule.ended_on > todaySeoul()) && (
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
