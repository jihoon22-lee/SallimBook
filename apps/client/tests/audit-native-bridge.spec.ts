import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.use({ trace: "off", screenshot: "off", video: "off" });
const id = "00000000-0000-4000-8000-000000000001";
async function setup(page: Page, scenario = "success") {
  await page.route("**/__audit-bridge", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><title>Synthetic audit bridge</title>",
    }),
  );
  await page.addInitScript(
    ({ scenario, id }) => {
      const state = { calls: [] as { method: string; args: unknown }[], http: 0 };
      Object.assign(window, {
        __auditBridge: state,
        CapacitorCustomPlatform: { name: "android" },
        Capacitor: {
          PluginHeaders:
            scenario === "unavailable"
              ? []
              : [
                  {
                    name: "SallimBookAuth",
                    methods: [{ name: "listAuditEvents", rtype: "promise" }],
                  },
                ],
          nativePromise: async (_plugin: string, method: string, args: unknown) => {
            state.calls.push({ method, args });
            if (scenario === "throws") throw new Error("synthetic private detail");
            const errors: Record<string, string> = {
              locked: "APP_LOCKED",
              expired: "SESSION_EXPIRED",
              cancelled: "AUTH_CANCELLED",
              denied: "ACCESS_DENIED",
              invalid: "INVALID_REQUEST",
              network: "NETWORK_UNAVAILABLE",
              key: "KEY_INVALIDATED",
            };
            if (errors[scenario])
              return { ok: false, code: errors[scenario], message: "synthetic private detail" };
            const metadataErrors: Record<string, [number, string]> = {
              cursor: [400, "INVALID_CURSOR"],
              filter: [422, "INVALID_AUDIT_FILTER"],
              metadata: [503, "AUDIT_METADATA_INVALID"],
              unknown: [503, "synthetic private detail"],
            };
            const error = metadataErrors[scenario];
            if (error)
              return {
                ok: true,
                value: {
                  status: error[0],
                  body: {
                    error: {
                      code: error[1],
                      message: "synthetic private detail",
                      submitted: "synthetic private detail",
                    },
                  },
                },
              };
            const item = {
              id,
              actor_member_id: id,
              entity_type: "asset",
              entity_id: id,
              action: "update",
              request_id: "synthetic-1",
              before_version: 1,
              after_version: 2,
              occurred_at: "2026-10-18T00:00:00Z",
              changed_fields: ["name"],
            };
            const body: Record<string, unknown> = { items: [item], next_cursor: null };
            if (scenario === "extra") body.safe_diff = { name: "synthetic private detail" };
            if (scenario === "too-many") body.items = [item, item];
            if (scenario === "unsafe-cursor")
              body.next_cursor = "https://synthetic.invalid/private";
            if (scenario === "missing") delete body.items;
            return { ok: true, value: { status: 200, body } };
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
    { scenario, id },
  );
  await page.goto("/__audit-bridge");
}

test("generated audit filters cross only the dedicated native command without storage or HTTP", async ({
  page,
}) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeAudit.ts";
    const { nativeAudit } = await import(source);
    const query = {
      limit: 200,
      cursor: null,
      entity_type: "asset",
      entity_id: id,
      actor_member_id: id,
      action: "update",
      since: "2026-10-17T00:00:00+09:00",
      until: "2026-10-19T00:00:00Z",
    };
    const first = await nativeAudit.list();
    const filtered = await nativeAudit.list({ query });
    return {
      first,
      filtered,
      query,
      methods: Object.keys(nativeAudit),
      ...(window as unknown as { __auditBridge: object }).__auditBridge,
      storage: localStorage.length + sessionStorage.length,
    };
  }, id);
  expect(result.methods).toEqual(["list"]);
  expect(result.first).toEqual(result.filtered);
  expect(result.first.items[0]).toMatchObject({ action: "update", changed_fields: ["name"] });
  expect(result).toMatchObject({
    calls: [
      { method: "listAuditEvents", args: {} },
      { method: "listAuditEvents", args: { query: result.query } },
    ],
    http: 0,
    storage: 0,
  });
});

test("URLs raw diffs headers scope flags and malformed filters are rejected before any native call", async ({
  page,
}) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeAudit.ts";
    const { nativeAudit } = await import(source);
    const attempts: unknown[] = [];
    for (const field of [
      "url",
      "path",
      "headers",
      "body",
      "household_id",
      "safe_diff",
      "password",
      "token",
      "biometricSuccess",
      "ifMatch",
    ])
      attempts.push({ [field]: "synthetic" }, { query: { [field]: "synthetic" } });
    attempts.push(
      null,
      [],
      { query: null },
      { query: [] },
      { query: { limit: 0 } },
      { query: { limit: 201 } },
      { query: { limit: 1.5 } },
      { query: { limit: "50" } },
      { query: { cursor: "https://synthetic.invalid" } },
      { query: { cursor: "a".repeat(1025) } },
      { query: { entity_id: "../synthetic" } },
      { query: { actor_member_id: 1 } },
      { query: { entity_type: "a".repeat(41) } },
      { query: { action: "bad/action" } },
      { query: { since: "2026-10-18" } },
      { query: { until: "2026-10-18T00:00:00" } },
      { query: { since: true } },
      { query: { limit: null } },
      { query: { entity_id: id }, headers: {} },
    );
    const codes = [];
    for (const options of attempts) {
      try {
        await nativeAudit.list(options);
        codes.push("accepted");
      } catch (e) {
        codes.push((e as { code: string }).code);
      }
    }
    return { codes, ...(window as unknown as { __auditBridge: object }).__auditBridge };
  }, id);
  expect(result.codes).toHaveLength(39);
  expect(result.codes.every((code: string) => code === "VALIDATION_ERROR")).toBe(true);
  expect(result).toMatchObject({ calls: [], http: 0 });
});

