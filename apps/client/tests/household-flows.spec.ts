import { expect, test, type Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { householdOverviewFor, mockFinance, sampleAccount, uid } from "./support/finance";
import { mockInsurance, policyRow } from "./support/insurance";
import { openDisclosure } from "./support/task-ui";

type S = components["schemas"];

const plan = {
  expected_income_known_krw: "8900000",
  expected_income_count: 2,
  expected_income_unknown_count: 0,
  spending_known_krw: "3120000",
  loan_known_krw: "1450000",
  transfer_known_krw: "1500000",
  margin_before_transfers_krw: "4330000",
  margin_after_transfers_krw: "2830000",
};
const months = ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"];
const net = [null, "601500000", "612000000", "620900000", "634350000", "638470000"];

function trends(to: string, count: number): S["HouseholdTrendsResponse"] {
  const labels = months.slice(-count);
  return {
    to_month: to,
    months: labels.length,
    net_assets: labels.map((month) => {
      const value = net[months.indexOf(month)]!;
      return {
        month,
        assets_krw: value === null ? null : "960270000",
        liabilities_krw: value === null ? null : "321800000",
        net_assets_krw: value,
        item_count: 3,
        known_count: value === null ? 0 : 2,
        entered_count: value === null ? 0 : 1,
        confirmed: month < "2025-12",
      };
    }),
    plan: labels.map((month) => {
      const early = month < "2025-12";
      return {
        month,
        as_of: `${month}-28`,
        income_known_krw: month === "2025-09" ? "0" : early ? "8500000" : "8900000",
        income_count: month === "2025-09" ? 0 : 2,
        income_unknown_count: 0,
        spending_known_krw: "3120000",
        loan_known_krw: early ? "1740000" : "1450000",
        transfer_known_krw: "1500000",
        planned_unknown_count: 0,
        margin_before_transfers_krw: month === "2025-09" ? null : early ? "3640000" : "4330000",
        margin_after_transfers_krw: month === "2025-09" ? null : early ? "2140000" : "2830000",
        actual_income_krw: month === "2026-01" ? "12100000" : "0",
      };
    }),
  };
}

const insuranceSummary: S["InsuranceSummaryResponse"] = {
  as_of: "2026-02-20",
  policy_count: 2,
  paid_unknown_count: 1,
  monthly_premium_krw: "418000",
  paid_total_krw: "18460000",
  received_krw: "6240000",
  matched_received_krw: "6000000",
  unassigned_received_krw: "240000",
  recovery_percent: "32.5",
  policies: [
    {
      policy_id: uid(80),
      insurer: "합성 보험사",
      product_name: "합성 실손",
      status: "active",
      monthly_premium_krw: "418000",
      paid_before_krw: "17000000",
      paid_through: "2025-12-31",
      paid_estimated_krw: "1460000",
      estimated_from_month: "2026-01",
      estimated_months: 2,
      unknown_months: 0,
      paid_total_krw: "18460000",
      received_krw: "6000000",
      recovery_percent: "32.5",
    },
    {
      policy_id: uid(81),
      insurer: "합성 보험사",
      product_name: "합성 미입력",
      status: "active",
      monthly_premium_krw: "0",
      paid_before_krw: null,
      paid_through: null,
      paid_estimated_krw: "0",
      estimated_from_month: null,
      estimated_months: 0,
      unknown_months: 0,
      paid_total_krw: null,
      received_krw: "0",
      recovery_percent: null,
    },
  ],
};

async function household(page: Page) {
  await page.clock.setFixedTime(new Date("2026-02-20T03:00:00Z"));
  const state = await mockCashflow(page);
  state.finance.overview = (month) =>
    householdOverviewFor({
      month,
      assets: state.finance.assets,
      accounts: state.finance.accounts,
      amounts: {
        [uid(10)]: { amount: "900000000", basis: "2025-12" },
        [uid(11)]: { amount: "60270000", basis: month },
        [uid(12)]: { amount: "321800000", basis: month },
      },
      plan,
      insurance: {
        active_policy_count: 2,
        open_case_count: 1,
        claims_in_progress_count: 1,
        documents_required_count: 0,
        policies: [{ id: uid(80), name: "합성 보험사 · 합성 실손" }],
      },
      investments: {
        count: 1,
        value_krw: "60270000",
        contributed_krw: "52000000",
        gain_krw: "8270000",
        return_percent: "15.9",
        missing_contribution_count: 1,
        items: [
          {
            asset_id: uid(11),
            account_id: sampleAccount.id,
            name: "합성 개인 금융 자산",
            account_type: "brokerage",
            value_krw: "60270000",
            basis_month: month,
            contributed_krw: "52000000",
            contributed_as_of: "2026-01-31",
            gain_krw: "8270000",
            return_percent: "15.9",
          },
        ],
      },
    });
  state.finance.trends = trends;
  state.finance.insuranceSummary = insuranceSummary;
  return state;
}

for (const transport of ["web", "native"] as const)
  test(`${transport} home leads with net assets, their trend and where the income goes`, async ({
    page,
  }) => {
    const state = await household(page);
    const native = transport === "native" ? await mockNativeCashflow(page, state) : null;
    const writes: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") writes.push(request.url());
    });
    await page.goto("/");
    const hero = page.getByRole("region", { name: "저장된 자산 금액" });
    // The server's total is shown rounded for reading and exactly beside it.
    await expect(hero.locator(".net-figure")).toHaveText("6억 3,847만원");
    await expect(hero.locator(".net-meta")).toContainText("638,470,000원");
    await expect(hero).toContainText("+412만원 지난달보다");
    await expect(hero.getByRole("img", { name: /순자산$/ })).toBeVisible();
    await expect(hero).toContainText("확정한 달");
    // A month with no saved amount is a gap, never a zero point.
    await expect(hero.locator(".chart-dot")).toHaveCount(5);
    await expect(hero.locator(".chart-dot-open")).toHaveCount(3);
    const flow = page.getByRole("region", { name: "계획상 남는 돈", exact: true });
    await expect(flow.locator(".flow-figure")).toHaveText("283만원");
    await expect(flow).toContainText("남는 돈2,830,000원");
    // Every bar's value is in the chart's accessible name, since the bars show no numbers.
    await expect(
      flow.getByRole("img", {
        name: /^월별 계획상 남는 돈: 2025년 9월 없음, .*2026년 2월 283만원$/,
      }),
    ).toBeVisible();
    await expect(flow.locator(".chart-bar")).toHaveCount(5);
    await expect(flow.getByRole("link", { name: "월별로 보기" })).toHaveAttribute(
      "href",
      "/living/monthly",
    );
    const invested = page.getByRole("region", { name: "투자·연금", exact: true });
    await expect(invested).toContainText("+827만원 (15.9%)");
    await expect(invested).toContainText("넣은 돈 52,000,000원 대비 최근 입력 평가액");
    await expect(invested).toContainText("넣은 돈을 적지 않은 투자·연금 계좌 1개");
    const insurance = page.getByRole("region", { name: "보험", exact: true });
    await expect(insurance).toContainText("32.5%");
    await expect(insurance).toContainText("낸 보험료를 모르는 계약 1개는 비율에서 뺐어요");
    await expect(insurance).toContainText("매달 418,000원");
    await expect(page.getByRole("region", { name: "자산 구성", exact: true })).toContainText(
      "900,000,000원",
    );
    if (native) {
      const called = native.calls.map((call) => call.method);
      expect(called).toContain("householdTrends");
      expect(called).toContain("insuranceSummary");
    }
    expect(writes).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });

