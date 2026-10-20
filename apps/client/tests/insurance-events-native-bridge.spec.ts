import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.use({ trace: "off", screenshot: "off", video: "off" });
const id = "00000000-0000-4000-8000-000000000001";
const child = "00000000-0000-4000-8000-000000000002";
const methods = [
  "medicalNodeSummary",
  "insuranceCaseSummary",
  "listInsuranceClaims",
  "createInsuranceClaim",
  "getInsuranceClaim",
  "updateInsuranceClaim",
  "insuranceClaimHistory",
  "listMedicalExpenses",
  "createMedicalExpense",
  "getMedicalExpense",
  "correctMedicalExpense",
  "medicalExpenseHistory",
  "listMedicalRefunds",
  "createMedicalRefund",
  "voidMedicalExpense",
  "getMedicalRefund",
  "correctMedicalRefund",
  "medicalRefundHistory",
  "voidMedicalRefund",
  "getPayoutAllocation",
  "linkPayoutAllocation",
  "payoutAllocationHistory",
  "listInsurancePayouts",
  "createInsurancePayout",
  "getInsurancePayout",
  "correctInsurancePayout",
  "insurancePayoutHistory",
  "listInsuranceReturns",
  "createInsuranceReturn",
  "voidInsurancePayout",
  "getInsuranceReturn",
  "correctInsuranceReturn",
  "insuranceReturnHistory",
  "voidInsuranceReturn",
];

async function setup(page: Page, scenario = "success") {
  await page.route("**/__insurance-events-bridge", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><title>Synthetic insurance bridge test</title>",
    }),
  );
  await page.addInitScript(
    ({ methods, scenario }) => {
      const state = { calls: [] as { method: string; args: unknown }[], http: 0 };
      Object.assign(window, {
        __insuranceEventsBridge: state,
        CapacitorCustomPlatform: { name: "android" },
        Capacitor: {
          PluginHeaders:
            scenario === "unavailable"
              ? []
              : [
                  {
                    name: "SallimBookAuth",
                    methods: methods.map((name) => ({ name, rtype: "promise" })),
                  },
                ],
          nativePromise: async (_plugin: string, method: string, args: unknown) => {
            state.calls.push({ method, args });
            if (scenario === "cancelled") return { ok: false, code: "AUTH_CANCELLED" };
            if (scenario === "locked") return { ok: false, code: "APP_LOCKED" };
            if (scenario === "reauthenticate")
              return { ok: false, code: "REAUTHENTICATION_REQUIRED" };
            if (scenario === "conflict")
              return {
                ok: true,
                value: {
                  status: 409,
                  body: {
                    error: {
                      code: "MEDICAL_EXPENSE_IN_CLAIM",
                      message: "synthetic private detail",
                    },
                  },
                },
              };
            return {
              ok: true,
              value: {
                status: 200,
                body: {
                  marker: method,
                  amount_krw: "99999999999999999999",
                  missing: null,
                  zero: "0",
                },
              },
            };
          },
        },
      });
      const original = window.fetch;
      window.fetch = (input, init) => {
        const url = input instanceof Request ? input.url : String(input);
        if (new URL(url, location.href).pathname.startsWith("/api/")) state.http++;
        return original.call(window, input, init);
      };
    },
    { methods, scenario },
  );
  await page.goto("/__insurance-events-bridge");
}

