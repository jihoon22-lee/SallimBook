import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

// Synthetic Capacitor bridge simulation: UI behavior only, never native security evidence.
test.use({ trace: "off", screenshot: "off", video: "off" });

type Scenario = { authenticated?: boolean; cancelled?: boolean; logoutUnconfirmed?: boolean; conflict?: boolean; passkey?: boolean; expiredRegistration?: boolean };
async function nativeMock(page: Page, scenario: Scenario = {}) {
  await page.addInitScript((initial) => {
    const state = { authenticated: Boolean(initial.authenticated), calls: [] as { method: string; args: Record<string, unknown> }[], http: 0, version: 1, revoked: false, conflict: Boolean(initial.conflict), passkey: Boolean(initial.passkey) };
    const member = { user_id: "00000000-0000-4000-8000-000000000001", member_id: "00000000-0000-4000-8000-000000000002", household_id: "00000000-0000-4000-8000-000000000003", display_name: "합성 앱 구성원", role: "owner" };
    const cursor = "00000000-0000-4000-8000-000000000009";
    const firstDevice = () => ({ id: "00000000-0000-4000-8000-000000000004", label: "합성 첫 기기", platform: "android", status: state.revoked ? "revoked" : "active", last_seen_at: "2026-10-17T00:00:00Z", current: false, version: state.version });
    const secondDevice = { ...firstDevice(), id: "00000000-0000-4000-8000-000000000005", label: "합성 둘째 기기", current: true };
    Object.assign(window, {
      __nativeMock: state,
      CapacitorCustomPlatform: { name: "android" },
      Capacitor: {
        PluginHeaders: [{ name: "SallimBookAuth", methods: ["getSession", "loginUI", "reauthenticateUI", "acceptInvitationUI", "createInvitationUI", "logout", "request", "passkeyLoginUI", "registerPasskeyUI", "revokePasskeyUI", "revokeDeviceUI", "createInvitationWithPasskeyUI"].map((name) => ({ name, rtype: "promise" })).concat([{ name: "addListener", rtype: "callback" }, { name: "removeListener", rtype: "promise" }]) }],
        nativeCallback: () => "synthetic-lock-listener",
        nativePromise: async (_plugin: string, method: string, args: Record<string, unknown> = {}) => {
          if (method === "removeListener") return;
          state.calls.push({ method, args });
          const success = (value: unknown) => ({ ok: true, value });
          if (method === "getSession") return success({ available: true, authenticated: state.authenticated });
          if (method === "loginUI" || method === "passkeyLoginUI") { if (!initial.cancelled) state.authenticated = true; return success({ status: initial.cancelled ? "cancelled" : "authenticated" }); }
          if (method === "reauthenticateUI") return success({ status: initial.cancelled ? "cancelled" : "authenticated" });
          if (method === "acceptInvitationUI") return success({ status: initial.cancelled ? "cancelled" : "accepted" });
          if (method === "createInvitationUI" || method === "createInvitationWithPasskeyUI") return success({ status: initial.cancelled ? "cancelled" : "created" });
          if (method === "registerPasskeyUI" && initial.expiredRegistration) return { ok: false, code: "SESSION_EXPIRED" };
          if (method === "registerPasskeyUI") { if (!initial.cancelled) state.passkey = true; return success({ status: initial.cancelled ? "cancelled" : "registered" }); }
          if (method === "revokePasskeyUI") { if (!initial.cancelled) state.passkey = false; return success({ status: initial.cancelled ? "cancelled" : "revoked" }); }
          if (method === "revokeDeviceUI") { if (!initial.cancelled) state.revoked = true; return success({ status: initial.cancelled ? "cancelled" : "revoked" }); }
          if (method === "logout") { state.authenticated = false; return success({ status: "signedOut", serverRevoked: !initial.logoutUnconfirmed }); }
          if (method === "request") {
            if (String(args.path).startsWith("/api/v1/auth/passkeys?")) return success({ status: 200, body: { items: state.passkey ? [{ id: "00000000-0000-4000-8000-000000000010", label: "합성 네이티브 패스키", created_at: "2026-10-17T00:00:00Z", last_used_at: null, backed_up: false, device_type: "single_device", version: 1 }] : [], next_cursor: null } });
            if (args.path === "/api/v1/me") return success({ status: 200, body: member });
            if (args.method === "GET" && String(args.path).startsWith("/api/v1/devices?")) return success({ status: 200, body: String(args.path).includes("cursor=") ? { items: [firstDevice(), secondDevice], next_cursor: null } : { items: [firstDevice()], next_cursor: cursor } });
            if (args.method === "DELETE") {
              if (state.conflict) { state.conflict = false; state.version++; return success({ status: 409, body: { error: { code: "VERSION_CONFLICT", message: "UNTRUSTED_NATIVE_ERROR", request_id: "synthetic", current_version: state.version } } }); }
              state.revoked = true; state.version++; return success({ status: 204, body: null });
            }
          }
          return { ok: false, code: "REQUEST_FAILED" };
        },
      },
    });
    const fetch = window.fetch;
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (new URL(url, location.href).pathname.startsWith("/api/")) state.http++;
      return fetch.call(window, input, init);
    };
  }, scenario);
}
async function bridgeState(page: Page) {
  return page.evaluate(() => (window as unknown as { __nativeMock: { calls: { method: string; args: Record<string, unknown> }[]; http: number } }).__nativeMock);
}
async function noWebCredentials(page: Page) {
  await expect(page.locator("input[type=password], input[name=token], input[name=intended_login], input[name=login_name]")).toHaveCount(0);
  const state = await bridgeState(page);
  expect(state.http).toBe(0);
  expect(state.calls.filter((call) => call.method !== "request").every((call) => {
    const keys = Object.keys(call.args).sort().join(",");
    return call.method === "revokePasskeyUI" ? keys === "credentialId,ifMatch" : call.method === "revokeDeviceUI" ? keys === "deviceId,ifMatch" : keys === "";
  })).toBe(true);
  expect(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0)).toBe(true);
}

