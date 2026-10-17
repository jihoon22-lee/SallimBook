import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.use({ trace: "off", screenshot: "off", video: "off" });
const applianceId = "00000000-0000-4000-8000-000000000010";
const consumableId = "00000000-0000-4000-8000-000000000020";
const linkId = "00000000-0000-4000-8000-000000000030";
const movementId = "00000000-0000-4000-8000-000000000040";
const replacementId = "00000000-0000-4000-8000-000000000050";
const methods = ["listAppliances", "createAppliance", "getAppliance", "updateAppliance", "listConsumables", "createConsumable",
  "getConsumable", "updateConsumable", "listApplianceConsumables", "createApplianceConsumable", "getApplianceConsumable",
  "updateApplianceConsumable", "listStockMovements", "createStockMovement", "getStockMovement", "cancelStockMovement",
  "listConsumableReplacements", "createConsumableReplacement", "getConsumableReplacement", "cancelConsumableReplacement", "getHomecareStatus",
  "deleteAppliance", "deleteConsumable", "deleteApplianceConsumable"];

async function setup(page: Page, scenario = "success") {
  await page.route("**/__homecare-bridge", (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic homecare bridge test</title>" }));
  await page.addInitScript(({ methods, scenario, consumableId, movementId, replacementId }) => {
    const state = { calls: [] as { method: string; args: unknown }[], http: 0 };
    Object.assign(window, { __homecareBridge: state, CapacitorCustomPlatform: { name: "android" }, Capacitor: {
      PluginHeaders: scenario === "unavailable" ? [] : [{ name: "SallimBookAuth", methods: methods.map((name) => ({ name, rtype: "promise" })) }],
      nativePromise: async (_plugin: string, method: string, args: unknown) => {
        state.calls.push({ method, args });
        if (scenario === "throws") throw new Error("synthetic native private detail");
        const failures: Record<string, string> = { cancelled: "AUTH_CANCELLED", locked: "APP_LOCKED", expired: "SESSION_EXPIRED", network: "NETWORK_UNAVAILABLE", invalid: "INVALID_REQUEST", denied: "ACCESS_DENIED" };
        if (failures[scenario]) return { ok: false, code: failures[scenario] };
        if (scenario === "conflict") return { ok: true, value: { status: 409, body: { error: { code: "INSUFFICIENT_STOCK", message: "synthetic private detail", note: "synthetic private detail" } } } };
        if (method.startsWith("delete")) return { ok: true, value: { status: 204, body: null } };
        const stockMutation = ["createStockMovement", "cancelStockMovement", "createConsumableReplacement", "cancelConsumableReplacement"].includes(method);
        const body = stockMutation ? { id: movementId, consumable_id: consumableId, stock_version: 2,
          replacement_id: method === "createConsumableReplacement" ? replacementId : null } : {
          marker: method, quantity: 1_000_000, purchase_price_krw: "99999999999999999999", missing: null, zero: "0",
        };
        return { ok: true, value: { status: method.startsWith("create") ? 201 : 200, body } };
      },
    } });
    const original = window.fetch;
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (new URL(url, location.href).pathname.startsWith("/api/")) state.http++;
      return original.call(window, input, init);
    };
  }, { methods, scenario, consumableId, movementId, replacementId });
  await page.goto("/__homecare-bridge");
}

test("24 homecare commands preserve typed values and independent stock and link versions", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async ({ applianceId, consumableId, linkId, movementId, replacementId }) => {
    const source = "/src/platform/nativeFinance.ts";
    const { nativeFinance } = await import(source);
    const stock = { ifMatch: '"7"', idempotencyKey: "synthetic:homecare:1" };
    const cancel = { occurred_on: "2026-02-28", reason: "합성 취소" };
    const cases: [string, Record<string, unknown>][] = [
      ["listAppliances", { query: { status: "all", limit: 200, cursor: null } }],
      ["createAppliance", { input: { name: "합성 가전", purchase_price_krw: "99999999999999999999", warranty_until: null } }],
      ["getAppliance", { applianceId }],
      ["updateAppliance", { applianceId, input: { ended_on: "2026-02-28" }, ifMatch: '"3"' }],
      ["listConsumables", { query: { status: "active", limit: 200 } }],
      ["createConsumable", { input: { name: "합성 필터", sku_or_model: null, unit: "개", low_stock_threshold: 0 } }],
      ["getConsumable", { consumableId }],
      ["updateConsumable", { consumableId, input: { low_stock_threshold: 1_000_000 }, ifMatch: '"7"' }],
      ["listApplianceConsumables", { query: { appliance_id: applianceId, consumable_id: consumableId, active: false } }],
      ["createApplianceConsumable", { input: { appliance_id: applianceId, consumable_id: consumableId, interval_unit: "manual", interval_count: null } }],
      ["getApplianceConsumable", { linkId }],
      ["updateApplianceConsumable", { linkId, input: { next_check_override: null }, ifMatch: '"3"' }],
      ["listStockMovements", { consumableId, query: { limit: 200, cursor: null } }],
      ["createStockMovement", { consumableId, input: { kind: "receipt", quantity_delta: 3, occurred_on: "2026-01-31", unit_cost_krw: "0", purchase_url: "https://synthetic.invalid/item" }, ...stock }],
      ["getStockMovement", { consumableId, movementId }],
      ["cancelStockMovement", { consumableId, movementId, input: cancel, ...stock }],
      ["listConsumableReplacements", { linkId, query: { limit: 200 } }],
      ["createConsumableReplacement", { linkId, input: { replaced_on: "2026-01-31", quantity: 1, link_version: 3, clear_next_check_override: false }, ...stock }],
      ["getConsumableReplacement", { linkId, replacementId }],
      ["cancelConsumableReplacement", { linkId, replacementId, input: cancel, ...stock }],
      ["getHomecareStatus", { query: { appliance_id: applianceId, consumable_id: consumableId, limit: 200 } }],
      ["deleteAppliance", { applianceId, ifMatch: '"3"' }],
      ["deleteConsumable", { consumableId, ifMatch: '"7"' }],
      ["deleteApplianceConsumable", { linkId, ifMatch: '"3"' }],
    ];
    const values: unknown[] = [];
    for (const [method, args] of cases) values.push(await nativeFinance[method](args));
    const state = (window as unknown as { __homecareBridge: { calls: unknown[]; http: number } }).__homecareBridge;
    return { calls: state.calls, expected: cases.map(([method, args]) => ({ method, args })), values,
      http: state.http, storage: localStorage.length + sessionStorage.length };
  }, { applianceId, consumableId, linkId, movementId, replacementId });
  expect(result.calls).toEqual(result.expected);
  expect(result.calls).toHaveLength(24);
  expect(result.values[0]).toMatchObject({ quantity: 1_000_000, purchase_price_krw: "99999999999999999999", missing: null, zero: "0" });
  expect(result.values[13]).toEqual({ id: movementId, consumable_id: consumableId, stock_version: 2, replacement_id: null });
  expect(result.values[17]).toEqual({ id: movementId, consumable_id: consumableId, stock_version: 2, replacement_id: replacementId });
  expect(result.values.slice(21)).toEqual([null, null, null]);
  expect(result.http).toBe(0); expect(result.storage).toBe(0);
});