test("the home works without the trend and says nothing about a month record", async ({ page }) => {
  const state = await household(page);
  await page.route("**/api/v1/household-trends?*", (route) => route.abort("failed"));
  await page.route("**/api/v1/insurance/summary", (route) => route.abort("failed"));
  await page.goto("/");
  const hero = page.getByRole("region", { name: "저장된 자산 금액" });
  await expect(hero.locator(".net-figure")).toHaveText("6억 3,847만원");
  await expect(hero.locator(".chart")).toHaveCount(0);
  await expect(hero).not.toContainText("지난달보다");
  // Counts still come from the status read when the summary could not be loaded.
  await expect(page.getByRole("region", { name: "보험", exact: true })).toContainText(
    "가입 중인 계약 2개",
  );
  await expect(page.getByText(/먼저 월 기록|월 기록을 만들/)).toHaveCount(0);
  expect(state.finance.overviewMonths).toContain("2026-02");
});

test("a future month shows its status without calling an older month last month", async ({
  page,
}) => {
  await household(page);
  await page.goto("/");
  const hero = page.getByRole("region", { name: "저장된 자산 금액" });
  await expect(hero).toContainText("지난달보다");
  await page.getByLabel("확인할 월", { exact: true }).fill("2026-03");
  // The trend still ends at the running month, so no change is claimed for March.
  await expect(hero.locator(".net-figure")).toHaveText("6억 3,847만원");
  await expect(hero).not.toContainText("지난달보다");
  await expect(
    hero.getByRole("img", { name: "2025년 9월부터 2026년 2월까지 순자산" }),
  ).toBeVisible();
});