test("native login uses parameterless UI and restores only metadata", async ({ page }) => {
  await nativeMock(page);
  await page.goto("/login");
  await page.getByRole("button", { name: "앱에서 로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/auth$/);
  await expect(page.getByText("합성 앱 구성원", { exact: true })).toBeVisible();
  await noWebCredentials(page);
  expect((await bridgeState(page)).calls.some((call) => call.method === "loginUI")).toBe(true);
});

for (const cancelled of [false, true]) test(`native password reauthentication preserves session on ${cancelled ? "cancellation" : "success"}`, async ({ page }) => {
  await nativeMock(page, { authenticated: true, cancelled });
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "앱 패스키로 로그인", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "비밀번호로 다시 인증", exact: true }).click();
  await expect(page).toHaveURL(cancelled ? /\/login$/ : /\/settings\/auth$/);
  const calls = (await bridgeState(page)).calls;
  expect(calls.some((call) => call.method === "reauthenticateUI")).toBe(true);
  expect(calls.some((call) => call.method === "loginUI")).toBe(false);
  await page.goto("/settings/auth");
  await expect(page.getByText("합성 앱 구성원", { exact: true })).toBeVisible();
  await noWebCredentials(page);
});

test("cancelled native login stays signed out and permits retry", async ({ page }) => {
  await nativeMock(page, { cancelled: true });
  await page.goto("/login");
  const button = page.getByRole("button", { name: "앱에서 로그인", exact: true });
  await button.click();
  await expect(button).toBeEnabled();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("합성 앱 구성원", { exact: true })).toHaveCount(0);
  await noWebCredentials(page);
});

for (const cancelled of [true, false]) test(`native invitation acceptance ${cancelled ? "cancelled" : "accepted"} never creates a JS session`, async ({ page }) => {
  await nativeMock(page, { cancelled });
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "초대 수락하고 계정 등록", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 수락하고 계정 등록", exact: true })).toBeEnabled();
  await expect(page.getByText("계정 등록을 마쳤어요.", { exact: false })).toHaveCount(cancelled ? 0 : 1);
  expect((await bridgeState(page)).calls.some((call) => call.method === "loginUI")).toBe(false);
  await noWebCredentials(page);
});

for (const cancelled of [true, false]) test(`native invitation creation ${cancelled ? "cancelled" : "created"} returns status only`, async ({ page }) => {
  await nativeMock(page, { authenticated: true, cancelled });
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "초대 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 만들기", exact: true })).toBeEnabled();
  await expect(page.getByText("초대를 만들었어요.", { exact: false })).toHaveCount(cancelled ? 0 : 1);
  await expect(page.getByLabel("생성된 초대 코드")).toHaveCount(0);
  await noWebCredentials(page);
});

test("native device metadata pagination deduplicates and conflict requires refresh", async ({ page }) => {
  await nativeMock(page, { authenticated: true, conflict: true });
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "기기 더 보기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 둘째 기기 현재 기기" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "합성 첫 기기", exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "합성 첫 기기 연결 해제", exact: true }).click();
  await page.getByRole("button", { name: "연결 해제 확인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("다시 불러");
  await expect(page.getByText("UNTRUSTED_NATIVE_ERROR")).toHaveCount(0);
  await page.getByRole("button", { name: "기기 목록 다시 불러오기", exact: true }).click();
  await page.getByRole("button", { name: "합성 첫 기기 연결 해제", exact: true }).click();
  await page.getByRole("button", { name: "연결 해제 확인", exact: true }).click();
  await expect(page.getByRole("button", { name: "합성 첫 기기 연결 해제", exact: true })).toHaveCount(0);
  expect((await bridgeState(page)).calls.filter((call) => call.args.method === "DELETE").map((call) => call.args.ifMatch)).toEqual(['"1"', '"2"']);
  await noWebCredentials(page);
});

