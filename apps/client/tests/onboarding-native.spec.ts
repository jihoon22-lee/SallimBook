import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockNativeOnboarding } from "./support/onboarding";

test.use({ trace: "off", screenshot: "off", video: "off" });
async function noSecrets(page: Page, state: Awaited<ReturnType<typeof mockNativeOnboarding>>) {
  await expect(page.locator("input[type=password],input[name=code],input[name=display_name],input[name=login_name],input[name=intended_login],input[name=token]")).toHaveCount(0);
  expect(state.http).toEqual([]);
  expect(state.calls.filter((call) => call.method !== "request").every((call) => Object.keys(call.args).length === 0)).toBe(true);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
}

for (const mode of ["setup", "connect"] as const) {
  for (const cancelled of [false, true]) test(`native ${mode} ${cancelled ? "cancellation permits retry" : "installs session and restores safe member metadata"}`, async ({ page }) => {
    const state = await mockNativeOnboarding(page); state.cancelled = cancelled;
    await page.goto(mode === "setup" ? "/onboarding" : "/onboarding/connect");
    const button = page.getByRole("button", { name: mode === "setup" ? "앱에서 가계 시작하기" : "앱에서 배우자 연결", exact: true });
    await button.click();
    if (cancelled) {
      await expect(page.getByText("등록을 취소했어요. 준비되면 다시 시작해 주세요.", { exact: true })).toBeVisible();
      await expect(button).toBeEnabled();
      expect(state.authenticated).toBe(false);
    } else {
      await expect(page).toHaveURL(/\/$/);
      await expect(page.getByRole("heading", { level: 1, name: "함께 살피는 오늘의 살림" })).toBeVisible();
      await expect(page.getByRole("link", { name: "우리 가계 시작하기", exact: true })).toHaveCount(0);
      await page.locator(".topbar-link").click();
      await page.getByRole("main").getByRole("link", { name: /^계정과 기기/ }).click();
      await expect(page.getByText("합성 앱 새 계정", { exact: true })).toBeVisible();
      expect(state.calls.some((call) => call.method === "request" && call.args.path === "/api/v1/me")).toBe(true);
      await expect(page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true })).toHaveCount(mode === "setup" ? 1 : 0);
    }
    expect(state.calls.filter((call) => call.method === (mode === "setup" ? "createHousehold" : "connectHousehold"))).toHaveLength(1);
    await noSecrets(page, state);
  });
}

test("native login promotes setup and keeps partner connection when setup becomes unavailable", async ({ page }) => {
  const state = await mockNativeOnboarding(page);
  await page.goto("/login");
  await expect(page.getByRole("link", { name: "우리 가계 시작하기", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "앱에서 로그인", exact: true })).toBeVisible();
  state.available = false;
  await page.reload();
  await expect(page.getByRole("link", { name: "우리 가계 시작하기", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "배우자 연결", exact: true })).toBeVisible();
  await noSecrets(page, state);
});

test("native setup-status failure stays closed and retries without an HTTP fallback", async ({ page }) => {
  const state = await mockNativeOnboarding(page); state.failure = "NETWORK_UNAVAILABLE"; state.method = "getSetupStatus";
  await page.goto("/onboarding");
  await expect(page.getByRole("alert")).toContainText("서버 연결");
  await expect(page.getByRole("button", { name: "앱에서 가계 시작하기", exact: true })).toHaveCount(0);
  state.failure = "";
  await page.getByRole("button", { name: "가계 시작 상태 다시 확인", exact: true }).click();
  await expect(page.getByRole("button", { name: "앱에서 가계 시작하기", exact: true })).toBeEnabled();
  await noSecrets(page, state);
});

