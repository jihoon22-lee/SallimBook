import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.use({ trace: "off", screenshot: "off", video: "off" });
const id = "00000000-0000-4000-8000-000000000001";
const methods = ["openVaultUI", "getVaultStatus", "listVaultShares", "getVaultRotation"];
async function setup(page: Page, scenario = "success") {
  await page.route("**/__vault-bridge", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><title>Synthetic native vault bridge</title>",
    }),
  );
  await page.addInitScript(
    ({ methods, scenario, id }) => {
      const state = { calls: [] as { method: string; args: unknown }[], http: 0 };
      Object.assign(window, {
        __vaultBridge: state,
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
            if (scenario === "throws") throw new Error("synthetic private native detail");
            const failures: Record<string, string> = {
              cancelled: "AUTH_CANCELLED",
              locked: "APP_LOCKED",
              expired: "SESSION_EXPIRED",
              network: "NETWORK_UNAVAILABLE",
              invalid: "INVALID_REQUEST",
              denied: "ACCESS_DENIED",
              key: "KEY_INVALIDATED",
            };
            if (failures[scenario])
              return {
                ok: false,
                code: failures[scenario],
                message: "synthetic private native detail",
              };
            const metadataFailures: Record<string, { status: number; code: string }> = {
              "missing-rotation": { status: 404, code: "NOT_FOUND" },
              "stale-rotation": { status: 409, code: "VAULT_ROTATION_UNAVAILABLE" },
              reauthentication: { status: 403, code: "REAUTHENTICATION_REQUIRED" },
              "unknown-error": { status: 503, code: "synthetic private unknown code" },
            };
            const failure = metadataFailures[scenario];
            if (failure)
              return {
                ok: true,
                value: {
                  status: failure.status,
                  body: {
                    error: { code: failure.code, message: "synthetic private native detail" },
                  },
                },
              };
            if (method === "openVaultUI")
              return {
                ok: true,
                value:
                  scenario === "extra-result"
                    ? { status: "completed", ciphertext: "synthetic opaque" }
                    : { status: scenario === "ui-cancelled" ? "cancelled" : "completed" },
              };
            const body =
              method === "getVaultStatus"
                ? {
                    household_id: id,
                    initialized: false,
                    id: null,
                    version: null,
                    current_key_version: null,
                    own_membership: "not_enrolled",
                    rotation_required: false,
                    pending_rotation_id: null,
                    members: [],
                  }
                : method === "listVaultShares"
                  ? { items: [], next_cursor: null }
                  : {
                      id,
                      household_id: id,
                      key_version: 2,
                      source_key_version: 1,
                      state: "staging",
                      version: 1,
                      key_check_prepared: false,
                      recovery_prepared: false,
                      cards: [],
                      members: [{ member_id: id, source_membership_version: 1, prepared: false }],
                    };
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
    { methods, scenario, id },
  );
  await page.goto("/__vault-bridge");
}

test("all native vault workflows accept only action and optional IDs and return status", async ({
  page,
}) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeVault.ts";
    const { nativeVault } = await import(source);
    const cases = [
      ...["manage", "setup", "register-device", "change-password", "recover", "rotate"].map(
        (action) => ({ action }),
      ),
      ...["view", "edit", "purge", "cvc-view", "cvc-edit", "cvc-delete"].map((action) => ({
        action,
        cardId: id,
      })),
      ...["share", "revoke-member"].map((action) => ({ action, memberId: id })),
      ...["accept-share", "cancel-share"].map((action) => ({ action, offerId: id })),
      ...["resume-rotation", "abort-rotation"].map((action) => ({ action, rotationId: id })),
    ];
    const results = [];
    for (const args of cases) results.push(await nativeVault.open(args));
    const state = (window as unknown as { __vaultBridge: { calls: unknown[]; http: number } })
      .__vaultBridge;
    return {
      results,
      expected: cases.map((args) => ({ method: "openVaultUI", args })),
      calls: state.calls,
      http: state.http,
      storage: localStorage.length + sessionStorage.length,
    };
  }, id);
  expect(result.calls).toEqual(result.expected);
  expect(result.calls).toHaveLength(18);
  expect(result.results).toEqual(Array.from({ length: 18 }, () => ({ status: "completed" })));
  expect(result.http).toBe(0);
  expect(result.storage).toBe(0);
});

test("three metadata readers retain generated safe status and manifest values", async ({
  page,
}) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeVault.ts";
    const { nativeVault } = await import(source);
    const status = await nativeVault.getVaultStatus();
    const shares = await nativeVault.listVaultShares({ query: { cursor: null, limit: 200 } });
    const rotation = await nativeVault.getVaultRotation({ rotationId: id });
    const state = (window as unknown as { __vaultBridge: { calls: unknown[]; http: number } })
      .__vaultBridge;
    return {
      status,
      shares,
      rotation,
      calls: state.calls,
      http: state.http,
      storage: localStorage.length + sessionStorage.length,
      methods: Object.keys(nativeVault).sort(),
    };
  }, id);
  expect(result.status).toMatchObject({ initialized: false, current_key_version: null });
  expect(result.shares).toEqual({ items: [], next_cursor: null });
  expect(result.rotation).toMatchObject({ key_version: 2, source_key_version: 1, cards: [] });
  expect(result.methods).toEqual(["getVaultRotation", "getVaultStatus", "listVaultShares", "open"]);
  expect(result.calls).toEqual([
    { method: "getVaultStatus" },
    { method: "listVaultShares", args: { query: { cursor: null, limit: 200 } } },
    { method: "getVaultRotation", args: { rotationId: id } },
  ]);
  expect(result.http).toBe(0);
  expect(result.storage).toBe(0);
});

