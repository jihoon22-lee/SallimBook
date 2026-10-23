import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { auditRow, mockAudit } from "./support/audit";
import { mockCashflow } from "./support/cashflow";
import { mockComparison } from "./support/comparison";
import { mockFinance, uid } from "./support/finance";
import { mockHomecare } from "./support/homecare";
import { mockInsurance } from "./support/insurance";
test.use({ trace: "off", screenshot: "off", video: "off" });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});

const error = (code: string, status: number) => ({
  status,
  json: { error: { code, message: "UNTRUSTED", request_id: "synthetic" } },
});

test("a saved or deleted notice shown from router state does not come back on reload", async ({
  page,
}) => {
  await mockFinance(page);
  await page.goto(`/assets/${uid(10)}/edit`);
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 저장 이름");
  await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
  const saved = page.getByText("자산 정보를 저장했어요.", { exact: true });
  await expect(saved).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "합성 저장 이름", exact: true })).toBeVisible();
  await expect(saved).toHaveCount(0);

  // uid(10) has no account, so the mock lets it be deleted (uid(11) backs an account).
  await page.goto(`/assets/${uid(10)}`);
  await page.getByRole("button", { name: "오등록 삭제 검토", exact: true }).click();
  await page
    .getByLabel("잘못 등록한 자산이며 실제 삭제할 것을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "오등록 자산 삭제", exact: true }).click();
  const deleted = page.getByText("자산이 삭제된 것을 확인했어요.", { exact: true });
  await expect(page).toHaveURL(/\/assets$/);
  await expect(deleted).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("자산과 부채");
  await expect(deleted).toHaveCount(0);
});

test("pressing Enter in a field keeps focus on it after the save fails", async ({ page }) => {
  await mockCashflow(page);
  await page.route("**/api/v1/income", (route) =>
    route.request().method() === "POST"
      ? route.fulfill(error("UNAVAILABLE", 503))
      : route.fallback(),
  );
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await page.getByRole("combobox", { name: "입금계좌", exact: true }).selectOption(uid(30));
  const amount = page.getByLabel("수입 금액 (원)", { exact: true });
  await amount.fill("3000");
  await amount.press("Enter");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(amount).toBeFocused();
});

test("the trend chart labels its months and gives each point a large target", async ({ page }) => {
  await mockComparison(page);
  await page.goto("/assets/compare?to=2025-02&from=2025-01");
  const chart = page.locator("svg.asset-trend-chart");
  await expect(chart).toBeVisible();
  const labels = chart.locator("text.chart-month");
  await expect(labels.first()).toHaveText("2024.03");
  await expect(labels.last()).toHaveText("2025.02");
  expect(await labels.count()).toBeGreaterThanOrEqual(3);
  expect(await labels.count()).toBeLessThanOrEqual(7);
  const targets = chart.locator("circle.chart-point");
  expect(await targets.count()).toBe(3);
  for (const box of await targets.evaluateAll((nodes) =>
    nodes.map((node) => node.getBoundingClientRect().width),
  ))
    expect(box).toBeGreaterThanOrEqual(24);
});

test("a failed read says it could not load instead of using the save-failure wording", async ({
  page,
}) => {
  await mockCashflow(page);
  await page.route("**/api/v1/income?*", (route) => route.fulfill(error("UNAVAILABLE", 503)));
  await page.goto("/income");
  const alert = page.getByRole("alert").filter({ hasText: "불러오지 못했어요" });
  await expect(alert.first()).toBeVisible();
  await expect(page.getByText("다시 저장하지 않아요")).toHaveCount(0);
});

