import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as {
  login: string;
  password: string;
  control: string;
};
test.setTimeout(120_000);
test.use({ actionTimeout: 10_000, navigationTimeout: 15_000 });
// No HTTP mocks or number-bearing diagnostics; all records are synthetic and disposable.
async function createAssetFields(page: Page, name: string, financial: boolean) {
  await page.getByLabel("자산 이름", { exact: true }).fill(name);
  if (!financial) await page.getByLabel("분류", { exact: true }).selectOption("real_estate");
  await page.getByLabel("소유 방식", { exact: true }).selectOption("joint");
  await page.getByLabel("가계 지분 (%)", { exact: true }).fill("33.3333333333333333");
  await page.getByLabel("금액 입력 기준", { exact: true }).selectOption("whole");
  await page.getByLabel("보유 시작일", { exact: true }).fill("2025-01-01");
}
for (const viewport of [
  { name: "desktop", width: 1280, height: 900 },
  { name: "android_size", width: 412, height: 915 },
])
  test(`real finance UI with scoped number reveal ${viewport.name}`, async ({ page, context }) => {
    await page.setViewportSize(viewport);
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
    let scopedHeader = false;
    let revealNoStore = false;
    page.on("request", (request) => {
      if (request.url().endsWith("/reveal"))
        scopedHeader ||= Boolean(request.headers()["x-step-up-token"]);
    });
    page.on("response", (response) => {
      if (response.url().endsWith("/reveal") && response.status() === 200)
        revealNoStore = response.headers()["cache-control"]?.includes("no-store") ?? false;
    });
    try {
      await page.goto("/login");
      await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
      await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
      await page.getByText("기기 이름 변경", { exact: true }).click();
      await page.getByLabel("이 기기 이름", { exact: true }).fill(`합성 금융 ${viewport.name}`);
      await page.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(
        page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
      ).toBeVisible();
      await page.goto("/settings/auth");
      await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
      await page.getByLabel("패스키 이름", { exact: true }).fill(`합성 금융 확인 ${viewport.name}`);
      await page.getByRole("button", { name: "패스키 등록", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: `합성 금융 확인 ${viewport.name}`, exact: true }),
      ).toBeVisible();
      console.log("SAFE_PHASE=FINANCE_LOGIN");

      await page.goto("/assets/new");
      await createAssetFields(page, `합성 HTTPS 공동 자산 ${viewport.name}`, false);
      await page.getByRole("button", { name: "자산 등록", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: `합성 HTTPS 공동 자산 ${viewport.name}`, exact: true }),
      ).toBeVisible();
      const assetId = new URL(page.url()).pathname.split("/").at(-1)!;
      await page.getByRole("link", { name: "자산 정보 수정", exact: true }).click();
      await page.getByLabel("자산 이름", { exact: true }).fill(`합성 내 수정 ${viewport.name}`);
      const setup = await page.evaluate(async (id) => {
        const csrf = await fetch("/api/v1/auth/web/csrf").then((response) => response.json());
        const asset = await fetch(`/api/v1/assets/${id}`).then((response) => response.json());
        const changed = await fetch(`/api/v1/assets/${id}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf.csrf_token,
            "If-Match": `"${asset.version}"`,
          },
          body: JSON.stringify({ note: "합성 다른 편집자의 HTTPS 메모" }),
        });
        return {
          status: changed.status,
          exactShare: asset.household_share === "0.333333333333333333",
          noAmounts: !Object.keys(asset).some((key) => key.endsWith("_krw") || key === "balance"),
        };
      }, assetId);
      expect(setup).toEqual({ status: 200, exactShare: true, noAmounts: true });
      await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
      await expect(page.getByRole("alert")).toContainText("다른 곳에서 정보가 변경");
      await page.getByRole("button", { name: "서버의 최신 정보 확인", exact: true }).click();
      await page.getByRole("button", { name: "비교한 내 수정 유지", exact: true }).click();
      await expect(page.getByLabel("메모 (선택)", { exact: true })).toHaveValue(
        "합성 다른 편집자의 HTTPS 메모",
      );
      await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: `합성 내 수정 ${viewport.name}`, exact: true }),
      ).toBeVisible();
      console.log("SAFE_PHASE=FINANCE_ASSET_CONFLICT");

      await page.goto("/accounts/new");
      await page.getByLabel("금융기관", { exact: true }).fill("합성 HTTPS 금융기관");
      await page.getByLabel("계좌 유형", { exact: true }).selectOption("irp");
      await createAssetFields(page, `합성 HTTPS IRP ${viewport.name}`, true);
      await page.getByLabel("개설일 (선택)", { exact: true }).fill("2025-01-01");
      await page.getByRole("button", { name: "계좌 등록", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: `합성 HTTPS IRP ${viewport.name}`, exact: true }),
      ).toBeVisible();
      const accountId = new URL(page.url()).pathname.split("/").at(-1)!;
      await page.getByRole("button", { name: "계좌번호 등록·변경", exact: true }).click();
      await page.getByLabel("새 계좌번호", { exact: true }).fill("SYNTHETIC-HTTPS-ACCOUNT");
      await page.getByRole("button", { name: "계좌번호 저장", exact: true }).click();
      await expect(page.getByLabel("새 계좌번호", { exact: true })).toHaveCount(0);
      const metadata = await page.evaluate(async (id) => {
        const response = await fetch(`/api/v1/accounts/${id}`);
        const account = await response.json();
        const assets = await fetch("/api/v1/assets?status=all").then((value) => value.json());
        return {
          noPlain: !Object.hasOwn(account, "account_number"),
          hasNumber: account.has_number,
          masked:
            Boolean(account.masked_number) && account.masked_number !== "SYNTHETIC-HTTPS-ACCOUNT",
          oneAsset:
            assets.items.filter((item: { id: string }) => item.id === account.asset_id).length ===
            1,
          noStore: response.headers.get("cache-control")?.includes("no-store") ?? false,
        };
      }, accountId);
      expect(metadata).toEqual({
        noPlain: true,
        hasNumber: true,
        masked: true,
        oneAsset: true,
        noStore: true,
      });
      console.log("SAFE_PHASE=FINANCE_NUMBER_SAVED");

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
      await page.getByRole("button", { name: "전체 계좌번호 30초 보기", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "패스키로 이 계좌번호만 확인", exact: true }),
      ).toBeVisible();
      expect(await page.evaluate(() => !document.querySelector("output")?.textContent)).toBe(true);
      await page.clock.install();
      await page.bringToFront();
      await page.getByRole("button", { name: "패스키로 이 계좌번호만 확인", exact: true }).click();
      await expect
        .poll(() => page.evaluate(() => Boolean(document.querySelector("output")?.textContent)))
        .toBe(true);
      const correct = await page.evaluate(
        () => document.querySelector("output")?.textContent === "SYNTHETIC-HTTPS-ACCOUNT",
      );
      await page.clock.fastForward(30_001);
      await expect
        .poll(() => page.evaluate(() => !document.querySelector("output")?.textContent))
        .toBe(true);
      expect(correct).toBe(true);
      expect(scopedHeader).toBe(true);
      expect(revealNoStore).toBe(true);
      console.log("SAFE_PHASE=FINANCE_SCOPED_REVEAL");
      const boundaries = await page.evaluate(async (id) => {
        const csrf = await fetch("/api/v1/auth/web/csrf").then((response) => response.json());
        const headers = { "Content-Type": "application/json", "X-CSRF-Token": csrf.csrf_token };
        const repeat = await fetch(`/api/v1/accounts/${id}/reveal`, { method: "POST", headers });
        const registration = await fetch("/api/v1/auth/passkeys/register/options", {
          method: "POST",
          headers,
          body: JSON.stringify({ label: "합성 범위 초과 거부" }),
        });
        const absent = await fetch("/api/v1/accounts/00000000-0000-4000-8000-000000000999");
        return {
          reveal: repeat.status,
          registration: registration.status,
          absent: absent.status,
          errorNoStore: [repeat, registration, absent].every((response) =>
            response.headers.get("cache-control")?.includes("no-store"),
          ),
        };
      }, accountId);
      expect(boundaries).toEqual({
        reveal: 403,
        registration: 403,
        absent: 404,
        errorNoStore: true,
      });
      await page.getByRole("button", { name: "계좌 사용 종료하기", exact: true }).click();
      await page.getByLabel("계좌 종료일", { exact: true }).fill("2026-09-20");
      await page.getByRole("button", { name: "계좌 사용 종료 확인", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "계좌 사용 종료하기", exact: true }),
      ).toHaveCount(0);
      expect(
        await page.evaluate(async (id) => {
          const response = await fetch(`/api/v1/accounts/${id}`);
          const value = await response.json();
          return (
            value.status === "closed" &&
            value.asset.status === "archived" &&
            value.closed_on === "2026-09-20"
          );
        }, accountId),
      ).toBe(true);
      expect(
        await page.evaluate(
          () =>
            localStorage.length === 0 &&
            sessionStorage.length === 0 &&
            document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      console.log("SAFE_PHASE=FINANCE_ACCOUNT_CLOSED");
    } finally {
      await page.close();
      await cdp.detach().catch(() => undefined);
    }
  });
