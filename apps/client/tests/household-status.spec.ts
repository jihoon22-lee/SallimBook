import { expect, test, type Page } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";
import { mockComparison } from "./support/comparison";
import { householdOverviewFor, sampleAccount, uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });

const plan = {
  expected_income_known_krw: "5000000",
  expected_income_count: 2,
  expected_income_unknown_count: 0,
  spending_known_krw: "2500000",
  loan_known_krw: "1055000",
  transfer_known_krw: "300000",
  margin_before_transfers_krw: "1445000",
  margin_after_transfers_krw: "1145000",
};

async function quietCare(page: Page) {
  // The consumables card reads on its own; keep it empty so the home status is what is tested.
  await page.route("**/api/v1/homecare/status?*", (route) =>
    route.fulfill({ json: { as_of: "2025-10-15", items: [], next_cursor: null } }),
  );
  await page.route("**/api/v1/appliances?*", (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
}

async function household(page: Page) {
  const state = await mockCashflow(page);
  await quietCare(page);
  await page.clock.setFixedTime(new Date("2025-10-15T03:00:00Z"));
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET") writes.push(request.url());
  });
  state.finance.overview = (month) =>
    householdOverviewFor({
      month,
      assets: state.finance.assets,
      accounts: state.finance.accounts,
      cards: state.cards,
      // The house was valued in June; the account was not updated since, the loan never entered.
      amounts: {
        [uid(10)]: { amount: "300000000", basis: "2025-06" },
        [uid(11)]: { amount: "1700000", basis: "2025-06", stale: true },
      },
      plan,
      insurance: {
        active_policy_count: 2,
        open_case_count: 1,
        claims_in_progress_count: 3,
        documents_required_count: 1,
        policies: [{ id: uid(70), name: "합성 보험사 · 합성 실손" }],
      },
    });
  return { state, writes };
}

test("the home shows each item's latest amount and only notes what could be updated", async ({
  page,
}) => {
  const { state, writes } = await household(page);
  await page.goto("/");
  const balance = page.getByRole("region", { name: "저장된 자산 금액" });
  await expect(balance).toContainText("등록 기준 순자산");
  await expect(balance).toContainText("301,700,000원");
  await expect(balance).toContainText(
    "금액 미입력 1개 · 오래된 금액 1개 · 가장 오래된 기준 2025년 6월",
  );
  await expect(balance.getByRole("link", { name: "금액 입력·수정" })).toHaveAttribute(
    "href",
    "/assets/months/2025-10",
  );
  const accounts = page.getByRole("region", { name: "계좌·연금", exact: true });
  await expect(accounts).toContainText("1,700,000원 (2025년 6월 기준) · 오래된 금액");
  await expect(accounts.getByRole("link", { name: "합성 개인 금융 자산" })).toHaveAttribute(
    "href",
    `/accounts/${sampleAccount.id}`,
  );
  await expect(page.getByRole("region", { name: "부동산", exact: true })).toContainText(
    "300,000,000원",
  );
  const loans = page.getByRole("region", { name: "대출", exact: true });
  await expect(loans).toContainText("금액 미입력");
  await expect(loans).toContainText("1개 · 금액 미입력 1개");
  const insurance = page.getByRole("region", { name: "보험", exact: true });
  await expect(insurance).toContainText("진행 중인 사건 1건 · 청구 진행 3건");
  await expect(
    insurance.getByRole("link", { name: "서류 보완이 필요한 청구 1건" }),
  ).toHaveAttribute("href", "/insurance/claims?state=documents_required");
  // Nothing asks for a month record before the status shows, and reading never writes.
  await expect(page.getByText(/먼저 월 기록|월 기록을 만들/)).toHaveCount(0);
  expect(state.finance.overviewMonths).toContain("2025-10");
  expect(writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("the plan margin is the server's estimate and never reads as a balance", async ({ page }) => {
  const { state } = await household(page);
  await page.goto("/");
  const margin = page.getByRole("region", { name: "월 계획 기준 여유", exact: true });
  await expect(margin).toContainText("1,445,000원");
  await expect(margin).toContainText("1,145,000원");
  await expect(margin).toContainText(
    "확인된 예상 수입 5,000,000원 − 소비성 비용 2,500,000원 − 대출 원리금 1,055,000원",
  );
  await expect(margin).toContainText("실제 잔액·저축액이 아니에요");
  await page.goto("/living");
  await expect(page.getByRole("region", { name: "월 계획 기준 여유", exact: true })).toContainText(
    "1,445,000원",
  );
  // Without a known expected income the margin waits instead of showing a deficit.
  const original = state.finance.overview!;
  state.finance.overview = (month) => {
    const data = original(month);
    return {
      ...data,
      plan: { ...data.plan, expected_income_count: 1, expected_income_unknown_count: 1 },
    };
  };
  await page.goto("/");
  await expect(page.getByRole("region", { name: "월 계획 기준 여유", exact: true })).toContainText(
    "예상 수입 금액을 등록하면 월 계획 기준 여유를 볼 수 있어요.",
  );
  await expect(page.getByText("1,445,000원", { exact: true })).toHaveCount(0);
});

test("parts that fail together show one message and one retry", async ({ page }) => {
  const { state } = await household(page);
  let incomeDown = true;
  await page.route("**/api/v1/income/summary?*", (route) =>
    incomeDown
      ? route.fulfill({
          status: 503,
          json: { error: { code: "UNAVAILABLE", message: "합성", request_id: "synthetic" } },
        })
      : route.fallback(),
  );
  state.finance.overviewFailure = true;
  await page.goto("/");
  await expect(page.locator(".retry-failed")).toHaveCount(1);
  const retry = page.getByRole("button", { name: "홈 다시 불러오기", exact: true });
  await expect(retry).toHaveCount(1);
  for (const name of ["보유 현황 다시 불러오기", "계획 기준 여유 다시 확인", "홈 수입 다시 확인"])
    await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
  incomeDown = false;
  state.finance.overviewFailure = false;
  await retry.click();
  await expect(page.locator(".retry-failed")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "저장된 자산 금액" })).toContainText(
    "301,700,000원",
  );
  await expect(page.getByRole("region", { name: "홈 등록 수입 요약" })).toBeVisible();
  // A single failure keeps its own message and retry.
  state.finance.overviewFailure = true;
  await page.goto("/");
  await expect(page.locator(".retry-failed")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "보유 현황 다시 불러오기", exact: true }),
  ).toBeVisible();
});

