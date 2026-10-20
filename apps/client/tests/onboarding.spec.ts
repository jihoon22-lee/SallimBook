import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockOnboarding } from "./support/onboarding";

// Synthetic credentials only; do not record form bodies or displayed connection codes.
test.use({ trace: "off", screenshot: "off", video: "off" });

async function fillRegistration(page: Page, code?: string, mismatch = false) {
  const password = `synthetic-only-${crypto.randomUUID()}`;
  if (code) await page.getByLabel("배우자 연결 코드", { exact: true }).fill(code);
  await page.getByLabel("표시 이름", { exact: true }).fill("합성 새 이름");
  await page.getByLabel("새 비밀번호", { exact: true }).fill(password);
  await page
    .getByLabel("새 비밀번호 확인", { exact: true })
    .fill(mismatch ? `${password}-different` : password);
}
async function expectHomeAndOpenAccount(page: Page) {
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "오늘의 살림" })).toBeVisible();
  await expect(page.getByRole("link", { name: "우리 가계 시작하기", exact: true })).toHaveCount(0);
  await page.locator(".topbar-link").click();
  await page
    .getByRole("main")
    .getByRole("link", { name: /^계정과 기기/ })
    .click();
}
async function noPersistence(page: Page) {
  expect(
    await page.evaluate(async () => ({
      local: localStorage.length,
      session: sessionStorage.length,
      caches: await caches.keys(),
    })),
  ).toEqual({ local: 0, session: 0, caches: [] });
}

test("empty household home starts entirely in browser with no operator token or login-name field", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  await page.goto("/");
  await page.getByRole("link", { name: "우리 가계 시작하기", exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(
    page.getByRole("heading", { name: "우리 가계 시작하기", exact: true }),
  ).toBeVisible();
  await expect(page.locator("form input")).toHaveCount(3);
  await expect(
    page.locator("input[name=login_name],input[name=device_label],input[name=token]"),
  ).toHaveCount(0);
  await fillRegistration(page);
  await page.getByRole("button", { name: "가계 만들고 시작하기", exact: true }).click();
  await expectHomeAndOpenAccount(page);
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByText("합성 새 이름", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true }),
  ).toBeVisible();
  expect(state.validSetup).toBe(true);
  expect(state.setupWrites).toBe(1);
  expect(state.loginWrites).toBe(0);
  await expect(page.locator("input[type=password]")).toHaveCount(0);
  await noPersistence(page);
});

for (const available of [true, false])
  test(`login keeps existing credentials and ${available ? "promotes first setup" : "offers partner connection without setup"}`, async ({
    page,
  }) => {
    const state = await mockOnboarding(page);
    state.available = available;
    await page.goto("/login");
    await expect.poll(() => state.setupReads).toBeGreaterThan(0);
    await expect(page.getByLabel("로그인 이름", { exact: true })).toBeVisible();
    await expect(page.getByLabel("비밀번호", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "우리 가계 시작하기", exact: true })).toHaveCount(
      available ? 1 : 0,
    );
    await page.getByRole("link", { name: "배우자 연결", exact: true }).click();
    await expect(page.getByLabel("배우자 연결 코드", { exact: true })).toBeVisible();
    expect(state.setupWrites).toBe(0);
  });

test("setup unavailability never renders registration and network uncertainty supports explicit retry", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  state.setupOffline = true;
  await page.goto("/onboarding");
  await expect(page.getByRole("alert")).toContainText("서버 연결");
  await expect(page.locator("form")).toHaveCount(0);
  state.setupOffline = false;
  state.available = false;
  await page.getByRole("button", { name: "가계 시작 상태 다시 확인" }).click();
  await expect(
    page.getByRole("heading", { name: "로그인하거나 배우자와 연결해 주세요", exact: true }),
  ).toBeVisible();
  await expect(page.locator("form")).toHaveCount(0);
  expect(state.setupWrites).toBe(0);
});

