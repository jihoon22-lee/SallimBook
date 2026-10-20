import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

// Chromium produces real WebAuthn signatures; the unchanged API verifies them in PostgreSQL.
// Never export virtual-authenticator private keys or record credential/request bodies.
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as {
  login: string;
  password: string;
  control: string;
};
test.setTimeout(90_000);
test.use({ actionTimeout: 10_000, navigationTimeout: 15_000 });

async function passwordLogin(page: Page, label: string) {
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
  await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill(label);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
  ).toBeVisible();
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
}

async function passkeyLogin(page: Page, label: string) {
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill(label);
  await page.getByRole("button", { name: "패스키로 로그인", exact: true }).click();
}

async function ageLogin(page: Page) {
  expect(
    await page.evaluate(
      async (control) =>
        (
          await fetch("/__test/expire-freshness", {
            method: "POST",
            headers: { "X-Test-Control": control },
          })
        ).status,
      fixture.control,
    ),
  ).toBe(200);
}

test("real passkey registration login scoped actions and revocation keep their server boundaries", async ({
  page,
  context,
}) => {
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  console.log("SAFE_PHASE=STARTED");
  const grants = { invitation: false, device: false };
  const otherContext = await context
    .browser()!
    .newContext({ baseURL: process.env.SALLIMBOOK_HTTPS_ORIGIN });
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/household/invitations")
      grants.invitation = Boolean(request.headers()["x-step-up-token"]);
    if (path.startsWith("/api/v1/devices/") && request.method() === "DELETE")
      grants.device = Boolean(request.headers()["x-step-up-token"]);
  });
  try {
    await passwordLogin(page, "합성 패스키 등록 브라우저");
    console.log("SAFE_PHASE=PASSWORD_LOGIN");
    await page.getByLabel("패스키 이름", { exact: true }).fill("합성 실제 검증 패스키");
    await page.getByRole("button", { name: "패스키 등록", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "합성 실제 검증 패스키", exact: true }),
    ).toBeVisible();
    console.log("SAFE_PHASE=BEFORE_LOGOUT");
    await page.getByRole("button", { name: "로그아웃", exact: true }).click();
    await passkeyLogin(page, "합성 패스키 로그인 브라우저");
    await expect(
      page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
    ).toBeVisible();
    await page.goto("/settings/auth");
    await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
    expect(
      (await context.cookies()).some(
        (cookie) =>
          cookie.name === "__Host-sallimbook_session" &&
          cookie.httpOnly &&
          cookie.secure &&
          cookie.sameSite === "Strict",
      ),
    ).toBe(true);

    console.log("SAFE_PHASE=PASSKEY_LOGIN");
    // Logout revokes its device too. Create an independently authenticated, still-active
    // synthetic device to revoke, instead of trying to revoke the already logged-out device.
    const otherPage = await otherContext.newPage();
    await passwordLogin(otherPage, "합성 별도 등록 기기");
    await otherPage.close();
    await page.bringToFront();
    await page.reload();
    await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
    await ageLogin(page);
    await page.getByText("기존 로그인 이름으로 초대", { exact: true }).click();
    await page.getByLabel("초대할 로그인 이름", { exact: true }).fill("synthetic_https_partner");
    await page.getByRole("button", { name: "패스키로 확인하고 초대", exact: true }).click();
    await expect(page.getByText("초대를 만들었어요.", { exact: false })).toBeVisible();
    expect(grants.invitation).toBe(true);
    console.log("SAFE_PHASE=INVITATION");
    await page.getByRole("button", { name: "합성 별도 등록 기기 연결 해제", exact: true }).click();
    await page.getByRole("button", { name: "패스키로 확인하고 연결 해제", exact: true }).click();
    const revokedDevice = page
      .locator("li.device-card")
      .filter({ has: page.getByRole("heading", { name: "합성 별도 등록 기기", exact: true }) });
    await expect(revokedDevice).toContainText("연결 해제됨");
    expect(grants.device).toBe(true);
    console.log("SAFE_PHASE=DEVICE_REVOKED");

    // Scoped authentication must not turn into a fresh account login for registering/revoking keys.
    await page.getByLabel("패스키 이름", { exact: true }).fill("합성 거부되어야 할 추가 패스키");
    await page.getByRole("button", { name: "패스키 등록", exact: true }).click();
    const panel = page.getByRole("region", { name: "내 패스키", exact: true });
    await expect(panel.getByRole("alert")).toContainText("5분 이내 로그인");
    await page
      .getByRole("button", { name: "합성 실제 검증 패스키 패스키 해제", exact: true })
      .click();
    await page.getByRole("button", { name: "패스키 해제 확인", exact: true }).click();
    await expect(panel.getByRole("alert")).toContainText("5분 이내 로그인");
    await expect(
      page.getByRole("heading", { name: "합성 실제 검증 패스키", exact: true }),
    ).toBeVisible();

    console.log("SAFE_PHASE=STALE_LOGIN_REJECTED");
    // A full login is started only after explicit sign-out; existing sessions use password reauth.
    await page.getByRole("button", { name: "로그아웃", exact: true }).click();
    await passkeyLogin(page, "합성 패스키 관리 재로그인");
    await expect(
      page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
    ).toBeVisible();
    await page.goto("/settings/auth");
    await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: "합성 실제 검증 패스키 패스키 해제", exact: true })
      .click();
    await page.getByRole("button", { name: "패스키 해제 확인", exact: true }).click();
    await expect(page.getByText("등록된 패스키가 없어요.", { exact: true })).toBeVisible();
    console.log("SAFE_PHASE=PASSKEY_REVOKED");
    console.log("SAFE_PHASE=BEFORE_LOGOUT");
    await page.getByRole("button", { name: "로그아웃", exact: true }).click();
    await passkeyLogin(page, "합성 폐기 패스키 로그인 시도");
    await expect(page.getByRole("alert")).toContainText("패스키를 확인하지 못했어요");
    expect(
      await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0),
    ).toBe(true);
    expect(
      await page.evaluate(
        async () => (await fetch("/api/v1/me", { credentials: "include" })).status,
      ),
    ).toBe(401);
    console.log("SAFE_PHASE=REVOKED_LOGIN_REJECTED");
    // L15: a revoked credential must not block registering again on the same authenticator.
    await passwordLogin(page, "합성 재등록 브라우저");
    await page.getByLabel("패스키 이름", { exact: true }).fill("합성 재등록 패스키");
    await page.getByRole("button", { name: "패스키 등록", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "합성 재등록 패스키", exact: true }),
    ).toBeVisible();
    console.log("SAFE_PHASE=PASSKEY_REREGISTERED");
  } finally {
    // Context teardown destroys its virtual authenticators, including pending ceremonies.
    // CDP removal can wait on an active browser prompt, so close the isolated target first.
    await otherContext.close();
    await page.close();
    await cdp.detach().catch(() => undefined);
  }
});

test("real pending authenticator can be cancelled without registration verification", async ({
  page,
  context,
}) => {
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: false,
    },
  });
  let verificationRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/auth/passkeys/register/verify")
      verificationRequests++;
  });
  try {
    await passwordLogin(page, "합성 취소 검증 브라우저");
    await page.getByLabel("패스키 이름", { exact: true }).fill("합성 취소할 패스키");
    const options = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/v1/auth/passkeys/register/options",
    );
    await page.getByRole("button", { name: "패스키 등록", exact: true }).click();
    expect((await options).status()).toBe(200);
    await page.getByRole("button", { name: "패스키 인증 취소", exact: true }).click();
    await expect(page.getByRole("button", { name: "패스키 등록", exact: true })).toBeEnabled();
    expect(verificationRequests).toBe(0);
    await expect(
      page.getByRole("heading", { name: "합성 취소할 패스키", exact: true }),
    ).toHaveCount(0);
  } finally {
    // Context teardown destroys its virtual authenticators, including pending ceremonies.
    // CDP removal can wait on an active browser prompt, so close the isolated target first.
    await page.close();
    await cdp.detach().catch(() => undefined);
  }
});
