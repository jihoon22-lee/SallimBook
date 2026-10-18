import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { BrowserContext, Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";

// Isolated synthetic household, real TLS/API/PostgreSQL. No HTTP mocks or recorded secrets.
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as { login: string; password: string; setup_identity: string };
type Member = components["schemas"]["MemberResponse"];
test.setTimeout(120_000);
test.use({ actionTimeout: 15_000, navigationTimeout: 20_000, trace: "off", screenshot: "off", video: "off" });

async function readMember(page: Page): Promise<Member> {
  return page.evaluate(async () => {
    const response = await fetch("/api/v1/me", { cache: "no-store" });
    if (!response.ok) throw new Error("Synthetic onboarding member read failed");
    return response.json();
  });
}
async function fillRegistration(page: Page, name: string, code?: string) {
  if (code) await page.getByLabel("배우자 연결 코드", { exact: true }).fill(code);
  await page.getByLabel("표시 이름", { exact: true }).fill(name);
  await page.getByLabel("새 비밀번호", { exact: true }).fill(fixture.password);
  await page.getByLabel("새 비밀번호 확인", { exact: true }).fill(fixture.password);
}
async function home(page: Page) {
  await expect(page).toHaveURL(`${process.env.SALLIMBOOK_HTTPS_ORIGIN}/`);
  await expect(page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "우리 가계 시작하기", exact: true })).toHaveCount(0);
}
async function noPersistence(page: Page) {
  expect(await page.evaluate(async () => ({ local: localStorage.length, session: sessionStorage.length, caches: (await caches.keys()).length }))).toEqual({ local: 0, session: 0, caches: 0 });
  expect(await page.evaluate(() => !document.cookie.includes("sallimbook_session"))).toBe(true);
}

test("real mobile first setup and partner code connect enter one household without a CLI or separate login", async ({ page, context, browser }) => {
  let partnerContext: BrowserContext | undefined;
  let code = "";
  const noStore: boolean[] = [];
  page.on("response", (response) => {
    if (["/api/v1/household/setup", "/api/v1/auth/web/setup", "/api/v1/household/connection-code"].includes(new URL(response.url()).pathname)) noStore.push(response.headers()["cache-control"] === "no-store");
  });
  try {
    await context.setExtraHTTPHeaders({ "Tailscale-User-Login": fixture.setup_identity });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("link", { name: "우리 가계 시작하기", exact: true }).click();
    await expect(page.locator("input[name=login_name],input[name=token],input[name=device_label]")).toHaveCount(0);
    await fillRegistration(page, "합성 HTTPS 첫 계정");
    const setupResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/auth/web/setup" && response.request().method() === "POST");
    await page.getByRole("button", { name: "가계 만들고 시작하기", exact: true }).click();
    expect((await setupResponse).status()).toBe(201);
    await home(page);
    const owner = await readMember(page);
    expect(owner.role).toBe("owner");
    expect((await context.cookies()).some((cookie) => cookie.name === "__Host-sallimbook_session" && cookie.secure && cookie.httpOnly && cookie.sameSite === "Strict" && cookie.path === "/")).toBe(true);
    await page.reload(); await home(page);
    expect((await readMember(page)).member_id === owner.member_id).toBe(true);
    await page.goto("/settings/auth");
    await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
    await expect(page.locator("input[name=intended_login]")).toHaveCount(0);
    const codeResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/household/connection-code" && response.request().method() === "POST");
    await page.getByRole("button", { name: "배우자 연결 코드 만들기", exact: true }).click();
    const issued = await codeResponse;
    expect(issued.status()).toBe(201);
    const result: components["schemas"]["ConnectionCodeResponse"] = await issued.json();
    code = result.code;
    expect(/^[0-9]{8}$/.test(code)).toBe(true);
    await expect(page.getByRole("button", { name: "연결 코드 보기", exact: true })).toBeVisible();
    // Leave the code masked in the owner UI: response value stays in this test's memory.
    await expect(page.getByLabel("생성된 배우자 연결 코드", { exact: true })).toHaveCount(0);

    partnerContext = await browser.newContext({ baseURL: process.env.SALLIMBOOK_HTTPS_ORIGIN, viewport: { width: 390, height: 844 }, extraHTTPHeaders: { "Tailscale-User-Login": fixture.setup_identity } });
    const partner = await partnerContext.newPage();
    await partner.goto("/login");
    await expect(partner.getByText("이미 시작한 가계가 있다면 로그인하거나 배우자에게 받은 연결 코드를 입력해 주세요.", { exact: true })).toBeVisible();
    await expect(partner.getByRole("link", { name: "우리 가계 시작하기", exact: true })).toHaveCount(0);
    expect(await partner.evaluate(async (password) => {
      const response = await fetch("/api/v1/auth/web/setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: "합성 중복 시작", password, device_label: "합성 거절 확인" }) });
      return response.status;
    }, fixture.password)).toBe(409);
    await partner.getByRole("link", { name: "배우자 연결", exact: true }).click();
    await fillRegistration(partner, "합성 HTTPS 배우자", code);
    const connected = partner.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/auth/web/connect" && response.request().method() === "POST");
    await partner.getByRole("button", { name: "연결하고 시작하기", exact: true }).click();
    const connectedResponse = await connected;
    expect(connectedResponse.status()).toBe(201);
    expect(connectedResponse.headers()["cache-control"] === "no-store").toBe(true);
    await home(partner);
    const joined = await readMember(partner);
    expect(joined.role).toBe("member");
    expect(joined.household_id === owner.household_id && joined.member_id !== owner.member_id).toBe(true);
    await partner.reload(); await home(partner);
    expect((await readMember(partner)).member_id === joined.member_id).toBe(true);
    await page.goto("/settings");
    await expect(page.getByText("합성 HTTPS 첫 계정 · 가계 관리자", { exact: true })).toBeVisible();
    await expect(page.getByText("합성 HTTPS 배우자 · 가계 구성원", { exact: true })).toBeVisible();
    const membership = await page.evaluate(async () => {
      const response = await fetch("/api/v1/household/members", { cache: "no-store" });
      if (!response.ok) throw new Error("Synthetic household read failed");
      return response.json();
    }) as Member[];
    expect(membership.length === 2 && membership.every((member) => member.household_id === owner.household_id)).toBe(true);
    // A fresh unauthenticated context reusing the consumed bearer code must fail.
    await partnerContext.clearCookies();
    expect(await partner.evaluate(async ({ code, password }) => (await fetch("/api/v1/auth/web/connect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code, display_name: "합성 재사용 거절", password, device_label: "합성 거절 확인" }) })).status, { code, password: fixture.password })).toBe(400);
    expect(noStore.length >= 3 && noStore.every(Boolean)).toBe(true);
    await noPersistence(page); await noPersistence(partner);
  } finally { code = ""; await partnerContext?.close(); }
});