for (const [scenario, status, code] of [
  ["locked", 0, "APP_LOCKED"],
  ["expired", 401, "UNAUTHENTICATED"],
  ["cancelled", 0, "REQUEST_CANCELLED"],
  ["denied", 403, "FORBIDDEN"],
  ["invalid", 422, "VALIDATION_ERROR"],
  ["network", 0, "NETWORK_UNAVAILABLE"],
  ["key", 401, "NATIVE_KEY_INVALIDATED"],
  ["cursor", 400, "INVALID_CURSOR"],
  ["filter", 422, "INVALID_AUDIT_FILTER"],
  ["metadata", 503, "AUDIT_METADATA_INVALID"],
  ["unknown", 503, "REQUEST_FAILED"],
  ["throws", 0, "NATIVE_AUTH_UNAVAILABLE"],
  ["unavailable", 0, "NATIVE_AUTH_UNAVAILABLE"],
  ["extra", 403, "FORBIDDEN"],
  ["too-many", 403, "FORBIDDEN"],
  ["unsafe-cursor", 403, "FORBIDDEN"],
  ["missing", 403, "FORBIDDEN"],
] as const) {
  test(`audit failures discard private details without retry or web fallback: ${scenario}`, async ({
    page,
  }) => {
    await setup(page, scenario);
    const result = await page.evaluate(async () => {
      const source = "/src/platform/nativeAudit.ts";
      const { nativeAudit } = await import(source);
      let error: { status?: number; code?: string; message?: string } = {};
      try {
        await nativeAudit.list({ query: { limit: 1 } });
      } catch (e) {
        const typed = e as { status: number; code: string };
        error = { status: typed.status, code: typed.code, message: String(e) };
      }
      return {
        error,
        ...(window as unknown as { __auditBridge: { calls: unknown[]; http: number } })
          .__auditBridge,
        storage: localStorage.length + sessionStorage.length,
      };
    });
    expect(result.error).toMatchObject({ status, code });
    expect(result.error.message).not.toContain("synthetic private");
    expect(result.calls).toHaveLength(scenario === "unavailable" ? 0 : 1);
    expect(result.http).toBe(0);
    expect(result.storage).toBe(0);
  });
}
