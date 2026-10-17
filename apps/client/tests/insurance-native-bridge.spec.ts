import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.use({ trace: "off", screenshot: "off", video: "off" });
const id = "00000000-0000-4000-8000-000000000001";
const child = "00000000-0000-4000-8000-000000000002";
const methods = ["listInsurancePolicies", "createInsurancePolicy", "getInsurancePolicy", "updateInsurancePolicy", "listInsuranceCoverages",
  "createInsuranceCoverage", "updateInsuranceCoverage", "listPolicyPremiumLinks", "createPolicyPremiumLink", "updatePolicyPremiumLink",
  "listInsuranceCases", "createInsuranceCase", "getInsuranceCase", "updateInsuranceCase", "insuranceCaseHistory", "listMedicalNodes",
  "createMedicalNode", "getMedicalNode", "updateMedicalNode", "deleteMedicalNode", "editInsurancePolicyNumberUI", "showInsurancePolicyNumberUI"];

async function setup(page: Page, scenario = "success") {
  await page.route("**/__insurance-bridge", (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic insurance bridge test</title>" }));
  await page.addInitScript(({ methods, scenario }) => {
    const state = { calls: [] as { method: string; args: unknown }[], http: 0 };
    Object.assign(window, { __insuranceBridge: state, CapacitorCustomPlatform: { name: "android" }, Capacitor: {
      PluginHeaders: scenario === "unavailable" ? [] : [{ name: "SallimBookAuth", methods: methods.map((name) => ({ name, rtype: "promise" })) }],
      nativePromise: async (_plugin: string, method: string, args: unknown) => {
        state.calls.push({ method, args });
        if (scenario === "locked") return { ok: false, code: "APP_LOCKED" };
        if (scenario === "reauthenticate") return { ok: false, code: "REAUTHENTICATION_REQUIRED" };
        if (scenario === "conflict") return { ok: true, value: { status: 409, body: { error: { code: "MEDICAL_NODE_IN_USE", message: "synthetic private detail" } } } };
        if (method.endsWith("UI")) return { ok: true, value: { status: method.startsWith("edit") ? "saved" : "completed" } };
        if (method === "deleteMedicalNode") return { ok: true, value: { status: 204, body: null } };
        return { ok: true, value: { status: 200, body: { marker: method, insured_amount_krw: "99999999999999999999", missing: null, zero: "0" } } };
      },
    } });
    const original = window.fetch;
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (new URL(url, location.href).pathname.startsWith("/api/")) state.http++;
      return original.call(window, input, init);
    };
  }, { methods, scenario });
  await page.goto("/__insurance-bridge");
}

test("20 insurance metadata commands retain generated DTOs and never use web HTTP", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async ({ id, child }) => {
    const source = "/src/platform/nativeFinance.ts";
    const { nativeFinance } = await import(source);
    const input = { insurer: "합성 보험사", product_name: "합성 계약", coverage_start: "2026-01-31", status: "active" };
    const cases: [string, Record<string, unknown>][] = [
      ["listInsurancePolicies", { query: { status: "active", insured_member_id: id, cursor: null, limit: 200 } }],
      ["createInsurancePolicy", { input }], ["getInsurancePolicy", { policyId: id }],
      ["updateInsurancePolicy", { policyId: id, input: { note: null }, ifMatch: '"7"' }],
      ["listInsuranceCoverages", { policyId: id, query: { active: false } }],
      ["createInsuranceCoverage", { policyId: id, input: { name: "합성 보장", benefit_type: "fixed", insured_amount_krw: "99999999999999999999", active: true } }],
      ["updateInsuranceCoverage", { policyId: id, coverageId: child, input: { insured_amount_krw: "0" }, ifMatch: '"7"' }],
      ["listPolicyPremiumLinks", { policyId: id, query: { active: null } }],
      ["createPolicyPremiumLink", { policyId: id, input: { rule_id: child } }],
      ["updatePolicyPremiumLink", { policyId: id, linkId: child, input: { active: false }, ifMatch: '"7"' }],
      ["listInsuranceCases", { query: { patient_member_id: id, treatment_state: "ongoing", financial_state: "settled" } }],
      ["createInsuranceCase", { input: { title: "합성 사건", patient_member_id: id, start_on: "2026-01-31", treatment_state: "ongoing", financial_state: "open" } }],
      ["getInsuranceCase", { caseId: id }],
      ["updateInsuranceCase", { caseId: id, input: { end_on: null, treatment_state: "ongoing", reason: "합성 재개" }, ifMatch: '"7"' }],
      ["insuranceCaseHistory", { caseId: id, query: { cursor: 8, limit: 200 } }],
      ["listMedicalNodes", { caseId: id, query: { cursor: child } }],
      ["createMedicalNode", { caseId: id, input: { parent_id: null, kind: "group", label: "합성 그룹", sort_order: 0 } }],
      ["getMedicalNode", { caseId: id, nodeId: child }],
      ["updateMedicalNode", { caseId: id, nodeId: child, input: { parent_id: null }, ifMatch: '"7"' }],
      ["deleteMedicalNode", { caseId: id, nodeId: child, ifMatch: '"7"' }],
    ];
    const values = [];
    for (const [method, args] of cases) values.push(await nativeFinance[method](args));
    const state = (window as unknown as { __insuranceBridge: { calls: unknown[]; http: number } }).__insuranceBridge;
    return { calls: state.calls, expected: cases.map(([method, args]) => ({ method, args })), values, http: state.http, storage: localStorage.length + sessionStorage.length };
  }, { id, child });
  expect(result.calls).toEqual(result.expected);
  expect(result.calls).toHaveLength(20);
  expect(result.values[5]).toMatchObject({ insured_amount_krw: "99999999999999999999", missing: null, zero: "0" });
  expect(result.values[19]).toBeNull();
  expect(result.http).toBe(0); expect(result.storage).toBe(0);
});