test("native local logout preserves remote revocation uncertainty", async ({ page }) => {
  await nativeMock(page, { authenticated: true, logoutUnconfirmed: true });
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page.getByRole("heading", { name: "로그인이 필요해요" })).toBeVisible();
  await expect(page.getByText("이 기기에서는 로그아웃했어요.", { exact: false })).toBeVisible();
  await expect(page.getByText("합성 앱 구성원", { exact: true })).toHaveCount(0);
  await noWebCredentials(page);
});

for (const cancelled of [true, false]) test(`native passkey login ${cancelled ? "cancels" : "authenticates"} without JS ceremony data`, async ({ page }) => {
  await nativeMock(page, { cancelled });
  await page.goto("/login");
  await page.getByRole("button", { name: "앱 패스키로 로그인", exact: true }).click();
  if (cancelled) await expect(page.getByRole("button", { name: "앱 패스키로 로그인", exact: true })).toBeEnabled();
  else await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  expect((await bridgeState(page)).calls.some((call) => call.method === "passkeyLoginUI")).toBe(true);
  await noWebCredentials(page);
});

for (const cancelled of [true, false]) test(`native passkey registration ${cancelled ? "cancels" : "registers"} with status only`, async ({ page }) => {
  await nativeMock(page, { authenticated: true, cancelled });
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "앱에서 패스키 등록", exact: true }).click();
  await expect(page.getByRole("button", { name: "앱에서 패스키 등록", exact: true })).toBeEnabled();
  await expect(page.getByRole("heading", { name: "합성 네이티브 패스키", exact: true })).toHaveCount(cancelled ? 0 : 1);
  await expect(page.getByLabel("패스키 이름", { exact: true })).toHaveCount(0);
  await noWebCredentials(page);
});

for (const cancelled of [true, false]) test(`native passkey revocation ${cancelled ? "cancels" : "revokes"} with ID and version only`, async ({ page }) => {
  await nativeMock(page, { authenticated: true, passkey: true, cancelled });
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "합성 네이티브 패스키 패스키 해제", exact: true }).click();
  await page.getByRole("button", { name: "패스키 해제 확인", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 네이티브 패스키", exact: true })).toHaveCount(cancelled ? 1 : 0);
  await expect.poll(async () => (await bridgeState(page)).calls.some((call) => call.method === "revokePasskeyUI")).toBe(true);
  await noWebCredentials(page);
});

for (const cancelled of [true, false]) test(`native scoped device action ${cancelled ? "cancels" : "revokes"} without reusable grants`, async ({ page }) => {
  await nativeMock(page, { authenticated: true, cancelled });
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "합성 첫 기기 연결 해제", exact: true }).click();
  await page.getByRole("button", { name: "패스키로 확인하고 연결 해제", exact: true }).click();
  await expect(page.getByRole("button", { name: "합성 첫 기기 연결 해제", exact: true })).toHaveCount(cancelled ? 1 : 0);
  await expect.poll(async () => (await bridgeState(page)).calls.some((call) => call.method === "revokeDeviceUI")).toBe(true);
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  await noWebCredentials(page);
});

for (const cancelled of [true, false]) test(`native scoped invitation ${cancelled ? "cancels" : "creates"} within native UI`, async ({ page }) => {
  await nativeMock(page, { authenticated: true, cancelled });
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "패스키로 확인하고 초대", exact: true }).click();
  await expect(page.getByRole("button", { name: "패스키로 확인하고 초대", exact: true })).toBeEnabled();
  await expect(page.getByText("초대를 만들었어요.", { exact: false })).toHaveCount(cancelled ? 0 : 1);
  await expect(page.getByLabel("생성된 초대 코드")).toHaveCount(0);
  expect((await bridgeState(page)).calls.some((call) => call.method === "createInvitationWithPasskeyUI")).toBe(true);
  await noWebCredentials(page);
});

test("native registration session expiry clears account state without success", async ({ page }) => {
  await nativeMock(page, { authenticated: true, expiredRegistration: true });
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "앱에서 패스키 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible();
  await expect(page.getByText("패스키를 등록했어요.", { exact: true })).toHaveCount(0);
  await noWebCredentials(page);
});