test("confirmation mismatch clears passwords without submitting registration", async ({ page }) => {
  const state = await mockOnboarding(page);
  await page.goto("/onboarding");
  await fillRegistration(page, undefined, true);
  await page.getByRole("button", { name: "가계 만들고 시작하기" }).click();
  await expect(page.getByRole("alert")).toContainText("일치하지 않아요");
  await expect(page.getByLabel("새 비밀번호", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("새 비밀번호 확인", { exact: true })).toHaveValue("");
  expect(state.setupWrites).toBe(0);
});

test("partner joins with an eight-digit code retaining leading zero and automatically signs in", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  state.available = false;
  await page.goto("/onboarding/connect");
  await expect(page.getByLabel("배우자 연결 코드", { exact: true })).toHaveAttribute(
    "inputmode",
    "numeric",
  );
  await fillRegistration(page, state.code);
  await page.getByRole("button", { name: "연결하고 시작하기", exact: true }).click();
  await expectHomeAndOpenAccount(page);
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  expect(state.validConnect).toBe(true);
  expect(state.connectWrites).toBe(1);
  expect(state.loginWrites).toBe(0);
  await expect(
    page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true }),
  ).toHaveCount(0);
  expect(page.url()).not.toContain(state.code);
  await noPersistence(page);
});

for (const [mode, code, status, message] of [
  ["setup", "SETUP_COMPLETE", 409, "이미 가계가 시작"],
  ["setup", "SETUP_UNAVAILABLE", 403, "새 가계를 시작할 수 없어요"],
  ["setup", "RATE_LIMITED", 429, "잠시 기다려야"],
  ["setup", "UNKNOWN_SERVER_FAILURE", 503, "요청을 완료하지 못했어요"],
  ["connect", "INVALID_CONNECTION_CODE", 400, "연결 코드가 맞지 않거나"],
  ["connect", "HOUSEHOLD_FULL", 409, "이미 두 계정"],
] as const)
  test(`${mode} ${code} preserves truthful error and clears sensitive input`, async ({ page }) => {
    const state = await mockOnboarding(page);
    state.error = code;
    state.status = status;
    await page.goto(mode === "setup" ? "/onboarding" : "/onboarding/connect");
    await fillRegistration(page, mode === "connect" ? state.code : undefined);
    const button = page.getByRole("button", {
      name: mode === "setup" ? "가계 만들고 시작하기" : "연결하고 시작하기",
      exact: true,
    });
    await button.click();
    await expect(page.getByRole("alert")).toContainText(message);
    await expect(page.getByText("UNTRUSTED_ONBOARDING_ERROR")).toHaveCount(0);
    await expect(page.getByLabel("새 비밀번호", { exact: true })).toHaveValue("");
    if (mode === "connect")
      await expect(page.getByLabel("배우자 연결 코드", { exact: true })).toHaveValue("");
    if (code === "SETUP_COMPLETE" || code === "SETUP_UNAVAILABLE")
      await expect(button).toBeDisabled();
    else await expect(button).toBeEnabled();
    expect(state.authenticated).toBe(false);
    expect(state.setupWrites + state.connectWrites).toBe(1);
    await noPersistence(page);
  });

test("cancelled registration ignores a late successful response and does not automatically retry", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  state.delay = 600;
  await page.goto("/onboarding");
  await fillRegistration(page);
  await page.getByRole("button", { name: "가계 만들고 시작하기" }).click();
  await expect.poll(() => state.setupWrites).toBe(1);
  await page.getByRole("button", { name: "요청 대기 중단" }).click();
  await expect(page.getByRole("alert")).toContainText("등록이 끝났을 수 있으니");
  await expect.poll(() => state.authenticated).toBe(true);
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toHaveCount(0);
  expect(state.setupWrites).toBe(1);
  expect(state.loginWrites).toBe(0);
  await expect(page.getByLabel("새 비밀번호", { exact: true })).toHaveValue("");
});

test("owner generates a CSRF-protected code without partner-login input and clears it on navigation", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  state.authenticated = true;
  await page.goto("/settings/auth");
  await expect(page.locator("input[name=intended_login]")).toHaveCount(0);
  await page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true }).click();
  await expect(page.getByLabel("생성된 배우자 연결 코드", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "연결 코드 보기", exact: true }).click();
  expect(
    (await page.getByLabel("생성된 배우자 연결 코드", { exact: true }).textContent()) ===
      state.code,
  ).toBe(true);
  expect(state.validCode).toBe(true);
  expect(state.codeWrites).toBe(1);
  expect(page.url()).not.toContain(state.code);
  await noPersistence(page);
  await page.getByRole("link", { name: "최근 로그인 다시 확인", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "로그인", exact: true })).toBeVisible();
  await expect(page.getByLabel("생성된 배우자 연결 코드", { exact: true })).toHaveCount(0);
  await page.goBack();
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  await expect(page.getByLabel("생성된 배우자 연결 코드", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "연결 코드 보기", exact: true })).toHaveCount(0);
});