for (const [scenario, status, code] of [
  ["missing-rotation", 404, "NOT_FOUND"],
  ["stale-rotation", 409, "VAULT_ROTATION_UNAVAILABLE"],
  ["reauthentication", 403, "REAUTHENTICATION_REQUIRED"],
  ["unknown-error", 503, "REQUEST_FAILED"],
] as const) {
  test(`native metadata keeps safe error identity: ${scenario}`, async ({ page }) => {
    await setup(page, scenario);
    const result = await page.evaluate(async (id) => {
      const source = "/src/platform/nativeVault.ts";
      const { nativeVault } = await import(source);
      const errors = [];
      for (const operation of [
        () => nativeVault.getVaultStatus(),
        () => nativeVault.listVaultShares(),
        () => nativeVault.getVaultRotation({ rotationId: id }),
      ]) {
        try {
          await operation();
        } catch (error) {
          const typed = error as { status: number; code: string };
          errors.push({ status: typed.status, code: typed.code, message: String(error) });
        }
      }
      const state = (window as unknown as { __vaultBridge: { calls: unknown[]; http: number } })
        .__vaultBridge;
      return {
        errors,
        calls: state.calls.length,
        http: state.http,
        storage: localStorage.length + sessionStorage.length,
      };
    }, id);
    expect(result.errors).toHaveLength(3);
    for (const error of result.errors) {
      expect(error).toMatchObject({ status, code });
      expect(error.message).not.toContain("synthetic private");
    }
    expect(result.calls).toBe(3);
    expect(result.http).toBe(0);
    expect(result.storage).toBe(0);
  });
}

test("plaintext opaque values flags URLs and extra arguments are rejected before bridge invocation", async ({
  page,
}) => {
  await setup(page);
  const result = await page.evaluate(async (id) => {
    const source = "/src/platform/nativeVault.ts";
    const { nativeVault } = await import(source);
    const attempts: (() => Promise<unknown>)[] = [];
    for (const field of [
      "password",
      "recoveryCode",
      "pan",
      "cvc",
      "ciphertext",
      "wrapped_hvk",
      "biometricSuccess",
      "url",
      "headers",
      "ifMatch",
    ]) {
      attempts.push(() => nativeVault.open({ action: "view", cardId: id, [field]: "synthetic" }));
      attempts.push(() => nativeVault.listVaultShares({ query: { [field]: "synthetic" } }));
    }
    attempts.push(
      () => nativeVault.open({ action: "decrypt", cardId: id }),
      () => nativeVault.open({ action: "view", cardId: "../synthetic" }),
      () => nativeVault.getVaultRotation({ rotationId: id, input: "synthetic" }),
      () => nativeVault.listVaultShares({ query: { limit: 201 } }),
    );
    const codes = [];
    for (const attempt of attempts) {
      try {
        await attempt();
        codes.push("accepted");
      } catch (e) {
        codes.push((e as { code: string }).code);
      }
    }
    const state = (window as unknown as { __vaultBridge: { calls: unknown[]; http: number } })
      .__vaultBridge;
    return {
      codes,
      calls: state.calls,
      http: state.http,
      storage: localStorage.length + sessionStorage.length,
    };
  }, id);
  expect(result.codes).toEqual(Array(24).fill("VALIDATION_ERROR"));
  expect(result.calls).toEqual([]);
  expect(result.http).toBe(0);
  expect(result.storage).toBe(0);
});

for (const scenario of [
  "cancelled",
  "locked",
  "expired",
  "network",
  "invalid",
  "denied",
  "key",
  "unavailable",
  "throws",
  "extra-result",
]) {
  test(`vault fails without web fallback or retry: ${scenario}`, async ({ page }) => {
    await setup(page, scenario);
    const result = await page.evaluate(async () => {
      const source = "/src/platform/nativeVault.ts";
      const { nativeVault } = await import(source);
      let code = "accepted";
      let message = "";
      try {
        await nativeVault.open({ action: "manage" });
      } catch (e) {
        code = (e as { code: string }).code;
        message = String(e);
      }
      const state = (window as unknown as { __vaultBridge: { calls: unknown[]; http: number } })
        .__vaultBridge;
      return {
        code,
        message,
        calls: state.calls.length,
        http: state.http,
        storage: localStorage.length + sessionStorage.length,
      };
    });
    expect(result.code).not.toBe("accepted");
    expect(result.message).not.toContain("synthetic private");
    expect(result.calls).toBe(scenario === "unavailable" ? 0 : 1);
    expect(result.http).toBe(0);
    expect(result.storage).toBe(0);
  });
}

test("native cancellation is a terminal status without another request", async ({ page }) => {
  await setup(page, "ui-cancelled");
  const result = await page.evaluate(async () => {
    const source = "/src/platform/nativeVault.ts";
    const { nativeVault } = await import(source);
    return nativeVault.open({ action: "manage" });
  });
  expect(result).toEqual({ status: "cancelled" });
});
