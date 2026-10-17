import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

// JS dispatch simulation only. JVM policy tests verify native validation and app-lock denial.
test.use({ trace: "off", screenshot: "off", video: "off" });
const id = "00000000-0000-4000-8000-000000000001";
const valueId = "00000000-0000-4000-8000-000000000002";
const methods = ["getAssetMonth", "getAssetMonthRevision", "listAssetMonthRevisions", "createAssetMonthDraft", "updateAssetMonthValue",
  "synchronizeAssetMonthScope", "confirmAssetMonth", "reopenAssetMonth", "listIncome", "incomeSummary", "incomeDuplicateCandidates",
  "getIncome", "incomeHistory", "createIncome", "correctIncome", "voidIncome", "returnIncome", "convertIncomePrecision"];

async function setup(page: Page, scenario: "success" | "locked" | "conflict" | "unavailable" = "success") {
  await page.route("**/__cashflow-bridge", (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic bridge test</title>" }));
  await page.addInitScript(({ methods, scenario }) => {
    const state = { calls: [] as { method: string; args: unknown }[], http: 0 };
    Object.assign(window, { __cashflowBridge: state, CapacitorCustomPlatform: { name: "android" }, Capacitor: {
      PluginHeaders: scenario === "unavailable" ? [] : [{ name: "SallimBookAuth", methods: methods.map((name) => ({ name, rtype: "promise" })) }],
      nativePromise: async (_plugin: string, method: string, args: unknown) => {
        state.calls.push({ method, args });
        if (scenario === "locked") return { ok: false, code: "APP_LOCKED" };
        if (scenario === "conflict") return { ok: true, value: { status: 409, body: { error: { code: "INCOME_DUPLICATE_SUSPECTED", message: "synthetic private detail" } } } };
        return { ok: true, value: { status: 200, body: { marker: method, amount_krw: "99999999999999999999", missing: null, zero: "0" } } };
      },
    } });
    const original = window.fetch;
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (new URL(url, location.href).pathname.startsWith("/api/")) state.http++;
      return original.call(window, input, init);
    };
  }, { methods, scenario });
  await page.goto("/__cashflow-bridge");
}

test("18 named metadata commands retain DTO values and mutation keys without web HTTP", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async ({ id, valueId }) => {
    const source = "/src/platform/nativeFinance.ts";
    const { nativeFinance } = await import(source);
    const income = { kind: "salary", amount_krw: "99999999999999999999", period_month: "2026-01", date_precision: "month", member_id: id, occurred_on: null };
    const mutation = { ifMatch: '"7"', idempotencyKey: "synthetic.stable:retry-1" };
    const cases: [string, Record<string, unknown>][] = [
      ["getAssetMonth", { month: "2026-01", query: { cursor: null, limit: 200 } }],
      ["getAssetMonthRevision", { month: "2026-01", revisionNo: 3 }],
      ["listAssetMonthRevisions", { month: "2026-01", query: { cursor: 4 } }],
      ["createAssetMonthDraft", { month: "2026-01", input: { copy_previous: false }, idempotencyKey: mutation.idempotencyKey }],
      ["updateAssetMonthValue", { month: "2026-01", assetId: id, input: { revision_id: id, value_id: valueId, input_amount_krw: "0", as_of_date: "2026-01-31" }, ifMatch: mutation.ifMatch }],
      ["synchronizeAssetMonthScope", { month: "2026-01", input: { revision_id: id }, ifMatch: mutation.ifMatch }],
      ["confirmAssetMonth", { month: "2026-01", input: { revision_id: id, acknowledge_non_month_end_dates: true }, ...mutation }],
      ["reopenAssetMonth", { month: "2026-01", input: { revision_id: id, reason: "합성 정정" }, ...mutation }],
      ["listIncome", { query: { month: "2026-01", member_id: id } }],
      ["incomeSummary", { query: { month: "2026-01" } }],
      ["incomeDuplicateCandidates", { query: { month: "2026-01", kind: "salary", member_id: id, date_precision: "month" } }],
      ["getIncome", { recordId: id }],
      ["incomeHistory", { recordId: id, query: { cursor: 4, limit: 100 } }],
      ["createIncome", { input: income, idempotencyKey: mutation.idempotencyKey }],
      ["correctIncome", { recordId: id, input: { reason: "합성 정정", account_id: null }, ...mutation }],
      ["voidIncome", { recordId: id, input: { reason: "합성 무효" }, ...mutation }],
      ["returnIncome", { recordId: id, input: { amount_krw: "1", period_month: "2026-01", date_precision: "month", reason: "합성 반환" }, ...mutation }],
      ["convertIncomePrecision", { input: { sources: [{ id, version: 7 }], replacements: [income], reason: "합성 전환" }, idempotencyKey: mutation.idempotencyKey }],
    ];
    const values = [];
    for (const [method, args] of cases) values.push(await nativeFinance[method](args));
    const state = (window as unknown as { __cashflowBridge: { calls: { method: string; args: unknown }[]; http: number } }).__cashflowBridge;
    return { values, calls: state.calls, expected: cases.map(([method, args]) => ({ method, args })), http: state.http, storage: localStorage.length + sessionStorage.length };
  }, { id, valueId });
  expect(result.calls).toEqual(result.expected);
  expect(result.values).toEqual(methods.map((marker) => ({ marker, amount_krw: "99999999999999999999", missing: null, zero: "0" })));
  expect(result.http).toBe(0); expect(result.storage).toBe(0);
});

for (const scenario of ["locked", "conflict", "unavailable"] as const) test(`${scenario} fails closed with bounded API errors`, async ({ page }) => {
  await setup(page, scenario);
  const result = await page.evaluate(async ({ id }) => {
    const source = "/src/platform/nativeFinance.ts";
    const { nativeFinance } = await import(source);
    let error: { code?: string; status?: number; message?: string; keys?: string[] } = {};
    try { await nativeFinance.getIncome({ recordId: id }); }
    catch (caught) {
      const failure = caught as { code: string; status: number; message: string };
      error = { code: failure.code, status: failure.status, message: failure.message, keys: Object.keys(failure) };
    }
    const state = (window as unknown as { __cashflowBridge: { calls: unknown[]; http: number } }).__cashflowBridge;
    return { error, calls: state.calls.length, http: state.http };
  }, { id });
  expect(result.error.code).toBe(scenario === "locked" ? "APP_LOCKED" : scenario === "conflict" ? "INCOME_DUPLICATE_SUSPECTED" : "NATIVE_AUTH_UNAVAILABLE");
  expect(result.error.status).toBe(scenario === "conflict" ? 409 : 0);
  expect(result.error.message).toBe(result.error.code);
  expect(result.error.keys).not.toContain("body");
  expect(result.http).toBe(0); expect(result.calls).toBe(scenario === "unavailable" ? 0 : 1);
});