test("an asset list shows the latest entered amount when the month has none yet", async ({
  page,
}) => {
  const state = await mockComparison(page);
  // February has no entry for the house yet; January has one.
  state.after = state.after.filter((row) => row.asset_id !== uid(10));
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
  state.finance.overview = (month) =>
    householdOverviewFor({
      month,
      assets: state.finance.assets,
      accounts: state.finance.accounts,
      amounts: { [uid(10)]: { amount: "1000", basis: "2025-01" } },
    });
  await page.goto("/assets");
  const property = page
    .locator(".asset-record")
    .filter({ has: page.getByRole("link", { name: "합성 공동 주택", exact: true }) });
  await expect(property).toContainText("2025년 2월 가계 보유분 미입력");
  await expect(property).toContainText("최근 입력 1,000원 (2025년 1월 기준)");
  // A failed status read leaves the list as it was, with no extra error.
  state.finance.overviewFailure = true;
  await page.reload();
  await expect(property).toContainText("2025년 2월 가계 보유분 미입력");
  await expect(property).not.toContainText("최근 입력");
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("the insurance hub shows what is in progress and where to continue", async ({ page }) => {
  await household(page);
  await page.goto("/insurance");
  const status = page.getByRole("region", { name: "보험 현황", exact: true });
  await expect(status).toContainText("가입 중인 계약 2개");
  await expect(status).toContainText("진행 중인 사건 1건 · 청구 진행 3건");
  await expect(status.getByRole("link", { name: "합성 보험사 · 합성 실손" })).toHaveAttribute(
    "href",
    `/insurance/policies/${uid(70)}`,
  );
  await expect(status).toContainText("외 1개");
  await expect(status.getByRole("link", { name: "서류 보완이 필요한 청구 1건" })).toHaveAttribute(
    "href",
    "/insurance/claims?state=documents_required",
  );
});
