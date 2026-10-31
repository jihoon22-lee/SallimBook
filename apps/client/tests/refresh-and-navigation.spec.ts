import { expect, test } from "@playwright/test";
import { mockExports } from "./support/exports";
import { mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { mockMonths } from "./support/months";
import { mockComparison } from "./support/comparison";
import { uid } from "./support/finance";
import { openDisclosure } from "./support/task-ui";

test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-28T03:00:00Z"));
});

test("home insurance destination preserves its open financial state", async ({ page }) => {
  const state = await mockExports(page);
  const cases = state.documents.homecare.insurance.core.cases;
  cases[0]!.financial_state = "open";
  cases[1]!.financial_state = "settled";
  cases[1]!.title = "합성 정산 완료 사건";
  await page.goto("/");
  await page.getByText("월별 자산 변화·기록 관리", { exact: true }).click();
  await page.getByRole("link", { name: "진행 중인 보험 기록", exact: true }).click();
  await openDisclosure(page, "사건 찾기");
  await expect(page.getByRole("combobox", { name: "정산 상태 필터", exact: true })).toHaveValue(
    "open",
  );
  await expect(page.getByRole("link", { name: "합성 정산 완료 사건", exact: true })).toHaveCount(0);
});

test("manual income reload updates both rows and household totals", async ({ page }) => {
  const state = await mockCashflow(page);
  await page.goto("/income");
  const summary = page.getByRole("region", { name: "등록 수입 요약", exact: true });
  await expect(summary).toContainText("4,000,000원");
  state.incomes[0]!.amount_krw = "3456789";
  await openDisclosure(page, "수입 기록 찾기");
  await page.getByRole("button", { name: "수입 목록 다시 확인", exact: true }).click();
  await expect(page.locator(".task-records")).toContainText("3,456,789원");
  await expect(summary).toContainText("4,456,789원");
});

for (const transport of ["web", "native"] as const) {
  test(`${transport} resume refreshes stale income once and preserves fresh data`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    if (transport === "native") await mockNativeCashflow(page, state);
    await page.goto("/income");
    const summary = page.getByRole("region", { name: "등록 수입 요약", exact: true });
    await expect(summary).toContainText("4,000,000원");
    state.incomes[0]!.amount_krw = "3456789";
    await page.clock.setFixedTime(new Date("2025-02-28T03:01:00Z"));
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(summary).toContainText("4,000,000원");
    await page.clock.setFixedTime(new Date("2025-02-28T03:03:00Z"));
    await page.evaluate(() => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect(summary).toContainText("4,456,789원");
    await expect(page.locator(".task-records")).toContainText("3,456,789원");
    const reads = state.reads.length;
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await page.waitForTimeout(100);
    expect(state.reads.length).toBe(reads);
    expect(state.writes).toHaveLength(0);
  });
}

test("resume does not replace an unsaved income draft", async ({ page }) => {
  const state = await mockCashflow(page);
  await page.goto(`/income/${uid(40)}/edit`);
  const amount = page.getByLabel("수입 금액 (원)", { exact: true });
  await amount.fill("987654");
  const reads = state.reads.length;
  state.incomes[0]!.amount_krw = "3456789";
  await page.clock.setFixedTime(new Date("2025-02-28T03:03:00Z"));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.waitForTimeout(100);
  expect((await amount.inputValue()).replaceAll(",", "")).toBe("987654");
  expect(state.reads.length).toBe(reads);
  expect(state.writes).toHaveLength(0);
});

test("resume keeps the pages already opened in a long list", async ({ page }) => {
  const state = await mockCashflow(page);
  state.pageSize = 1;
  await page.goto("/income");
  await page.getByRole("button", { name: "수입 더 보기", exact: true }).click();
  await expect(page.locator(".task-records > li")).toHaveCount(2);
  state.incomes[1]!.amount_krw = "234567";
  await page.clock.setFixedTime(new Date("2025-02-28T03:03:00Z"));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.locator(".task-records")).toContainText("234,567원");
  await expect(page.locator(".task-records > li")).toHaveCount(2);
  expect(state.writes).toHaveLength(0);
});

test("monthly confirmation replaces the save notice and offers comparison", async ({ page }) => {
  const state = await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "합성 공동 주택 금액 확인", exact: true }).click();
  await page.getByLabel("입력 방식", { exact: true }).selectOption("unchanged");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await page.getByRole("button", { name: "합성 종료 대출 금액 확인", exact: true }).click();
  await page.getByLabel("확인 금액 (원)", { exact: true }).fill("0");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await page.getByRole("button", { name: "월 확정 검토", exact: true }).click();
  await page.getByRole("button", { name: "확인하고 월 확정", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("월 기록을 확정했어요");
  await expect(page.getByText("확인한 금액과 기준일을 저장했어요.", { exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByRole("link", { name: "확정한 월 비교", exact: true })).toHaveAttribute(
    "href",
    "/assets/compare?to=2025-02",
  );
  expect(state.record!.state).toBe("confirmed");
});

test("appliance link reaches its asynchronously loaded consumables section", async ({ page }) => {
  await mockExports(page);
  await page.goto("/appliances");
  await page.getByRole("link", { name: "연결 소모품·교체 확인", exact: true }).first().click();
  const target = page.locator("#device-consumables");
  await expect(target).toBeFocused();
  const rect = await target.boundingBox();
  // Near the end of the document the browser clamps scrolling to the page bottom.
  expect(rect!.y).toBeLessThan(page.viewportSize()!.height / 2);
  expect(rect!.y).toBeGreaterThanOrEqual(0);
});

test("the first monthly draft does not offer an unavailable previous copy", async ({ page }) => {
  const state = await mockMonths(page);
  state.record = null;
  state.previous = null;
  await page.goto("/assets/months/2025-02");
  const copy = page.getByLabel("전월 마지막 확정본의 금액 불러오기", { exact: true });
  await expect(copy).not.toBeChecked();
  await expect(copy).toBeDisabled();
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "미확인 항목 확인하기", exact: true }),
  ).toBeVisible();
  expect(state.writes[0]!.body.copy_previous).toBe(false);
});

test("first confirmed home offers its record and distinguishes no income from zero", async ({
  page,
}) => {
  const comparison = await mockComparison(page);
  comparison.mode = "no_previous_month";
  const state = await mockExports(page);
  state.documents.homecare.cashflow.incomes = [];
  await page.route("**/api/v1/asset-comparison?*", (route) =>
    route.fulfill({
      json: comparison.response(new URL(route.request().url()).searchParams),
    }),
  );
  await page.goto("/");
  await page.getByText("월별 자산 변화·기록 관리", { exact: true }).click();
  await expect(page.locator(".home-assets .asset-detail-actions > a.button-link")).toHaveAttribute(
    "href",
    "/assets/months/2025-02",
  );
  await expect(page.locator(".home-assets")).toContainText("서로 다른 기준일");
  const income = page.getByRole("region", { name: "홈 등록 수입 요약", exact: true });
  await expect(income).toContainText("이 달에 귀속된 실제 수입 기록은 아직 없어요");
  await expect(income).not.toContainText("0원");
});