test("a medical node in use answers with the in-use message and no version-conflict review", async ({
  page,
}) => {
  await mockInsurance(page);
  await page.route(/\/api\/v1\/insurance\/cases\/[^/]+\/nodes\/[^/]+$/, (route) =>
    route.request().method() === "PATCH"
      ? route.fulfill(error("MEDICAL_NODE_IN_USE", 409))
      : route.fallback(),
  );
  await page.goto(`/insurance/cases/${uid(90)}/nodes/${uid(91)}`);
  await page.getByRole("button", { name: "진료 내용·위치 수정", exact: true }).click();
  await page.getByLabel("진료 이름", { exact: true }).fill("합성 바뀐 외래");
  await page.getByRole("button", { name: "진료 기록 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("하위 진료나 비용 기록이 있어");
  await expect(page.getByRole("button", { name: "보험 현재 내용 비교", exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByRole("button", { name: "진료 기록 저장", exact: true })).toBeEnabled();
});

test("Continue editing returns focus to the first field of the form", async ({ page }) => {
  await mockCashflow(page);
  await page.goto("/income/new");
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("3500");
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await page.getByRole("button", { name: "계속 입력하기", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "수입 구성원", exact: true })).toBeFocused();
});

test("a version conflict in the delete review offers to load the item again", async ({ page }) => {
  const state = await mockFinance(page);
  await page.route(/\/api\/v1\/assets\/[^/]+$/, (route) =>
    route.request().method() === "DELETE"
      ? route.fulfill(error("VERSION_CONFLICT", 409))
      : route.fallback(),
  );
  await page.goto(`/assets/${uid(11)}`);
  await page.getByRole("button", { name: "오등록 삭제 검토", exact: true }).click();
  await page
    .getByLabel("잘못 등록한 자산이며 실제 삭제할 것을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "오등록 자산 삭제", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  const reads = state.assets.length;
  const reload = page.getByRole("button", { name: "다시 불러오기", exact: true });
  await expect(reload).toBeVisible();
  await reload.click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(state.assets).toHaveLength(reads);
});

async function home(page: Page) {
  const comparison = await mockComparison(page);
  await mockHomecare(page);
  await page.route("**/api/v1/asset-comparison?*", (route) =>
    route.fulfill({ json: comparison.response(new URL(route.request().url()).searchParams) }),
  );
  return comparison;
}

test("home says the previous month is what to confirm when only it is unconfirmed", async ({
  page,
}) => {
  const state = await home(page);
  state.mode = "unconfirmed";
  state.previousOnly = true;
  await page.goto("/");
  const assets = page.getByRole("region", { name: "자산의 변화", exact: true });
  await expect(assets.getByText("전월 확정 후 비교", { exact: true })).toBeVisible();
  await expect(assets.getByText("확정 후 비교", { exact: true })).toHaveCount(0);
});

test("the audit page shows Korean labels for changed fields and 기타 항목 for unknown ones", async ({
  page,
}) => {
  const state = await mockAudit(page);
  state.rows = [
    auditRow(9200, { changed_fields: ["household_share", "name", "password_hash", "brand_new"] }),
  ];
  await page.goto("/settings/audit");
  const row = page
    .getByRole("region", { name: "감사 기록 목록", exact: false })
    .getByRole("listitem");
  await expect(row.first()).toContainText("가계 지분");
  await expect(row.first()).toContainText("이름");
  await expect(row.first()).toContainText("보안 정보");
  await expect(row.first()).toContainText("기타 항목");
  await expect(row.first()).not.toContainText("household_share");
  await expect(row.first()).not.toContainText("brand_new");
});

test("a reversal dated before its original shows the dated message, a conflict keeps the old one", async ({
  page,
}) => {
  await mockCashflow(page);
  let status = 422;
  await page.route(/\/api\/v1\/income\/[^/]+\/returns$/, (route) =>
    route.fulfill(error("INVALID_REVERSAL", status)),
  );
  await page.goto(`/income/${uid(40)}`);
  await page.getByRole("button", { name: "수입 반환 기록", exact: true }).click();
  await page.getByLabel("반환 금액 (원)", { exact: true }).fill("100000");
  await page.getByLabel("실제 반환일", { exact: true }).fill("2025-02-20");
  await page.getByLabel("반환 사유", { exact: true }).fill("합성 일부 반환");
  await page.getByRole("button", { name: "반환 기록 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("반환일은 원본 날짜보다 빠를 수 없어요.");
  status = 409;
  await page.getByRole("button", { name: "반환 기록 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("반환할 원본 수입과 금액을 확인해 주세요.");
});

test("an unavailable account or card names both the opening and the end dates", async ({
  page,
}) => {
  await mockCashflow(page);
  await page.route("**/api/v1/income", (route) =>
    route.request().method() === "POST"
      ? route.fulfill(error("ACCOUNT_UNAVAILABLE", 422))
      : route.fallback(),
  );
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("3000");
  await page.getByRole("combobox", { name: "입금계좌", exact: true }).selectOption(uid(30));
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("선택한 계좌를 그 날짜에 쓸 수 없어요");
  await expect(page.getByRole("alert")).toContainText("개설일과 사용 종료일");
});