test("monthly flow lists each month's plan with what changed and what was actually recorded", async ({
  page,
}) => {
  await household(page);
  await page.goto("/living/monthly");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("월별 흐름");
  await expect(page.getByRole("img", { name: "월별 예상 수입의 쓰임" })).toBeVisible();
  const table = page.getByRole("region", { name: "월별 흐름 표" });
  const row = (month: string) => table.getByRole("row").filter({ hasText: month });
  await expect(row("2026년 2월")).toContainText("2,830,000원");
  await expect(row("2026년 2월")).toContainText("기록 없음");
  await expect(row("2026년 1월")).toContainText("12,100,000원");
  await expect(row("2025년 12월")).toContainText("예상 수입 +40만원, 대출 원리금 -29만원");
  // Before any expected income was registered there is no margin, not a shortfall.
  await expect(row("2025년 9월")).toContainText("등록 전");
  await expect(row("2025년 9월").locator(".flow-left")).toHaveText("—");
  await expect(table.getByRole("row")).toHaveCount(7);
});

test("money put into an account is entered by hand and saved as an exact amount", async ({
  page,
}) => {
  const state = await mockFinance(page);
  await page.goto(`/accounts/${uid(30)}/edit`);
  await openDisclosure(page, "계좌 용도·개설일");
  await page.getByLabel("넣은 돈 기준일 (선택)", { exact: true }).fill("2026-01-31");
  await page.getByRole("button", { name: "계좌 수정 저장", exact: true }).click();
  // A date alone is not a contribution.
  await expect(page.getByRole("alert")).toContainText("넣은 돈을 확인해 주세요");
  expect(state.accountPatches).toHaveLength(0);
  await page.getByLabel("지금까지 넣은 돈 (원, 선택)", { exact: true }).fill("52,000,000");
  await page.getByRole("button", { name: "계좌 수정 저장", exact: true }).click();
  await expect.poll(() => state.accountPatches.length).toBe(1);
  expect(state.accountPatches[0]!.body).toEqual({
    contributed_krw: "52000000",
    contributed_as_of: "2026-01-31",
  });
});

test("premiums already paid need both the amount and its date, and the policy shows what came back", async ({
  page,
}) => {
  const state = await mockInsurance(page);
  state.summary = {
    ...insuranceSummary,
    policies: [{ ...insuranceSummary.policies[0]!, policy_id: policyRow().id }],
    policy_count: 1,
    paid_unknown_count: 0,
  };
  await page.goto("/insurance/policies/new");
  await page.getByLabel("보험사", { exact: true }).fill("합성 새 보험사");
  await page.getByLabel("보험 상품명", { exact: true }).fill("합성 새 보장");
  await page.getByLabel("보장 시작일", { exact: true }).fill("2020-01-01");
  await openDisclosure(page, "계약 기간·수익자·평가액·메모");
  await page.getByLabel("이미 낸 보험료 합계 (원, 선택)", { exact: true }).fill("17000000");
  await page.getByRole("button", { name: "보험 계약 등록", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("이미 낸 보험료의 금액·기준일");
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("이미 낸 보험료 기준일", { exact: true }).fill("2025-12-31");
  await page.getByRole("button", { name: "보험 계약 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 새 보장", exact: true })).toBeVisible();
  expect(state.writes[0]!.body).toMatchObject({
    premium_paid_before_krw: "17000000",
    premium_paid_through: "2025-12-31",
  });
  await page.goto(`/insurance/policies/${policyRow().id}`);
  const money = page.getByRole("region", { name: "낸 보험료와 받은 보험금" });
  await expect(money).toContainText("32.5%");
  await expect(money).toContainText("18,460,000원");
  await expect(money).toContainText("6,000,000원");
  await expect(money).toContainText(
    "직접 입력 17,000,000원(2025-12-31까지) + 2026년 1월부터 2개월 계획 금액 1,460,000원",
  );
  await page.goto("/insurance");
  const all = page.getByRole("region", { name: "계약별 보험료와 보험금" });
  await expect(all.getByRole("row")).toHaveCount(2);
  await expect(all).toContainText("32.5%");
  await expect(
    page.getByText("계약을 지정하지 않은 보험금 240,000원", { exact: false }),
  ).toBeVisible();
});
