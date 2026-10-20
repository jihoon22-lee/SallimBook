import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Real HTTPS + API + PostgreSQL, credentials are ephemeral synthetic fixtures.
// No route(), response mocks, trace, screenshots, video, or credential assertions.
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as {
  login: string;
  password: string;
};

test("real browser login restores HttpOnly Secure Strict cookie and logout revokes it", async ({
  page,
  context,
}) => {
  const violations: string[] = [];
  await page.exposeFunction("reportCspViolation", (value: string) => {
    violations.push(value);
  });
  await page.addInitScript(() =>
    document.addEventListener("securitypolicyviolation", (event) => {
      void (
        window as unknown as { reportCspViolation: (value: string) => Promise<void> }
      ).reportCspViolation(`${event.violatedDirective} ${event.blockedURI}`);
    }),
  );
  const screen = await page.goto("/login");
  // The harness serves screens with the production private web headers.
  expect(screen?.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
  await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 HTTPS 브라우저");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
  ).toBeVisible();
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  const cookies = await context.cookies();
  expect(
    cookies.some(
      (cookie) =>
        cookie.name === "__Host-sallimbook_session" &&
        cookie.secure &&
        cookie.httpOnly &&
        cookie.sameSite === "Strict" &&
        cookie.path === "/",
    ),
  ).toBe(true);
  expect(await page.evaluate(() => !document.cookie.includes("sallimbook_session"))).toBe(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "합성 HTTPS 브라우저 현재 기기" })).toBeVisible();
  await page.getByRole("link", { name: "최근 로그인 다시 확인", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByLabel("로그인 이름", { exact: true })).toHaveCount(0);
  await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "다시 인증", exact: true }).click();
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  await expect(page.locator(".device-card")).toHaveCount(1);
  const originalCookie = cookies.find((cookie) => cookie.name === "__Host-sallimbook_session");
  expect(
    (await context.cookies()).some(
      (cookie) => cookie.name === originalCookie?.name && cookie.value === originalCookie?.value,
    ),
  ).toBe(true);
  // localhost and 127.0.0.1 are different sites; the Strict cookie must not accompany
  // this cross-site iframe navigation. The response remains observable without CORS.
  const crossSite = await context.newPage();
  const otherOrigin = new URL(process.env.SALLIMBOOK_HTTPS_ORIGIN!);
  otherOrigin.hostname = "localhost";
  await crossSite.goto(`${otherOrigin.origin}/__test/cross-site`);
  const crossed = crossSite.waitForResponse(
    (response) => response.url() === `${process.env.SALLIMBOOK_HTTPS_ORIGIN}/api/v1/me`,
  );
  await crossSite.evaluate((origin) => {
    const frame = document.createElement("iframe");
    frame.src = `${origin}/api/v1/me`;
    document.body.append(frame);
  }, process.env.SALLIMBOOK_HTTPS_ORIGIN!);
  expect((await crossed).status()).toBe(401);
  await crossSite.close();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible();
  expect(
    (await context.cookies()).some((cookie) => cookie.name === "__Host-sallimbook_session"),
  ).toBe(false);
  expect(
    await page.evaluate(async () => (await fetch("/api/v1/me", { credentials: "include" })).status),
  ).toBe(401);
  expect(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0)).toBe(
    true,
  );
  expect(violations).toEqual([]);
});

test("real CSRF rejects mutation without token and rotated token only succeeds once", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
  await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
  ).toBeVisible();
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  const statuses = await page.evaluate(async () => {
    const logout = (token?: string) =>
      fetch("/api/v1/auth/web/logout", {
        method: "POST",
        credentials: "include",
        headers: token ? { "X-CSRF-Token": token } : {},
      }).then((response) => response.status);
    const missing = await logout();
    const first = await fetch("/api/v1/auth/web/csrf", { credentials: "include" }).then(
      (response) => response.json(),
    );
    const second = await fetch("/api/v1/auth/web/csrf", { credentials: "include" }).then(
      (response) => response.json(),
    );
    const stale = await logout(first.csrf_token);
    const current = await logout(second.csrf_token);
    const replay = await logout(second.csrf_token);
    return [missing, stale, current, replay];
  });
  expect(statuses).toEqual([403, 403, 204, 401]);
});
