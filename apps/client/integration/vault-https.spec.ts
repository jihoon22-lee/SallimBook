import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as {
  login: string;
  password: string;
  control: string;
};
const ownerName = "합성 HTTPS 구성원",
  partnerName = "합성 HTTPS 배우자";
const ownerPw = "Synthetic owner vault password 1!",
  partnerPw = "Synthetic partner vault password 1!";
const ownerRecovered = "Synthetic recovered owner password!",
  partnerChanged = "Synthetic changed partner password!";
const ownerRotated = "Synthetic rotated owner password!",
  partnerRotated = "Synthetic rotated partner password!",
  finalPw = "Synthetic final owner password!";
test.setTimeout(240_000);
test.use({ actionTimeout: 10_000, navigationTimeout: 15_000 });
const read = (page: Page, path: string) =>
  page.evaluate(async (path) => {
    const response = await fetch(path);
    if (!response.ok) throw new Error("Synthetic metadata read failed");
    return response.json();
  }, path);
async function login(page: Page, login: string, password: string) {
  await page.bringToFront();
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill(login);
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 HTTPS 보관함");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
  ).toBeVisible();
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
}
async function newPassword(page: Page, name: string, value: string) {
  await page.getByLabel(`${name}의 새 보관함 암호`, { exact: true }).fill(value);
  await page.getByLabel(`${name}의 새 보관함 암호 확인`, { exact: true }).fill(value);
}
async function confirmRecovery(page: Page) {
  await expect
    .poll(() => page.getByLabel("새 보관함 복구코드", { exact: true }).textContent())
    .toMatch(/^[A-Za-z0-9_-]{43}$/);
  const code = (await page.getByLabel("새 보관함 복구코드", { exact: true }).textContent())!;
  await page.getByLabel("새 복구코드를 오프라인으로 보관했어요").check();
  await page.getByRole("button", { name: "보관 확인·설정 완료", exact: true }).click();
  await expect(page.getByRole("region", { name: "보관함 보호 작업", exact: true })).toHaveCount(0);
  return code;
}
async function ackRun(page: Page) {
  await page.getByLabel("대상과 작업 내용을 확인했어요").check();
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
}
async function editCard(page: Page, id: string, password: string) {
  await page.goto(`/cards/${id}`);
  await page.getByText("암호 보관함 관리", { exact: true }).click();
  await page.getByRole("button", { name: "카드 비밀 등록·수정", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(password);
  await page.getByLabel("전체 카드 번호 (숫자만)").fill("4242424242424242");
  await page.getByLabel("유효기간 연도 (4자리)").fill("2032");
  await page.getByLabel("유효기간 월", { exact: true }).fill("12");
  await page.getByLabel("공유 CVC 처리", { exact: true }).selectOption("replace");
  await page.getByLabel("공유 CVC (3~4자리)", { exact: true }).fill("007");
  await page.getByLabel("공유 CVC의 접근·백업·삭제 범위를 확인했어요.").check();
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
  await expect(page.getByRole("region", { name: "보관함 보호 작업", exact: true })).toHaveCount(0);
}
async function viewCard(page: Page, id: string, password: string) {
  await page.bringToFront();
  await page.goto(`/cards/${id}`);
  await page.getByText("암호 보관함 관리", { exact: true }).click();
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "보관함 암호로 30초 보기", exact: true }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          document.querySelector('[aria-label="일시적으로 표시하는 카드 번호·유효기간·공유 CVC"]')
            ?.textContent === "4242424242424242 · 2032/12 · 공유 CVC 007",
      ),
    )
    .toBe(true);
  await page.getByRole("button", { name: "보호 작업 닫기·잠금", exact: true }).click();
}

