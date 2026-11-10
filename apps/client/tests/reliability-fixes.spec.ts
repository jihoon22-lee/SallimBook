import { expect, test } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";
import { mockComparison } from "./support/comparison";
import { mockFinance, uid } from "./support/finance";

async function resumeAfterTwoMinutes(page: import("@playwright/test").Page, at: string) {
  await page.clock.setFixedTime(new Date(at));
  await page.evaluate(() => {
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

test("home keeps the registered status on screen when a later refresh fails", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
  await mockComparison(page);
  await page.goto("/");
  const holdings = page.getByRole("region", { name: "우리 집 보유 현황", exact: true });
  const accounts = holdings.getByRole("region", { name: "계좌·연금", exact: true });
  await expect(accounts).toContainText("합성 개인 금융 자산");
  let failed = 0;
  await page.route("**/api/v1/household-overview?*", (route) => {
    failed += 1;
    return route.abort("failed");
  });
  await resumeAfterTwoMinutes(page, "2025-02-20T03:03:00Z");
  await expect.poll(() => failed).toBeGreaterThan(0);
  // The status stays; one retry is offered (the page-wide one when other parts failed too).
  await expect(accounts).toContainText("합성 개인 금융 자산");
  await expect(page.getByRole("region", { name: "계획상 남는 돈", exact: true })).toBeVisible();
  const retry = page.getByRole("button", { name: /다시 불러오기$/ }).first();
  await expect(retry).toBeVisible();
  await expect(holdings.getByText("보유 현황 불러오는 중", { exact: true })).toHaveCount(0);
  await page.unroute("**/api/v1/household-overview?*");
  await retry.click();
  await expect(accounts).toContainText("합성 개인 금융 자산");
});

test("an edited income resubmitted after an unanswered save is not recorded twice", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  // The server saves the first attempt but its answer never arrives.
  state.failure = "after";
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("3000");
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("처리 결과를 확인하지 못했어요");
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("3500");
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("이전 요청과 내용이 달라");
  expect(state.writes).toHaveLength(2);
  expect(state.writes[1]!.key).toBe(state.writes[0]!.key);
  expect(state.incomes.filter((row) => ["3000", "3500"].includes(row.amount_krw))).toHaveLength(1);
  // The conflict keeps the key held, so a further edit still cannot create a second record.
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("3600");
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(3);
  expect(state.writes[2]!.key).toBe(state.writes[0]!.key);
  expect(state.incomes.filter((row) => row.amount_krw === "3600")).toHaveLength(0);
});

test("stepping the compared month back drops an earlier month that no longer precedes it", async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date("2025-03-20T00:00:00Z"));
  const state = await mockComparison(page);
  await page.goto("/assets/compare?to=2025-03&from=2025-02");
  await expect.poll(() => state.queries.length).toBeGreaterThan(0);
  const target = page
    .getByRole("group", { name: "확인할 월" })
    .or(page.locator(".form-field").first());
  await target
    .getByRole("button", { name: /이전 달/ })
    .first()
    .click();
  await expect(page).toHaveURL(/compare\?to=2025-02$/);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect.poll(() => state.queries.at(-1)?.get("to")).toBe("2025-02");
  expect(state.queries.at(-1)?.get("from")).toBe("2025-01");
});

test("a month outside an item's holding period is not shown as a missing amount", async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
  const state = await mockFinance(page);
  // The synthetic joint home starts on 2025-01-01.
  expect(state.assets[0]!.started_on).toBe("2025-01-01");
  await page.goto("/assets");
  const item = page
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: "합성 공동 주택", exact: true }) });
  const amount = item.locator(".saved-amount strong");
  await expect(amount).toHaveText("미입력");
  await expect(item.getByRole("button", { name: "금액 입력·수정", exact: true })).toBeEnabled();
  await page.getByLabel("확인할 월", { exact: true }).fill("2024-12");
  await expect(amount).toHaveText("보유 기간이 아니에요");
  await expect(item.getByRole("button", { name: "금액 입력·수정", exact: true })).toBeDisabled();
});