test("policy number fields including null fail before any metadata bridge call", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeFinance.ts"; const { nativeFinance } = await import(source);
    const codes = [];
    for (const method of ["createInsurancePolicy", "updateInsurancePolicy"]) for (const policy_number of [null, "SYNTHETIC123"]) {
      try { await nativeFinance[method]({ policyId: id, ifMatch: '"7"', input: { insurer: "합성", product_name: "합성", coverage_start: "2026-01-31", policy_number } }); }
      catch (error) { codes.push((error as { code: string }).code); }
    }
    return { codes, state: (window as unknown as { __insuranceBridge: { calls: unknown[]; http: number } }).__insuranceBridge };
  }, id);
  expect(result.codes).toEqual(Array(4).fill("VALIDATION_ERROR"));
  expect(result.state.calls).toEqual([]); expect(result.state.http).toBe(0);
});

test("protected insurance number screens send only target and version and return status", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeFinance.ts"; const { nativeFinance } = await import(source);
    const edit = await nativeFinance.editInsurancePolicyNumber({ policyId: id, ifMatch: '"7"' });
    const show = await nativeFinance.showInsurancePolicyNumber({ policyId: id });
    return { edit, show, state: (window as unknown as { __insuranceBridge: { calls: unknown[]; http: number } }).__insuranceBridge };
  }, id);
  expect(result.edit).toEqual({ status: "saved" }); expect(result.show).toEqual({ status: "completed" });
  expect(result.state.calls).toEqual([{ method: "editInsurancePolicyNumberUI", args: { policyId: id, ifMatch: '"7"' } }, { method: "showInsurancePolicyNumberUI", args: { policyId: id } }]);
  expect(result.state.http).toBe(0);
});

for (const [scenario, expected] of [["locked", "APP_LOCKED"], ["unavailable", "NATIVE_AUTH_UNAVAILABLE"], ["reauthenticate", "REAUTHENTICATION_REQUIRED"], ["conflict", "MEDICAL_NODE_IN_USE"]]) {
  test(`insurance ${scenario} preserves safe error without HTTP fallback`, async ({ page }) => {
    await setup(page, scenario);
    const result = await page.evaluate(async ({ id, scenario }) => {
      const source = "/src/platform/nativeFinance.ts"; const { nativeFinance } = await import(source);
      let code = "", message = "";
      try { if (scenario === "reauthenticate") await nativeFinance.showInsurancePolicyNumber({ policyId: id }); else await nativeFinance.getInsurancePolicy({ policyId: id }); }
      catch (error) { code = (error as { code: string }).code; message = String(error); }
      return { code, message, http: (window as unknown as { __insuranceBridge: { http: number } }).__insuranceBridge.http };
    }, { id, scenario });
    expect(result.code).toBe(expected); expect(result.http).toBe(0); expect(result.message).not.toContain("synthetic private detail");
  });
}
