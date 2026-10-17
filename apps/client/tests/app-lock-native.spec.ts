import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { members, sampleAccount, uid } from "./support/finance";

// This simulates status dispatch and cache disposal, never OS authentication or Android enforcement.
test.use({ trace: "off", screenshot: "off", video: "off" });

async function install(page: Page, locked: boolean) {
  await page.addInitScript(({ account, member, locked }) => {
    const listeners = new Map<string, (event: { locked: boolean }) => void>();
    let next = 0;
    const state = {
      locked, calls: [] as { method: string; args: Record<string, unknown> }[], http: 0,
      emit(value: boolean, changeNativeState = true) {
        if (changeNativeState) this.locked = value;
        listeners.forEach((listener) => listener({ locked: value }));
      },
    };
    Object.assign(window, { __appLock: state, CapacitorCustomPlatform: { name: "android" }, Capacitor: {
      PluginHeaders: [{ name: "SallimBookAuth", methods: [
        ...["getSession", "request", "getAccount", "getAsset", "listAssets", "updateAccount", "lockApp", "getAppLock", "removeListener"].map((name) => ({ name, rtype: "promise" })),
        { name: "addListener", rtype: "callback" },
      ] }],
      nativeCallback: (_plugin: string, _method: string, _args: unknown, listener: (event: { locked: boolean }) => void) => {
        const id = String(++next); listeners.set(id, listener); return id;
      },
      nativePromise: async (_plugin: string, method: string, args: Record<string, unknown> = {}) => {
        if (method === "removeListener") { listeners.delete(String(args.callbackId)); return; }
        state.calls.push({ method, args });
        const ok = (value: unknown) => ({ ok: true, value });
        if (method === "lockApp") { state.emit(true); return ok({ locked: true }); }
        if (method === "getAppLock") return ok({ locked: state.locked });
        if (state.locked) return { ok: false, code: "APP_LOCKED" };
        if (method === "getSession") return ok({ available: true, authenticated: true });
        if (method === "request" && args.path === "/api/v1/me") return ok({ status: 200, body: member });
        if (method === "getAccount") return ok({ status: 200, body: account });
        if (method === "getAsset") return ok({ status: 200, body: account.asset });
        if (method === "listAssets") return ok({ status: 200, body: { items: [account.asset], next_cursor: null } });
        return { ok: false, code: "INVALID_REQUEST" };
      },
    } });
    const fetch = window.fetch;
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (new URL(url, location.href).pathname.startsWith("/api/")) state.http++;
      return fetch.call(window, input, init);
    };
  }, { account: sampleAccount, member: members[0], locked });
}
async function emit(page: Page, locked: boolean, changeNativeState = true) {
  await page.evaluate(({ locked, changeNativeState }) => {
    (window as unknown as { __appLock: { emit(locked: boolean, change: boolean): void } }).__appLock.emit(locked, changeNativeState);
  }, { locked, changeNativeState });
}
async function snapshot(page: Page) {
  return page.evaluate(() => {
    const state = (window as unknown as { __appLock: { calls: { method: string; args: Record<string, unknown> }[]; http: number } }).__appLock;
    return { calls: state.calls, http: state.http, stored: localStorage.length + sessionStorage.length };
  });
}

test("cold locked startup does not load account metadata or fall back to web HTTP", async ({ page }) => {
  await install(page, true); await page.goto(`/accounts/${uid(30)}`);
  await expect(page.getByRole("status")).toContainText("앱이 잠겨 있어요");
  const state = await snapshot(page);
  expect(state.calls.every((call) => call.method === "getSession")).toBe(true);
  expect(state.http).toBe(0); expect(state.stored).toBe(0);
  await expect(page.getByText(sampleAccount.masked_number!)).toHaveCount(0);
});

test("native lock event discards an edited form and a forged unlocked event grants no access", async ({ page }) => {
  await install(page, false); await page.goto(`/accounts/${uid(30)}/edit`);
  await page.getByLabel("용도 (선택)", { exact: true }).fill("discard this synthetic unsaved draft");
  await emit(page, true);
  await expect(page.getByRole("status")).toContainText("앱이 잠겨 있어요");
  await expect(page.locator("input")).toHaveCount(0);
  const before = (await snapshot(page)).calls.filter((call) => call.method === "getAccount").length;
  await emit(page, false, false);
  await expect(page.getByRole("status")).toContainText("앱이 잠겨 있어요");
  expect((await snapshot(page)).calls.filter((call) => call.method === "getAccount")).toHaveLength(before);
  await emit(page, false);
  await expect(page.getByLabel("용도 (선택)", { exact: true })).not.toHaveValue("discard this synthetic unsaved draft");
  expect((await snapshot(page)).calls.filter((call) => call.method === "getAccount").length).toBeGreaterThan(before);
  expect((await snapshot(page)).http).toBe(0); expect((await snapshot(page)).stored).toBe(0);
});

test("manual lock is a parameterless native command and immediately unmounts protected data", async ({ page }) => {
  await install(page, false); await page.goto(`/accounts/${uid(30)}`);
  await expect(page.getByText(sampleAccount.masked_number!, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "앱 잠금", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("앱이 잠겨 있어요");
  await expect(page.getByText(sampleAccount.masked_number!, { exact: true })).toHaveCount(0);
  expect((await snapshot(page)).calls.filter((call) => call.method === "lockApp")).toEqual([{ method: "lockApp", args: {} }]);
});
