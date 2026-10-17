import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

// JS dispatch simulation only. JVM policy tests verify native validation and app-lock denial.
test.use({ trace: "off", screenshot: "off", video: "off" });
const id = "00000000-0000-4000-8000-000000000001";
const valueId = "00000000-0000-4000-8000-000000000002";
const methods = ["getAssetMonth", "getAssetMonthRevision", "listAssetMonthRevisions", "createAssetMonthDraft", "updateAssetMonthValue",
  "synchronizeAssetMonthScope", "confirmAssetMonth", "reopenAssetMonth", "listIncome", "incomeSummary", "incomeDuplicateCandidates",
  "getIncome", "incomeHistory", "createIncome", "correctIncome", "voidIncome", "returnIncome", "convertIncomePrecision", "listCards", "getCard", "createCard", "updateCard", "archiveCard", "deleteCard", "getAssetComparison", "getAssetTrends",
  "listRecurringRules", "createRecurringRule", "getRecurringRule", "changeRecurringRule", "endRecurringRule", "generateObligations",
  "listObligations", "fixedCostSummary", "getObligation", "obligationHistory", "rescheduleObligation", "skipObligation", "unskipObligation",
  "completeObligation", "reopenObligation", "settleObligation", "listObligationSettlements", "voidFixedSettlement", "getCardPaymentLinks", "getAccountPaymentLinks"];