for (const [method, failure, message] of [
  ["createHousehold", "SETUP_COMPLETE", "이미 가계가 시작"],
  ["createHousehold", "RATE_LIMITED", "잠시 기다려야"],
  ["connectHousehold", "INVALID_CONNECTION_CODE", "연결 코드가 맞지 않거나"],
] as const) test(`native ${failure} renders only a safe error`, async ({ page }) => {
  const state = await mockNativeOnboarding(page); state.failure = failure; state.method = method;
  await page.goto(method === "createHousehold" ? "/onboarding" : "/onboarding/connect");
  await page.getByRole("button", { name: method === "createHousehold" ? "앱에서 가계 시작하기" : "앱에서 배우자 연결", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(message);
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toHaveCount(0);
  expect(state.authenticated).toBe(false);
  await noSecrets(page, state);
});

for (const cancelled of [false, true]) test(`native connection code ${cancelled ? "cancellation" : "creation"} returns status without exposing code`, async ({ page }) => {
  const state = await mockNativeOnboarding(page); state.authenticated = true; state.cancelled = cancelled;
  await page.goto("/settings/auth");
  const button = page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true });
  await button.click(); await expect(button).toBeEnabled();
  await expect(page.getByText("연결 코드를 만들었어요. 코드 전달은 앱의 보호 화면에서 진행해 주세요.", { exact: true })).toHaveCount(cancelled ? 0 : 1);
  await expect(page.getByRole("button", { name: "연결 코드 보기", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("생성된 배우자 연결 코드", { exact: true })).toHaveCount(0);
  expect(state.calls.filter((call) => call.method === "createConnectionCode")).toHaveLength(1);
  await noSecrets(page, state);
});

for (const mode of ["setup", "connect"] as const) test(`native ${mode} unlock event before Activity result does not cancel automatic home navigation`, async ({ page }) => {
  const state = await mockNativeOnboarding(page); state.unlockBeforeResult = true;
  await page.goto(mode === "setup" ? "/onboarding" : "/onboarding/connect");
  const button = page.getByRole("button", { name: mode === "setup" ? "앱에서 가계 시작하기" : "앱에서 배우자 연결", exact: true });
  await expect(button).toBeEnabled();
  const restores = state.calls.filter((call) => call.method === "getSession").length;
  await button.click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "함께 살피는 오늘의 살림" })).toBeVisible();
  expect(state.calls.filter((call) => call.method === "getSession")).toHaveLength(restores);
  expect(state.calls.some((call) => call.method === "request" && call.args.path === "/api/v1/me")).toBe(true);
  await noSecrets(page, state);
});

test("native lock invalidates a late registration result instead of exposing the new session", async ({ page }) => {
  const state = await mockNativeOnboarding(page); state.unlockBeforeResult = true; state.lockBeforeResult = true;
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "앱에서 가계 시작하기", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("앱이 잠겨 있어요");
  await expect(page.getByRole("heading", { name: "함께 살피는 오늘의 살림", exact: true })).toHaveCount(0);
  expect(state.calls.some((call) => call.method === "request" && call.args.path === "/api/v1/me")).toBe(false);
  await noSecrets(page, state);
});

test("native curtain enrollment restores the verified session on unlock without a JS enrollment call", async ({ page }) => {
  const state = await mockNativeOnboarding(page); state.locked = true;
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("앱이 잠겨 있어요");
  state.authenticated = true; state.available = false;
  await state.emitLock(false);
  await expect(page.getByRole("heading", { level: 1, name: "함께 살피는 오늘의 살림" })).toBeVisible();
  await expect(page.getByRole("link", { name: "우리 가계 시작하기", exact: true })).toHaveCount(0);
  await page.locator(".topbar-link").click();
  await page.getByRole("main").getByRole("link", { name: /^계정과 기기/ }).click();
  await expect(page.getByText("합성 앱 새 계정", { exact: true })).toBeVisible();
  expect(state.calls.some((call) => call.method === "request" && call.args.path === "/api/v1/me")).toBe(true);
  expect(state.calls.some((call) => call.method === "createHousehold" || call.method === "connectHousehold")).toBe(false);
  await noSecrets(page, state);
});
