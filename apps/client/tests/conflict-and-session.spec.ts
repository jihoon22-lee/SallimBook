import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";
import { members, uid } from "./support/finance";
import { mockMonths } from "./support/months";
test.use({ trace: "off", screenshot: "off", video: "off" });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});

test("a conflict table shows a comma-formatted draft as a grouped amount", async ({ page }) => {
  const state = await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "합성 공동 주택 금액 확인", exact: true }).click();
  await page.getByLabel("확인 금액 (원)", { exact: true }).fill("1,234,000");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-20");
  Object.assign(state.record!.values[0]!, {
    input_amount_krw: "2000",
    owned_amount_krw: "1000",
    as_of_date: "2025-02-21",
    verification_state: "verified",
    version: 2,
  });
  state.record!.version++;
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("작성한 내용은 유지");
  await page.getByRole("button", { name: "최신 월 기록과 비교", exact: true }).click();
  const table = page.getByRole("region", { name: "월 금액 충돌 비교 표", exact: true });
  const amount = table.getByRole("row").filter({ hasText: "금액" }).first();
  await expect(amount.getByRole("cell", { name: "1,234,000원", exact: true })).toBeVisible();
  await expect(amount.getByRole("cell", { name: "2,000원", exact: true })).toBeVisible();
  await expect(amount.getByRole("cell", { name: "미입력", exact: true })).toHaveCount(0);
});

/** The save endpoint answers 401 once; the sign-in endpoint restores a working session. */
async function expireOnNextSave(page: Page, state: Awaited<ReturnType<typeof mockCashflow>>) {
  const seen = { expire: true, logins: [] as Record<string, unknown>[] };
  await page.route("**/api/v1/income", async (route) => {
    if (route.request().method() === "POST" && seen.expire) {
      seen.expire = false;
      return route.fulfill({
        status: 401,
        json: { error: { code: "UNAUTHENTICATED", message: "UNTRUSTED", request_id: "synthetic" } },
      });
    }
    return route.fallback();
  });
  await page.route("**/api/v1/auth/web/login", (route) => {
    seen.logins.push(route.request().postDataJSON());
    state.finance.csrfCalls++;
    return route.fulfill({
      json: {
        csrf_token: `synthetic-finance-csrf-${state.finance.csrfCalls}`,
        member: members[0],
      },
    });
  });
  return seen;
}

test("a save answered with an expired session opens a sign-in dialog over the kept form", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const seen = await expireOnNextSave(page, state);
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  const amount = page.getByLabel("수입 금액 (원)", { exact: true });
  await amount.fill("3000");
  await page.getByRole("combobox", { name: "입금계좌", exact: true }).selectOption(uid(30));
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "로그인이 만료되었어요", exact: true });
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(/\/income\/new$/);
  expect(state.writes).toHaveLength(0);
  // The form is still there with what was typed; nothing is persisted in the browser.
  await expect(amount).toHaveValue("3000");
  const stored = () =>
    page.evaluate(async () => ({
      local: localStorage.length,
      session: sessionStorage.length,
      databases: (await indexedDB.databases()).length,
    }));
  expect(await stored()).toEqual({ local: 0, session: 0, databases: 0 });

  await dialog.getByLabel("로그인 이름", { exact: true }).fill("synthetic-owner");
  await dialog.getByLabel("비밀번호", { exact: true }).fill("synthetic-password-1");
  await dialog.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(seen.logins).toHaveLength(1);
  await expect(amount).toHaveValue("3000");
  expect(state.writes).toHaveLength(0);

  // The person presses save again; the same form saves.
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(1);
  expect(state.writes[0]!.body).toMatchObject({ amount_krw: "3000", member_id: uid(2) });
  expect(await stored()).toEqual({ local: 0, session: 0, databases: 0 });
});

test("closing the sign-in dialog keeps the form and a later save asks again", async ({ page }) => {
  const state = await mockCashflow(page);
  await expireOnNextSave(page, state);
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  const amount = page.getByLabel("수입 금액 (원)", { exact: true });
  await amount.fill("4100");
  await page.getByRole("combobox", { name: "입금계좌", exact: true }).selectOption(uid(30));
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "로그인이 만료되었어요", exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "닫기", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(amount).toHaveValue("4100");
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(dialog).toBeVisible();
  expect(state.writes).toHaveLength(0);
});

test("leaving a screen whose session ended shows the normal sign-in screen", async ({ page }) => {
  const state = await mockCashflow(page);
  await expireOnNextSave(page, state);
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("4100");
  await page.getByRole("combobox", { name: "입금계좌", exact: true }).selectOption(uid(30));
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "로그인이 만료되었어요", exact: true });
  await dialog.getByRole("button", { name: "닫기", exact: true }).click();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await page.getByRole("button", { name: "입력 버리고 나가기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible();
  await expect(dialog).toHaveCount(0);
});
