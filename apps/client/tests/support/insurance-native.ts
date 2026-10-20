import type { Page } from "@playwright/test";
import { members } from "./finance";
import type { mockInsuranceEvents } from "./insurance-events";
type State = Awaited<ReturnType<typeof mockInsuranceEvents>>;
type Args = Record<string, any>;
const mapping: Record<string, { method: string; path: string; fields: Record<string, string> }> = {
  listInsuranceCases: {
    method: "GET",
    path: "/api/v1/insurance/cases",
    fields: {},
  },
  createInsuranceCase: {
    method: "POST",
    path: "/api/v1/insurance/cases",
    fields: {},
  },
  getInsuranceCase: {
    method: "GET",
    path: "/api/v1/insurance/cases/{case_id}",
    fields: {
      case_id: "caseId",
    },
  },
  updateInsuranceCase: {
    method: "PATCH",
    path: "/api/v1/insurance/cases/{case_id}",
    fields: {
      case_id: "caseId",
    },
  },
  insuranceCaseHistory: {
    method: "GET",
    path: "/api/v1/insurance/cases/{case_id}/history",
    fields: {
      case_id: "caseId",
    },
  },
  listMedicalNodes: {
    method: "GET",
    path: "/api/v1/insurance/cases/{case_id}/nodes",
    fields: {
      case_id: "caseId",
    },
  },
  createMedicalNode: {
    method: "POST",
    path: "/api/v1/insurance/cases/{case_id}/nodes",
    fields: {
      case_id: "caseId",
    },
  },
  deleteMedicalNode: {
    method: "DELETE",
    path: "/api/v1/insurance/cases/{case_id}/nodes/{node_id}",
    fields: {
      case_id: "caseId",
      node_id: "nodeId",
    },
  },
  getMedicalNode: {
    method: "GET",
    path: "/api/v1/insurance/cases/{case_id}/nodes/{node_id}",
    fields: {
      case_id: "caseId",
      node_id: "nodeId",
    },
  },
  updateMedicalNode: {
    method: "PATCH",
    path: "/api/v1/insurance/cases/{case_id}/nodes/{node_id}",
    fields: {
      case_id: "caseId",
      node_id: "nodeId",
    },
  },
  medicalNodeSummary: {
    method: "GET",
    path: "/api/v1/insurance/cases/{case_id}/nodes/{node_id}/summary",
    fields: {
      case_id: "caseId",
      node_id: "nodeId",
    },
  },
  insuranceCaseSummary: {
    method: "GET",
    path: "/api/v1/insurance/cases/{case_id}/summary",
    fields: {
      case_id: "caseId",
    },
  },
  listInsuranceClaims: {
    method: "GET",
    path: "/api/v1/insurance/claims",
    fields: {},
  },
  createInsuranceClaim: {
    method: "POST",
    path: "/api/v1/insurance/claims",
    fields: {},
  },
  getInsuranceClaim: {
    method: "GET",
    path: "/api/v1/insurance/claims/{claim_id}",
    fields: {
      claim_id: "claimId",
    },
  },
  updateInsuranceClaim: {
    method: "PATCH",
    path: "/api/v1/insurance/claims/{claim_id}",
    fields: {
      claim_id: "claimId",
    },
  },
  insuranceClaimHistory: {
    method: "GET",
    path: "/api/v1/insurance/claims/{claim_id}/history",
    fields: {
      claim_id: "claimId",
    },
  },
  listMedicalExpenses: {
    method: "GET",
    path: "/api/v1/insurance/medical-expenses",
    fields: {},
  },
  createMedicalExpense: {
    method: "POST",
    path: "/api/v1/insurance/medical-expenses",
    fields: {},
  },
  getMedicalExpense: {
    method: "GET",
    path: "/api/v1/insurance/medical-expenses/{resource_id}",
    fields: {
      resource_id: "resourceId",
    },
  },
  correctMedicalExpense: {
    method: "POST",
    path: "/api/v1/insurance/medical-expenses/{resource_id}/correct",
    fields: {
      resource_id: "resourceId",
    },
  },
  medicalExpenseHistory: {
    method: "GET",
    path: "/api/v1/insurance/medical-expenses/{resource_id}/history",
    fields: {
      resource_id: "resourceId",
    },
  },
  listMedicalRefunds: {
    method: "GET",
    path: "/api/v1/insurance/medical-expenses/{resource_id}/refunds",
    fields: {
      resource_id: "resourceId",
    },
  },
  createMedicalRefund: {
    method: "POST",
    path: "/api/v1/insurance/medical-expenses/{resource_id}/refunds",
    fields: {
      resource_id: "resourceId",
    },
  },
  voidMedicalExpense: {
    method: "POST",
    path: "/api/v1/insurance/medical-expenses/{resource_id}/void",
    fields: {
      resource_id: "resourceId",
    },
  },
  getMedicalRefund: {
    method: "GET",
    path: "/api/v1/insurance/medical-refunds/{resource_id}",
    fields: {
      resource_id: "resourceId",
    },
  },
  correctMedicalRefund: {
    method: "POST",
    path: "/api/v1/insurance/medical-refunds/{resource_id}/correct",
    fields: {
      resource_id: "resourceId",
    },
  },
  medicalRefundHistory: {
    method: "GET",
    path: "/api/v1/insurance/medical-refunds/{resource_id}/history",
    fields: {
      resource_id: "resourceId",
    },
  },
  voidMedicalRefund: {
    method: "POST",
    path: "/api/v1/insurance/medical-refunds/{resource_id}/void",
    fields: {
      resource_id: "resourceId",
    },
  },
  getPayoutAllocation: {
    method: "GET",
    path: "/api/v1/insurance/payout-allocations/{allocation_id}",
    fields: {
      allocation_id: "allocationId",
    },
  },
  linkPayoutAllocation: {
    method: "PATCH",
    path: "/api/v1/insurance/payout-allocations/{allocation_id}",
    fields: {
      allocation_id: "allocationId",
    },
  },
  payoutAllocationHistory: {
    method: "GET",
    path: "/api/v1/insurance/payout-allocations/{allocation_id}/history",
    fields: {
      allocation_id: "allocationId",
    },
  },
  listInsurancePayouts: {
    method: "GET",
    path: "/api/v1/insurance/payouts",
    fields: {},
  },
  createInsurancePayout: {
    method: "POST",
    path: "/api/v1/insurance/payouts",
    fields: {},
  },
  getInsurancePayout: {
    method: "GET",
    path: "/api/v1/insurance/payouts/{resource_id}",
    fields: {
      resource_id: "resourceId",
    },
  },
  correctInsurancePayout: {
    method: "POST",
    path: "/api/v1/insurance/payouts/{resource_id}/correct",
    fields: {
      resource_id: "resourceId",
    },
  },
  insurancePayoutHistory: {
    method: "GET",
    path: "/api/v1/insurance/payouts/{resource_id}/history",
    fields: {
      resource_id: "resourceId",
    },
  },
  listInsuranceReturns: {
    method: "GET",
    path: "/api/v1/insurance/payouts/{resource_id}/returns",
    fields: {
      resource_id: "resourceId",
    },
  },
  createInsuranceReturn: {
    method: "POST",
    path: "/api/v1/insurance/payouts/{resource_id}/returns",
    fields: {
      resource_id: "resourceId",
    },
  },
  voidInsurancePayout: {
    method: "POST",
    path: "/api/v1/insurance/payouts/{resource_id}/void",
    fields: {
      resource_id: "resourceId",
    },
  },
  listInsurancePolicies: {
    method: "GET",
    path: "/api/v1/insurance/policies",
    fields: {},
  },
  createInsurancePolicy: {
    method: "POST",
    path: "/api/v1/insurance/policies",
    fields: {},
  },
  getInsurancePolicy: {
    method: "GET",
    path: "/api/v1/insurance/policies/{policy_id}",
    fields: {
      policy_id: "policyId",
    },
  },
  updateInsurancePolicy: {
    method: "PATCH",
    path: "/api/v1/insurance/policies/{policy_id}",
    fields: {
      policy_id: "policyId",
    },
  },
  listInsuranceCoverages: {
    method: "GET",
    path: "/api/v1/insurance/policies/{policy_id}/coverages",
    fields: {
      policy_id: "policyId",
    },
  },
  createInsuranceCoverage: {
    method: "POST",
    path: "/api/v1/insurance/policies/{policy_id}/coverages",
    fields: {
      policy_id: "policyId",
    },
  },
  updateInsuranceCoverage: {
    method: "PATCH",
    path: "/api/v1/insurance/policies/{policy_id}/coverages/{coverage_id}",
    fields: {
      policy_id: "policyId",
      coverage_id: "coverageId",
    },
  },
  listPolicyPremiumLinks: {
    method: "GET",
    path: "/api/v1/insurance/policies/{policy_id}/premium-links",
    fields: {
      policy_id: "policyId",
    },
  },
  createPolicyPremiumLink: {
    method: "POST",
    path: "/api/v1/insurance/policies/{policy_id}/premium-links",
    fields: {
      policy_id: "policyId",
    },
  },
  updatePolicyPremiumLink: {
    method: "PATCH",
    path: "/api/v1/insurance/policies/{policy_id}/premium-links/{link_id}",
    fields: {
      policy_id: "policyId",
      link_id: "linkId",
    },
  },
  getInsuranceReturn: {
    method: "GET",
    path: "/api/v1/insurance/returns/{resource_id}",
    fields: {
      resource_id: "resourceId",
    },
  },
  correctInsuranceReturn: {
    method: "POST",
    path: "/api/v1/insurance/returns/{resource_id}/correct",
    fields: {
      resource_id: "resourceId",
    },
  },
  insuranceReturnHistory: {
    method: "GET",
    path: "/api/v1/insurance/returns/{resource_id}/history",
    fields: {
      resource_id: "resourceId",
    },
  },
  voidInsuranceReturn: {
    method: "POST",
    path: "/api/v1/insurance/returns/{resource_id}/void",
    fields: {
      resource_id: "resourceId",
    },
  },
};
export async function mockNativeInsurance(page: Page, state: State) {
  const calls: { method: string; args: Args }[] = [];
  const http: string[] = [];
  const control = {
    failure: "" as "" | "APP_LOCKED" | "SESSION_EXPIRED" | "NETWORK_UNAVAILABLE",
    method: "",
    delayMethod: "",
    delayMs: 0,
  };
  const metadata = (body: unknown, status = 200) => ({ ok: true, value: { status, body } });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) http.push(request.url());
  });
  await page.exposeFunction("syntheticInsuranceNative", async (method: string, args: Args) => {
    calls.push({ method, args });
    if (method === "getSession")
      return { ok: true, value: { available: true, authenticated: true } };
    if (method === "request") return metadata(args.path === "/api/v1/me" ? members[0] : members);
    if (control.failure && (!control.method || control.method === method))
      return { ok: false, code: control.failure };
    if (method === "editInsurancePolicyNumberUI") {
      const policy = state.core.policies.find((p) => p.id === args.policyId)!;
      policy.has_number = true;
      policy.masked_number = "••••ONLY";
      policy.version++;
      return { ok: true, value: { status: "saved" } };
    }
    if (method === "showInsurancePolicyNumberUI")
      return { ok: true, value: { status: "completed" } };
    if (method === "listAccounts")
      return metadata({ items: state.cashflow.finance.accounts, next_cursor: null });
    if (method === "listAssets")
      return metadata({
        items: state.cashflow.finance.assets.filter(
          (row: any) => !args.query?.kind || row.kind === args.query.kind,
        ),
        next_cursor: null,
      });
    if (method === "listCards") return metadata({ items: state.cashflow.cards, next_cursor: null });
    if (method === "listRecurringRules")
      return metadata({ items: state.cashflow.rules, next_cursor: null });
    const route = mapping[method];
    if (!route) return { ok: false, code: "INVALID_REQUEST" };
    let path = route.path;
    for (const [field, input] of Object.entries(route.fields))
      path = path.replace(`{${field}}`, args[input]);
    const query = new URLSearchParams(
      Object.fromEntries(
        Object.entries(args.query ?? {})
          .filter(([, value]) => value !== undefined && value !== null)
          .map(([key, value]) => [key, String(value)]),
      ),
    );
    const result = await state.handle(route.method, path, query, args.input ?? {}, {
      ...(args.idempotencyKey ? { "idempotency-key": args.idempotencyKey } : {}),
      ...(args.ifMatch ? { "if-match": args.ifMatch } : {}),
    });
    if (control.delayMethod === method && control.delayMs)
      await new Promise((resolve) => setTimeout(resolve, control.delayMs));
    return result.abort
      ? { ok: false, code: "NETWORK_UNAVAILABLE" }
      : metadata(result.body, result.status);
  });
  await page.addInitScript(
    (methods) =>
      Object.assign(window, {
        CapacitorCustomPlatform: { name: "android" },
        Capacitor: {
          PluginHeaders: [
            {
              name: "SallimBookAuth",
              methods: [
                ...methods,
                "getSession",
                "request",
                "listAccounts",
                "listAssets",
                "listCards",
                "listRecurringRules",
                "editInsurancePolicyNumberUI",
                "showInsurancePolicyNumberUI",
              ]
                .map((name) => ({ name, rtype: "promise" }))
                .concat([
                  { name: "addListener", rtype: "callback" },
                  { name: "removeListener", rtype: "promise" },
                ]),
            },
          ],
          nativeCallback: () => "synthetic-listener",
          nativePromise: (_plugin: string, method: string, args = {}) =>
            method === "removeListener"
              ? Promise.resolve()
              : (window as any).syntheticInsuranceNative(method, args),
        },
      }),
    Object.keys(mapping),
  );
  return { calls, http, control };
}
