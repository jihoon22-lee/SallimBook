import { useCallback } from "react";
import { Link } from "react-router";
import type { components } from "@sallimbook/api-client";
import { useAuth } from "../auth/AuthProvider";
import { nativeFinance } from "../../platform/nativeFinance";
import { useResource } from "../finance/queries";
import { formatSeoulDateTime } from "../../shared/format";

type PolicyLink = components["schemas"]["RulePolicyLink"];

/** The policy whose premium a payment rule or monthly-plan item pays; one read per item. */
export function useRuleInsuranceLink(ruleId: string) {
  const { domainApi } = useAuth();
  return useResource(
    useCallback(
      () =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/recurring-rules/{rule_id}/insurance-link", {
              params: { path: { rule_id: ruleId } },
            }),
          () => nativeFinance.getRecurringRuleInsuranceLink({ ruleId }),
        ),
      [domainApi, ruleId],
    ),
  );
}

export function PolicyLinkText({ row }: { row: PolicyLink }) {
  return (
    <>
      <Link to={`/insurance/policies/${row.policy_id}`}>
        {row.product_name} · {row.insurer}
      </Link>{" "}
      ·{" "}
      {row.policy_status === "active"
        ? "유지 중"
        : row.policy_status === "ended"
          ? "계약 종료"
          : "실효"}{" "}
      ·{" "}
      {row.active
        ? "보험료 연결 중"
        : `보험료 연결 종료${row.ended_at ? ` (${formatSeoulDateTime(row.ended_at)})` : ""}`}
    </>
  );
}

/** Shown only for an item that pays a premium; a failed read is a quiet notice, never a block. */
export function PlanInsuranceLink({ planId }: { planId: string }) {
  const resource = useRuleInsuranceLink(planId);
  const row = resource.data?.link;
  if (resource.error)
    return (
      <p className="muted" role="status">
        보험 계약 연결을 확인하지 못했어요.{" "}
        <button type="button" onClick={() => void resource.reload()}>
          보험 계약 연결 다시 확인
        </button>
      </p>
    );
  if (!row) return null;
  return (
    <p>
      보험료로 연결된 계약: <PolicyLinkText row={row} />
    </p>
  );
}