for (const reason of ["timeout", "pagehide"] as const)
  test(`generated connection code is discarded on ${reason}`, async ({ page }) => {
    await page.clock.install();
    const state = await mockOnboarding(page);
    state.authenticated = true;
    await page.goto("/settings/auth");
    await page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true }).click();
    await page.getByRole("button", { name: "연결 코드 보기", exact: true }).click();
    await expect(page.getByLabel("생성된 배우자 연결 코드", { exact: true })).toBeVisible();
    if (reason === "timeout") await page.clock.fastForward(30_000);
    else await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    await expect(page.getByLabel("생성된 배우자 연결 코드", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "연결 코드 보기", exact: true })).toHaveCount(0);
  });

test("code generation requires recent authentication without exposing a result or retrying", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  state.authenticated = true;
  state.error = "REAUTHENTICATION_REQUIRED";
  state.status = 403;
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("다시 로그인");
  await expect(page.getByRole("link", { name: "다시 로그인", exact: true })).toHaveAttribute(
    "href",
    "/login",
  );
  await expect(page.getByRole("button", { name: "연결 코드 보기", exact: true })).toHaveCount(0);
  expect(state.codeWrites).toBe(1);
  expect(state.authenticated).toBe(true);
});

test("registration hides credentials on pagehide and remains usable at enlarged mobile width", async ({
  page,
}) => {
  await mockOnboarding(page);
  await page.goto("/onboarding/connect");
  await page.setViewportSize({ width: 320, height: 720 });
  await page.addStyleTag({ content: "html { font-size: 200%; }" });
  await fillRegistration(page, "00123456");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  await expect(page.getByLabel("배우자 연결 코드", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("새 비밀번호", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("새 비밀번호 확인", { exact: true })).toHaveValue("");
});

test("legacy login-name collision offers the existing invitation form without changing fixed aliases", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  state.authenticated = true;
  state.error = "LOGIN_UNAVAILABLE";
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("기존 계정의 로그인 이름과 겹쳐");
  await page.getByRole("button", { name: "기존 초대 방식으로 연결", exact: true }).click();
  await expect(page.getByLabel("초대할 로그인 이름", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "초대 만들기", exact: true })).toBeVisible();
  expect(state.codeWrites).toBe(1);
});

test("cancelled code creation discards a late code without claiming the server did not create one", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  state.authenticated = true;
  state.delay = 600;
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true }).click();
  await expect.poll(() => state.codeWrites).toBe(1);
  await page.getByRole("button", { name: "요청 대기 중단", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("코드가 생성됐을 수 있어요");
  await expect.poll(() => state.codeResponses).toBe(1);
  await expect(page.getByRole("button", { name: "연결 코드 보기", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("생성된 배우자 연결 코드", { exact: true })).toHaveCount(0);
  expect(state.codeWrites).toBe(1);
});

test("partner form rejects short or nonnumeric codes before sending a request", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  await page.goto("/onboarding/connect");
  await fillRegistration(page, "1234567");
  await page.getByRole("button", { name: "연결하고 시작하기", exact: true }).click();
  expect(state.connectWrites).toBe(0);
  await page.getByLabel("배우자 연결 코드", { exact: true }).fill("1234abcd");
  await page.getByRole("button", { name: "연결하고 시작하기", exact: true }).click();
  expect(state.connectWrites).toBe(0);
});

test("login account choices fill fixed aliases while preserving custom legacy login entry", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  state.available = false;
  await page.goto("/login");
  await page.getByLabel("비밀번호", { exact: true }).fill(`synthetic-only-${crypto.randomUUID()}`);
  await page.getByRole("button", { name: "처음 시작한 사람", exact: true }).click();
  await expect(page.getByLabel("로그인 이름", { exact: true })).toHaveValue("owner");
  await expect(page.getByLabel("비밀번호", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "연결한 배우자", exact: true }).click();
  await expect(page.getByLabel("로그인 이름", { exact: true })).toHaveValue("partner");
  await page.getByLabel("로그인 이름", { exact: true }).fill("synthetic.legacy");
  await expect(page.getByLabel("로그인 이름", { exact: true })).toHaveValue("synthetic.legacy");
  expect(state.loginWrites).toBe(0);
});
