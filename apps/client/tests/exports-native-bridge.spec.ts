import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.use({ trace: "off", screenshot: "off", video: "off" });
const id = "00000000-0000-4000-8000-000000000001";
async function setup(page: Page, scenario = "success") {
  await page.route("**/__export-bridge", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><title>Synthetic native export bridge</title>",
    }),
  );
  await page.addInitScript(
    ({ scenario }) => {
      const state = { calls: [] as { method: string; args: unknown }[], http: 0 };
      Object.assign(window, {
        __exportBridge: state,
        CapacitorCustomPlatform: { name: "android" },
        Capacitor: {
          PluginHeaders:
            scenario === "unavailable"
              ? []
              : [
                  {
                    name: "SallimBookAuth",
                    methods: [{ name: "exportArchiveUI", rtype: "promise" }],
                  },
                ],
          nativePromise: async (_plugin: string, method: string, args: unknown) => {
            state.calls.push({ method, args });
            if (scenario === "throws") throw new Error("synthetic private native detail");
            const failures: Record<string, string> = {
              cancelled: "AUTH_CANCELLED",
              locked: "APP_LOCKED",
              expired: "SESSION_EXPIRED",
              network: "NETWORK_UNAVAILABLE",
              invalid: "INVALID_REQUEST",
              denied: "ACCESS_DENIED",
              reauth: "REAUTHENTICATION_REQUIRED",
              password: "AUTH_FAILED",
              key: "KEY_INVALIDATED",
            };
            if (failures[scenario])
              return {
                ok: false,
                code: failures[scenario],
                message: "synthetic private native detail",
              };
            if (scenario.startsWith("extra-"))
              return {
                ok: true,
                value: {
                  status: "exported",
                  [scenario.slice(6)]: "synthetic private native detail",
                },
              };
            return {
              ok: true,
              value: {
                status:
                  scenario === "ui-cancelled"
                    ? "cancelled"
                    : scenario === "wrong-status"
                      ? "downloaded"
                      : "exported",
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
    { scenario },
  );
  await page.goto("/__export-bridge");
}

test("export copies generated-schema selections and returns only native status", async ({
  page,
}) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeExports.ts";
    const { nativeExports } = await import(source);
    const defaults = await nativeExports.export({ input: {} });
    const input = { formats: ["json"], document_ids: [id] };
    const pending = nativeExports.export({ input });
    input.formats.push("csv");
    input.document_ids.length = 0;
    const selected = await pending;
    const state = (window as unknown as { __exportBridge: { calls: unknown[]; http: number } })
      .__exportBridge;
    return {
      defaults,
      selected,
      ...state,
      storage: localStorage.length + sessionStorage.length,
      methods: Object.keys(nativeExports),
    };
  }, id);
  expect(result.defaults).toEqual({ status: "exported" });
  expect(result.selected).toEqual({ status: "exported" });
  expect(result.calls).toEqual([
    { method: "exportArchiveUI", args: { input: { formats: ["json", "csv"], document_ids: [] } } },
    { method: "exportArchiveUI", args: { input: { formats: ["json"], document_ids: [id] } } },
  ]);
  expect(result.methods).toEqual(["export"]);
  expect(result.http).toBe(0);
  expect(result.storage).toBe(0);
});

test("invalid choices secret data paths URLs and headers are rejected before native invocation", async ({
  page,
}) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeExports.ts";
    const { nativeExports } = await import(source);
    const attempts: unknown[] = [
      null,
      [],
      { input: null },
      { input: new Date() },
      { input: { formats: [] } },
      { input: { formats: ["json", "json"] } },
      { input: { formats: ["zip"] } },
      { input: { formats: null } },
      { input: { document_ids: null } },
      { input: { document_ids: [id, id] } },
      { input: { document_ids: ["../synthetic"] } },
      { input: { document_ids: Array(11).fill(id) } },
    ];
    for (const field of [
      "password",
      "pan",
      "cvc",
      "token",
      "url",
      "headers",
      "uri",
      "path",
      "bytes",
      "household_id",
      "step_up_token",
    ]) {
      attempts.push({ input: {}, [field]: "synthetic" }, { input: { [field]: "synthetic" } });
    }
    const codes = [];
    for (const input of attempts) {
      try {
        await nativeExports.export(input);
        codes.push("accepted");
      } catch (error) {
        codes.push((error as { code: string }).code);
      }
    }
    const state = (window as unknown as { __exportBridge: { calls: unknown[]; http: number } })
      .__exportBridge;
    return { codes, ...state, storage: localStorage.length + sessionStorage.length };
  }, id);
  expect(result.codes).toEqual(Array(34).fill("VALIDATION_ERROR"));
  expect(result.calls).toEqual([]);
  expect(result.http).toBe(0);
  expect(result.storage).toBe(0);
});

for (const [scenario, expected] of Object.entries({
  cancelled: "REQUEST_CANCELLED",
  locked: "APP_LOCKED",
  expired: "UNAUTHENTICATED",
  network: "NETWORK_UNAVAILABLE",
  invalid: "VALIDATION_ERROR",
  denied: "FORBIDDEN",
  reauth: "REAUTHENTICATION_REQUIRED",
  password: "REAUTHENTICATION_FAILED",
  key: "NATIVE_KEY_INVALIDATED",
  unavailable: "NATIVE_AUTH_UNAVAILABLE",
  throws: "NATIVE_AUTH_UNAVAILABLE",
  "wrong-status": "FORBIDDEN",
  "extra-bytes": "FORBIDDEN",
  "extra-uri": "FORBIDDEN",
  "extra-url": "FORBIDDEN",
  "extra-token": "FORBIDDEN",
})) {
  test(`export fails without web fallback retry or private details: ${scenario}`, async ({
    page,
  }) => {
    await setup(page, scenario);
    const result = await page.evaluate(async () => {
      const source = "/src/platform/nativeExports.ts";
      const { nativeExports } = await import(source);
      let code = "accepted";
      let message = "";
      try {
        await nativeExports.export({ input: {} });
      } catch (error) {
        code = (error as { code: string }).code;
        message = String(error);
      }
      const state = (window as unknown as { __exportBridge: { calls: unknown[]; http: number } })
        .__exportBridge;
      return {
        code,
        message,
        calls: state.calls.length,
        http: state.http,
        storage: localStorage.length + sessionStorage.length,
      };
    });
    expect(result.code).toBe(expected);
    expect(result.message).not.toContain("synthetic private");
    expect(result.calls).toBe(scenario === "unavailable" ? 0 : 1);
    expect(result.http).toBe(0);
    expect(result.storage).toBe(0);
  });
}

test("explicit native picker cancellation remains a status-only outcome", async ({ page }) => {
  await setup(page, "ui-cancelled");
  const result = await page.evaluate(async () => {
    const source = "/src/platform/nativeExports.ts";
    const { nativeExports } = await import(source);
    return nativeExports.export({ input: { formats: ["csv"], document_ids: [] } });
  });
  expect(result).toEqual({ status: "cancelled" });
});