test("a replay receipt never becomes a newer stock snapshot or gains implicit retries", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async ({ linkId }) => {
    const source = "/src/platform/nativeFinance.ts"; const { nativeFinance } = await import(source);
    const args = { linkId, input: { replaced_on: "2026-01-31", quantity: 1, link_version: 3, clear_next_check_override: true }, ifMatch: '"7"', idempotencyKey: "synthetic:replay:1" };
    const first = await nativeFinance.createConsumableReplacement(args);
    const replay = await nativeFinance.createConsumableReplacement(args);
    const state = (window as unknown as { __homecareBridge: { calls: unknown[]; http: number } }).__homecareBridge;
    return { first, replay, calls: state.calls, http: state.http, storage: localStorage.length + sessionStorage.length };
  }, { linkId });
  expect(result.first).toEqual(result.replay);
  expect(result.replay.stock_version).toBe(2);
  expect(result.calls).toHaveLength(2);
  expect(result.calls[0]).toEqual(result.calls[1]);
  expect(result.http).toBe(0); expect(result.storage).toBe(0);
});

for (const [scenario, expected] of [["cancelled", "REQUEST_CANCELLED"], ["locked", "APP_LOCKED"], ["expired", "UNAUTHENTICATED"],
  ["network", "NETWORK_UNAVAILABLE"], ["invalid", "VALIDATION_ERROR"], ["denied", "FORBIDDEN"],
  ["conflict", "INSUFFICIENT_STOCK"], ["unavailable", "NATIVE_AUTH_UNAVAILABLE"], ["throws", "NATIVE_AUTH_UNAVAILABLE"]]) {
  test(`homecare fails without web fallback or automatic retry: ${scenario}`, async ({ page }) => {
    await setup(page, scenario);
    const result = await page.evaluate(async ({ consumableId }) => {
      const source = "/src/platform/nativeFinance.ts"; const { nativeFinance } = await import(source);
      let code = "", message = "";
      try { await nativeFinance.createStockMovement({ consumableId, input: { kind: "receipt", quantity_delta: 1, occurred_on: "2026-02-28" }, ifMatch: '"7"', idempotencyKey: "synthetic:1" }); }
      catch (error) { code = (error as { code: string }).code; message = String(error); }
      const state = (window as unknown as { __homecareBridge: { calls: unknown[]; http: number } }).__homecareBridge;
      return { code, message, calls: state.calls.length, http: state.http, storage: localStorage.length + sessionStorage.length };
    }, { consumableId });
    expect(result.code).toBe(expected);
    expect(result.calls).toBe(scenario === "unavailable" ? 0 : 1);
    expect(result.http).toBe(0); expect(result.storage).toBe(0);
    expect(result.message).not.toContain("private detail");
  });
}