test("real HTTPS WebCrypto setup sharing recovery all-card rotation revocation and purge", async ({
  page,
  browser,
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
  let noStore = true,
    opaqueOnly = true;
  page.on("response", (r) => {
    if (/\/api\/v1\/(vault|cards)(\/|$)/.test(new URL(r.url()).pathname) && r.status() < 300)
      noStore &&= r.headers()["cache-control"]?.includes("no-store") ?? false;
  });
  page.on("request", (r) => {
    if (/\/api\/v1\/(vault|cards)(\/|$)/.test(new URL(r.url()).pathname))
      opaqueOnly &&= !/4242424242424242|Synthetic .*password/.test(r.postData() ?? "");
  });
  await login(page, fixture.login, fixture.password);
  const setup = await page.evaluate(
    async ({ password, partnerName }) => {
      const csrf = await fetch("/api/v1/auth/web/csrf").then((r) => r.json());
      const post = async (path: string, body: unknown) => {
        const r = await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf.csrf_token },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error("Synthetic setup failed");
        return r.json();
      };
      const me = await fetch("/api/v1/me").then((r) => r.json());
      const invite = await post("/api/v1/household/invitations", {
        intended_login: "synthetic_https_partner",
      });
      const partner = await post("/api/v1/auth/invitations/accept", {
        token: invite.token,
        password,
        display_name: partnerName,
      });
      const card = await post("/api/v1/cards", {
        owner_member_id: me.member_id,
        issuer_name: "합성 보관함 발급사",
        product_name: "합성 보관함 카드",
        card_type: "credit",
      });
      const closed = await post("/api/v1/cards", {
        owner_member_id: me.member_id,
        issuer_name: "합성 보관함 발급사",
        product_name: "합성 종료 보관함 카드",
        card_type: "credit",
        started_on: "2025-01-01",
        ended_on: "2026-01-01",
      });
      return { me, partner, card: card.id, closed: closed.id };
    },
    { password: fixture.password, partnerName },
  );
  await page.goto("/vault");
  await page.getByRole("button", { name: "보관함 처음 설정", exact: true }).click();
  await newPassword(page, ownerName, ownerPw);
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
  let recovery = await confirmRecovery(page);
  await editCard(page, setup.card, ownerPw);
  await editCard(page, setup.closed, ownerPw);
  await viewCard(page, setup.card, ownerPw);
  console.log("SAFE_PHASE=VAULT_SETUP_CARD");
  const partnerContext = await browser.newContext({ baseURL: process.env.SALLIMBOOK_HTTPS_ORIGIN });
  const partner = await partnerContext.newPage();
  try {
    await login(partner, "synthetic_https_partner", fixture.password);
    expect(
      await partner.evaluate(
        async (id) => (await fetch(`/api/v1/cards/${id}/secret-envelope`)).status,
        setup.card,
      ),
    ).toBe(403);
    await page.bringToFront();
    await page.goto("/vault");
    await page.getByRole("button", { name: "이 구성원에게 공유", exact: true }).click();
    await page.getByLabel("현재 보관함 암호", { exact: true }).fill(ownerPw);
    await newPassword(page, partnerName, partnerPw);
    await ackRun(page);
    await expect(page.getByRole("region", { name: "보관함 보호 작업", exact: true })).toHaveCount(
      0,
    );
    await partner.bringToFront();
    await partner.goto("/vault");
    await partner.getByRole("button", { name: "공유 수락", exact: true }).click();
    await partner.getByLabel("현재 보관함 암호", { exact: true }).fill(partnerPw);
    await partner.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
    await expect(
      partner.getByRole("region", { name: "보관함 보호 작업", exact: true }),
    ).toHaveCount(0);
    await viewCard(partner, setup.closed, partnerPw);
    await partner.goto("/vault");
    await partner.getByRole("button", { name: "보관함 암호 변경", exact: true }).click();
    await partner.getByLabel("현재 보관함 암호", { exact: true }).fill(partnerPw);
    await newPassword(partner, partnerName, partnerChanged);
    await partner.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
    await expect(
      partner.getByRole("region", { name: "보관함 보호 작업", exact: true }),
    ).toHaveCount(0);
    await viewCard(partner, setup.card, partnerChanged);
    console.log("SAFE_PHASE=VAULT_SHARING_PASSWORD");
    await page.bringToFront();
    await page.goto("/vault");
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
    await page.getByRole("button", { name: "복구코드로 보관함 복구", exact: true }).click();
    await page.getByLabel("보관 중인 복구코드").fill(recovery);
    await newPassword(page, ownerName, ownerRecovered);
    await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
    await page.getByLabel("현재 계정 로그인 비밀번호").fill(fixture.password);
    await page.getByRole("button", { name: "이 화면에서 계정 다시 인증" }).click();
    await expect(page.getByLabel("보관 중인 복구코드")).toBeEnabled();
    await page.getByLabel("보관 중인 복구코드").fill(recovery);
    await newPassword(page, ownerName, ownerRecovered);
    await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
    recovery = await confirmRecovery(page);
    await viewCard(page, setup.card, ownerRecovered);
    console.log("SAFE_PHASE=VAULT_RECOVERY_REAUTH");
    await page.goto("/vault");
    await page.getByRole("button", { name: "보관함 키 회전 시작", exact: true }).click();
    await page.getByLabel("현재 보관함 암호", { exact: true }).fill(ownerRecovered);
    await newPassword(page, ownerName, ownerRotated);
    await newPassword(page, partnerName, partnerRotated);
    await ackRun(page);
    await expect(page.getByLabel("새 보관함 복구코드", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "보호 작업 닫기·잠금" }).click();
    await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
    await page.getByRole("button", { name: "키 회전 계속하기", exact: true }).click();
    await page.getByLabel("현재 보관함 암호", { exact: true }).fill(ownerRecovered);
    await newPassword(page, ownerName, ownerRotated);
    await newPassword(page, partnerName, partnerRotated);
    await ackRun(page);
    recovery = await confirmRecovery(page);
    expect((await read(page, "/api/v1/vault/status")).current_key_version).toBe(2);
    await viewCard(page, setup.closed, ownerRotated);
    await viewCard(partner, setup.card, partnerRotated);
    console.log("SAFE_PHASE=VAULT_ROTATION_RESUME");
    await page.bringToFront();
    await page.goto("/vault");
    await page.getByRole("button", { name: "보관함 키 회전 시작", exact: true }).click();
    await page.getByLabel("현재 보관함 암호", { exact: true }).fill(ownerRotated);
    await newPassword(page, ownerName, finalPw);
    await newPassword(page, partnerName, partnerRotated);
    await ackRun(page);
    await expect(page.getByLabel("새 보관함 복구코드", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "보호 작업 닫기·잠금" }).click();
    await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
    await page.getByRole("button", { name: "키 회전 중단 검토", exact: true }).click();
    await ackRun(page);
    await expect(page.getByRole("region", { name: "보관함 보호 작업", exact: true })).toHaveCount(
      0,
    );
    expect((await read(page, "/api/v1/vault/status")).current_key_version).toBe(2);
    await page.getByRole("button", { name: "이 구성원 접근 철회 검토", exact: true }).click();
    await ackRun(page);
    await expect(page.getByRole("region", { name: "보관함 보호 작업", exact: true })).toHaveCount(
      0,
    );
    expect(
      await partner.evaluate(
        async (id) => (await fetch(`/api/v1/cards/${id}/secret-envelope`)).status,
        setup.card,
      ),
    ).toBe(403);
    await page.getByRole("button", { name: "보관함 키 회전 시작", exact: true }).click();
    await page.getByLabel("현재 보관함 암호", { exact: true }).fill(ownerRotated);
    await newPassword(page, ownerName, finalPw);
    await ackRun(page);
    recovery = await confirmRecovery(page);
    expect((await read(page, "/api/v1/vault/status")).current_key_version).toBe(4);
    await viewCard(page, setup.card, finalPw);
    console.log("SAFE_PHASE=VAULT_ABORT_REVOKE_ROTATE");
    await page.goto(`/cards/${setup.card}`);
    await page.getByText("암호 보관함 관리", { exact: true }).click();
    await page.getByRole("button", { name: "카드 비밀 제거", exact: true }).click();
    await ackRun(page);
    await expect(page.getByRole("region", { name: "보관함 보호 작업", exact: true })).toHaveCount(
      0,
    );
    expect((await read(page, `/api/v1/cards/${setup.card}`)).has_secret).toBe(false);
    expect((await read(page, `/api/v1/cards/${setup.closed}`)).has_secret).toBe(true);
    expect(
      await page.evaluate(
        async (id) => (await fetch(`/api/v1/cards/${id}/secret-envelope`)).status,
        setup.card,
      ),
    ).toBe(404);
    expect(noStore && opaqueOnly).toBe(true);
    expect(
      await page.evaluate(
        async () => localStorage.length + sessionStorage.length + (await caches.keys()).length,
      ),
    ).toBe(0);
    recovery = "";
    console.log("SAFE_PHASE=VAULT_PURGE_BOUNDARIES");
  } finally {
    await partnerContext.close();
  }
  expect(violations).toEqual([]);
});