async function setup(page: Page, scenario: "success" | "locked" | "conflict" | "unavailable" = "success") {
  await page.route("**/__cashflow-bridge", (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic bridge test</title>" }));
  await page.addInitScript(({ methods, scenario }) => {
    const state = { calls: [] as { method: string; args: unknown }[], http: 0 };
    Object.assign(window, { __cashflowBridge: state, CapacitorCustomPlatform: { name: "android" }, Capacitor: {
      PluginHeaders: scenario === "unavailable" ? [] : [{ name: "SallimBookAuth", methods: [...methods, "updateAsset", "archiveAsset"].map((name) => ({ name, rtype: "promise" })) }],
      nativePromise: async (_plugin: string, method: string, args: unknown) => {
        state.calls.push({ method, args });
        if (scenario === "locked") return { ok: false, code: "APP_LOCKED" };
        if (scenario === "conflict") return { ok: true, value: { status: 409, body: { error: { code: "INCOME_DUPLICATE_SUSPECTED", message: "synthetic private detail" } } } };
        if (method === "deleteCard") return { ok: true, value: { status: 204, body: null } };
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

test("46 named metadata commands retain DTO values and mutation keys without web HTTP", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async ({ id, valueId }) => {
    const source = "/src/platform/nativeFinance.ts";
    const { nativeFinance } = await import(source);
    const income = { kind: "salary", amount_krw: "99999999999999999999", period_month: "2026-01", date_precision: "month", member_id: id, occurred_on: null };
    const mutation = { ifMatch: '"7"', idempotencyKey: "synthetic.stable:retry-1" };
    const terms = { title: "합성 납부", category: "합성 분류", amount_mode: "fixed", expected_amount_krw: "0", economic_type: "expense",
      anchor_date: "2026-01-31", frequency: "monthly", currency_reference: "USD", foreign_amount_reference: "12345678901234567890.12345678" };
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
      ["listCards", { query: { owner_member_id: id, status: "all", limit: 200 } }],
      ["getCard", { cardId: id }],
      ["createCard", { input: { owner_member_id: id, issuer_name: "합성 카드사", product_name: "합성 카드", card_type: "credit", last_four: "1234", settlement_day: 31 } }],
      ["updateCard", { cardId: id, input: { settlement_account_id: null, alias: "합성 변경" }, ifMatch: mutation.ifMatch }],
      ["archiveCard", { cardId: id, input: { ended_on: "2026-01-31" }, ifMatch: mutation.ifMatch }],
      ["deleteCard", { cardId: id, ifMatch: mutation.ifMatch }],
      ["getAssetComparison", { query: { to: "2026-01", from: null, asset_id: id, limit: 200 } }],
      ["getAssetTrends", { query: { from: "2016-02", to: "2026-01", asset_id: id } }],
      ["listRecurringRules", { query: { limit: 200, cursor: null } }],
      ["createRecurringRule", { input: { ...terms, effective_from: "2026-01-01", effective_until: "2027-01-01", end_reason: "합성 초기 종료" }, idempotencyKey: mutation.idempotencyKey }],
      ["getRecurringRule", { ruleId: id }],
      ["changeRecurringRule", { ruleId: id, input: { ...terms, amount_mode: "variable", expected_amount_krw: null, effective_from: "2026-02-01", reason: "합성 조건 변경" }, ...mutation }],
      ["endRecurringRule", { ruleId: id, input: { effective_on: "2027-01-01", reason: "합성 종료" }, ...mutation }],
      ["generateObligations", { input: { rule_id: id, start_date: "2026-01-01", end_date: "2026-12-31" }, idempotencyKey: mutation.idempotencyKey }],
      ["listObligations", { query: { month: "2026-01", limit: 200 } }],
      ["fixedCostSummary", { query: { month: "2026-01" } }],
      ["getObligation", { obligationId: id }],
      ["obligationHistory", { obligationId: id, query: { cursor: 4, limit: 200 } }],
      ["rescheduleObligation", { obligationId: id, input: { scheduled_date: "2026-01-30", reason: "합성 이동" }, ...mutation }],
      ["skipObligation", { obligationId: id, input: { reason: "합성 건너뜀" }, ...mutation }],
      ["unskipObligation", { obligationId: id, input: { reason: "합성 복원" }, ...mutation }],
      ["completeObligation", { obligationId: id, input: { reason: "합성 완료" }, ...mutation }],
      ["reopenObligation", { obligationId: id, input: { reason: "합성 재개" }, ...mutation }],
      ["settleObligation", { obligationId: id, input: { amount_krw: "1000000", principal_krw: "700000", interest_krw: "300000", occurred_on: "2026-01-31", card_id: valueId }, ...mutation }],
      ["listObligationSettlements", { obligationId: id, query: { limit: 200, cursor: valueId } }],
      ["voidFixedSettlement", { settlementId: id, input: { reason: "합성 납부 취소" }, ...mutation }],
      ["getCardPaymentLinks", { resourceId: id, query: { as_of_date: "2026-01-31", rule_cursor: valueId, limit: 200 } }],
      ["getAccountPaymentLinks", { resourceId: id, query: { as_of_date: "2026-01-31", card_cursor: valueId, obligation_cursor: valueId, limit: 200 } }],
    ];
    const values = [];
    for (const [method, args] of cases) values.push(await nativeFinance[method](args));
    const state = (window as unknown as { __cashflowBridge: { calls: { method: string; args: unknown }[]; http: number } }).__cashflowBridge;
    return { values, calls: state.calls, expected: cases.map(([method, args]) => ({ method, args })), http: state.http, storage: localStorage.length + sessionStorage.length };
  }, { id, valueId });
  expect(result.calls).toEqual(result.expected);
  expect(result.values).toEqual(methods.map((marker) => marker === "deleteCard" ? null : ({ marker, amount_krw: "99999999999999999999", missing: null, zero: "0" })));
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


test("asset and card closure commands preserve explicit confirmation and digest", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async ({ id }) => {
    const source = "/src/platform/nativeFinance.ts";
    const { nativeFinance } = await import(source);
    const input = { ended_on: "2026-01-31", closure_ack: true, usage_digest: "b".repeat(64) };
    await nativeFinance.updateAsset(id, input, '\"7\"');
    await nativeFinance.archiveAsset(id, input, '\"7\"');
    await nativeFinance.updateCard({ cardId: id, input, ifMatch: '\"7\"' });
    await nativeFinance.archiveCard({ cardId: id, input, ifMatch: '\"7\"' });
    const state = (window as unknown as { __cashflowBridge: { calls: { method: string; args: unknown }[]; http: number } }).__cashflowBridge;
    return { ...state, input };
  }, { id });
  expect(result.calls).toEqual([
    { method: "updateAsset", args: { assetId: id, input: result.input, ifMatch: '\"7\"' } },
    { method: "archiveAsset", args: { assetId: id, input: result.input, ifMatch: '\"7\"' } },
    { method: "updateCard", args: { cardId: id, input: result.input, ifMatch: '\"7\"' } },
    { method: "archiveCard", args: { cardId: id, input: result.input, ifMatch: '\"7\"' } },
  ]);
  expect(result.http).toBe(0);
});