test("34 insurance event commands preserve arguments and avoid web HTTP and storage", async ({
  page,
}) => {
  await setup(page);
  const result = await page.evaluate(
    async ({ id, child, methods }) => {
      const source = "/src/platform/nativeFinance.ts";
      const { nativeFinance } = await import(source);
      const payment = {
        amount_krw: "99999999999999999999",
        occurred_on: "2026-01-31",
        account_id: null,
        card_id: null,
        note: null,
      };
      const expense = {
        ...payment,
        case_id: id,
        node_id: child,
        gross_medical_krw: null,
        public_coverage_krw: "0",
        lines: [],
      };
      const payout = {
        ...payment,
        allocations: [
          {
            case_id: id,
            policy_id: null,
            claim_id: null,
            benefit_type: "fixed",
            amount_krw: payment.amount_krw,
          },
        ],
      };
      const reason = { reason: "합성 정정 사유" };
      const inputs: Record<string, unknown> = {
        ExpenseCreate: expense,
        ExpenseCorrection: { ...expense, ...reason },
        RefundCreate: { ...payment, ...reason },
        PayoutCreate: payout,
        PayoutCorrection: { ...payout, ...reason },
        ReturnCreate: { ...payment, ...reason, original_allocation_id: child },
        EventReason: reason,
        ClaimCreate: {
          case_id: id,
          policy_id: child,
          expense_ids: [id],
          requested_krw: null,
          decided_krw: "0",
        },
        ClaimPatch: { ...reason, expense_ids: [], decision_note: null },
        AllocationLinkPatch: { ...reason, claim_id: null },
      };
      const cases: [string, Record<string, unknown>][] = [
        ["medicalNodeSummary", { caseId: id, nodeId: child }],
        ["insuranceCaseSummary", { caseId: id }],
        ["listInsuranceClaims", { query: { limit: 200, cursor: null } }],
        ["createInsuranceClaim", { input: inputs.ClaimCreate }],
        ["getInsuranceClaim", { claimId: id }],
        ["updateInsuranceClaim", { claimId: id, input: inputs.ClaimPatch, ifMatch: '"7"' }],
        ["insuranceClaimHistory", { claimId: id, query: { limit: 200, cursor: 8 } }],
        ["listMedicalExpenses", { query: { limit: 200, cursor: null } }],
        ["createMedicalExpense", { input: inputs.ExpenseCreate, idempotencyKey: "synthetic:1" }],
        ["getMedicalExpense", { resourceId: id }],
        [
          "correctMedicalExpense",
          {
            resourceId: id,
            input: inputs.ExpenseCorrection,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        ["medicalExpenseHistory", { resourceId: id, query: { limit: 200, cursor: 8 } }],
        ["listMedicalRefunds", { resourceId: id, query: { limit: 200, cursor: null } }],
        [
          "createMedicalRefund",
          {
            resourceId: id,
            input: inputs.RefundCreate,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        [
          "voidMedicalExpense",
          {
            resourceId: id,
            input: inputs.EventReason,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        ["getMedicalRefund", { resourceId: id }],
        [
          "correctMedicalRefund",
          {
            resourceId: id,
            input: inputs.RefundCreate,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        ["medicalRefundHistory", { resourceId: id, query: { limit: 200, cursor: 8 } }],
        [
          "voidMedicalRefund",
          {
            resourceId: id,
            input: inputs.EventReason,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        ["getPayoutAllocation", { allocationId: child }],
        [
          "linkPayoutAllocation",
          {
            allocationId: child,
            input: inputs.AllocationLinkPatch,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        ["payoutAllocationHistory", { allocationId: child, query: { limit: 200, cursor: 8 } }],
        ["listInsurancePayouts", { query: { limit: 200, cursor: null } }],
        ["createInsurancePayout", { input: inputs.PayoutCreate, idempotencyKey: "synthetic:1" }],
        ["getInsurancePayout", { resourceId: id }],
        [
          "correctInsurancePayout",
          {
            resourceId: id,
            input: inputs.PayoutCorrection,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        ["insurancePayoutHistory", { resourceId: id, query: { limit: 200, cursor: 8 } }],
        ["listInsuranceReturns", { resourceId: id, query: { limit: 200, cursor: null } }],
        [
          "createInsuranceReturn",
          {
            resourceId: id,
            input: inputs.ReturnCreate,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        [
          "voidInsurancePayout",
          {
            resourceId: id,
            input: inputs.EventReason,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        ["getInsuranceReturn", { resourceId: id }],
        [
          "correctInsuranceReturn",
          {
            resourceId: id,
            input: inputs.ReturnCreate,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
        ["insuranceReturnHistory", { resourceId: id, query: { limit: 200, cursor: 8 } }],
        [
          "voidInsuranceReturn",
          {
            resourceId: id,
            input: inputs.EventReason,
            ifMatch: '"7"',
            idempotencyKey: "synthetic:1",
          },
        ],
      ];
      const values = [];
      for (const [method, args] of cases) values.push(await nativeFinance[method](args));
      const state = (
        window as unknown as { __insuranceEventsBridge: { calls: unknown[]; http: number } }
      ).__insuranceEventsBridge;
      return {
        calls: state.calls,
        expected: cases.map(([method, args]) => ({ method, args })),
        values,
        methods,
        http: state.http,
        storage: localStorage.length + sessionStorage.length,
      };
    },
    { id, child, methods },
  );
  expect(result.calls).toEqual(result.expected);
  expect(result.calls).toHaveLength(34);
  expect(result.values).toHaveLength(34);
  expect(result.values[0]).toMatchObject({
    amount_krw: "99999999999999999999",
    missing: null,
    zero: "0",
  });
  expect(result.http).toBe(0);
  expect(result.storage).toBe(0);
});

for (const [scenario, expected] of [
  ["cancelled", "REQUEST_CANCELLED"],
  ["locked", "APP_LOCKED"],
  ["conflict", "MEDICAL_EXPENSE_IN_CLAIM"],
  ["unavailable", "NATIVE_AUTH_UNAVAILABLE"],
  ["reauthenticate", "REAUTHENTICATION_REQUIRED"],
]) {
  test(`insurance events fail closed without fetch or storage: ${scenario}`, async ({ page }) => {
    await setup(page, scenario);
    const result = await page.evaluate(async (id) => {
      const source = "/src/platform/nativeFinance.ts";
      const { nativeFinance } = await import(source);
      let code = "",
        message = "";
      try {
        await nativeFinance.voidMedicalExpense({
          resourceId: id,
          input: { reason: "합성 무효" },
          ifMatch: '"7"',
          idempotencyKey: "synthetic:1",
        });
      } catch (error) {
        code = (error as { code: string }).code;
        message = String(error);
      }
      return {
        code,
        message,
        http: (window as unknown as { __insuranceEventsBridge: { http: number } })
          .__insuranceEventsBridge.http,
        storage: localStorage.length + sessionStorage.length,
      };
    }, id);
    expect(result.code).toBe(expected);
    expect(result.http).toBe(0);
    expect(result.storage).toBe(0);
    expect(result.message).not.toContain("synthetic private detail");
  });
}
