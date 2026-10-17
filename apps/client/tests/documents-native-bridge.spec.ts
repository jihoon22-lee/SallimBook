import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.use({ trace: "off", screenshot: "off", video: "off" });
const id = "00000000-0000-4000-8000-000000000010";
const linkId = "00000000-0000-4000-8000-000000000020";
const methods = ["listDocuments", "getDocument", "deleteDocument", "createDocumentLink", "listDocumentLinks", "endDocumentLink", "uploadDocumentUI", "downloadDocumentUI"];
async function setup(page: Page, scenario = "success") {
  await page.route("**/__documents-bridge", (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic documents bridge</title>" }));
  await page.addInitScript(({ methods, scenario, id }) => {
    const state = { calls: [] as { method: string; args: unknown }[], http: 0 };
    Object.assign(window, { __documentsBridge: state, CapacitorCustomPlatform: { name: "android" }, Capacitor: {
      PluginHeaders: scenario === "unavailable" ? [] : [{ name: "SallimBookAuth", methods: methods.map((name) => ({ name, rtype: "promise" })) }],
      nativePromise: async (_plugin: string, method: string, args: unknown) => {
        state.calls.push({ method, args });
        if (scenario === "throws") throw new Error("synthetic private provider detail");
        const errors: Record<string, string> = { locked: "APP_LOCKED", expired: "SESSION_EXPIRED", cancelled: "AUTH_CANCELLED", network: "NETWORK_UNAVAILABLE", invalid: "INVALID_REQUEST", denied: "ACCESS_DENIED" };
        if (errors[scenario]) return { ok: false, code: errors[scenario], message: "synthetic private provider detail" };
        if (method.endsWith("UI")) return { ok: true, value: { status: scenario === "picker-cancelled" ? "cancelled" : method === "uploadDocumentUI" ? "uploaded" : "downloaded" } };
        if (scenario === "conflict") return { ok: true, value: { status: 409, body: { error: { code: "DOCUMENT_ALREADY_LINKED", message: "synthetic private provider detail" } } } };
        return { ok: true, value: { status: method === "createDocumentLink" ? 201 : 200, body: { id, version: 1 } } };
      },
    } });
    const original = window.fetch;
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (new URL(url, location.href).pathname.startsWith("/api/")) state.http++;
      return original.call(window, input, init);
    };
  }, { methods, scenario, id });
  await page.goto("/__documents-bridge");
}

test("six document metadata commands preserve target and version ownership without web HTTP", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async ({ id, linkId }) => {
    const source = "/src/platform/nativeFinance.ts"; const { nativeFinance } = await import(source);
    const cases: [string, Record<string, unknown>][] = [
      ["listDocuments", { query: { target_kind: "case", target_id: id, cursor: null, limit: 200 } }],
      ["getDocument", { documentId: id }],
      ["deleteDocument", { documentId: id, input: { reason: "합성 삭제" }, ifMatch: '"7"', idempotencyKey: "synthetic:delete" }],
      ["createDocumentLink", { input: { document_id: id, target: { kind: "expense", id: linkId } }, ifMatch: '"7"', idempotencyKey: "synthetic:link" }],
      ["listDocumentLinks", { documentId: id, query: { limit: 200 } }],
      ["endDocumentLink", { linkId, input: { reason: "합성 연결 해제" }, ifMatch: '"3"', idempotencyKey: "synthetic:end" }],
    ];
    const values = [];
    for (const [method, args] of cases) values.push(await nativeFinance[method](args));
    const state = (window as unknown as { __documentsBridge: { calls: unknown[]; http: number } }).__documentsBridge;
    return { calls: state.calls, expected: cases.map(([method, args]) => ({ method, args })), values, http: state.http,
      storage: localStorage.length + sessionStorage.length, create: typeof nativeFinance.createDocument, content: typeof nativeFinance.uploadDocumentContent };
  }, { id, linkId });
  expect(result.calls).toEqual(result.expected); expect(result.calls).toHaveLength(6);
  expect(result.values).toHaveLength(6); expect(result.values[2]).toEqual({ id, version: 1 });
  expect(result.create).toBe("undefined"); expect(result.content).toBe("undefined");
  expect(result.http).toBe(0); expect(result.storage).toBe(0);
});

test("native file screens receive targets only and return completion status only", async ({ page }) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeFinance.ts"; const { nativeFinance } = await import(source);
    const upload = await nativeFinance.uploadDocument({ target: { kind: "case", id } });
    const download = await nativeFinance.downloadDocument({ documentId: id });
    const state = (window as unknown as { __documentsBridge: { calls: unknown[]; http: number } }).__documentsBridge;
    return { upload, download, calls: state.calls, http: state.http, storage: localStorage.length + sessionStorage.length };
  }, id);
  expect(result.upload).toEqual({ status: "uploaded" }); expect(result.download).toEqual({ status: "downloaded" });
  expect(result.calls).toEqual([
    { method: "uploadDocumentUI", args: { target: { kind: "case", id } } },
    { method: "downloadDocumentUI", args: { documentId: id } },
  ]);
  expect(result.http).toBe(0); expect(result.storage).toBe(0);
});

test("picker cancellation produces no metadata creation or content retry", async ({ page }) => {
  await setup(page, "picker-cancelled");
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeFinance.ts"; const { nativeFinance } = await import(source);
    const value = await nativeFinance.uploadDocument({ target: { kind: "appliance", id } });
    const state = (window as unknown as { __documentsBridge: { calls: unknown[]; http: number } }).__documentsBridge;
    return { value, count: state.calls.length, http: state.http };
  }, id);
  expect(result).toEqual({ value: { status: "cancelled" }, count: 1, http: 0 });
});

for (const [scenario, expected] of [["locked", "APP_LOCKED"], ["expired", "UNAUTHENTICATED"], ["cancelled", "REQUEST_CANCELLED"],
  ["network", "NETWORK_UNAVAILABLE"], ["invalid", "VALIDATION_ERROR"], ["denied", "FORBIDDEN"], ["throws", "NATIVE_AUTH_UNAVAILABLE"],
  ["unavailable", "NATIVE_AUTH_UNAVAILABLE"], ["conflict", "DOCUMENT_ALREADY_LINKED"]]) {
  test(`document operations fail without web fallback or automatic retries: ${scenario}`, async ({ page }) => {
    await setup(page, scenario);
    const result = await page.evaluate(async ({ id, scenario }) => {
      const source = "/src/platform/nativeFinance.ts"; const { nativeFinance } = await import(source);
      let code = "", message = "";
      try {
        if (scenario === "conflict") await nativeFinance.createDocumentLink({ input: { document_id: id, target: { kind: "case", id } }, ifMatch: '"7"', idempotencyKey: "synthetic:link" });
        else await nativeFinance.downloadDocument({ documentId: id });
      } catch (error) { code = (error as { code: string }).code; message = String(error); }
      const state = (window as unknown as { __documentsBridge: { calls: unknown[]; http: number } }).__documentsBridge;
      return { code, message, count: state.calls.length, http: state.http, storage: localStorage.length + sessionStorage.length };
    }, { id, scenario });
    expect(result.code).toBe(expected); expect(result.message).not.toContain("private provider detail");
    expect(result.count).toBe(scenario === "unavailable" ? 0 : 1);
    expect(result.http).toBe(0); expect(result.storage).toBe(0);
  });
}
