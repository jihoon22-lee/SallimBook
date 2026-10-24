import { expect, test } from "@playwright/test";
import { incomeRow, mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { sampleAccount, uid } from "./support/finance";

test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
for (const native of [false, true]) {
  test(`account and card details show all registered connections and linked month income ${native ? "native" : "web"}`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    state.linksRequired = true;
    state.linksMore = true;
    state.pageSize = 1;
    state.incomes = Array.from({ length: 55 }, (_, i) =>
      incomeRow(400 + i, {
        account_id: i === 54 ? uid(30) : null,
        amount_krw: "17000",
        state: i === 54 ? "void" : "active",
      }),
    );
    const bridge = native ? await mockNativeCashflow(page, state) : null;
    await page.goto(`/accounts/${uid(30)}`);
    const payment = page.getByRole("region", { name: "정기 결제 연결", exact: true });
    await expect(payment).toContainText("연결 규칙 2개 · 적용기간 2개");
    await expect(payment.getByRole("link", { name: "합성 미래 연간 구독" })).toHaveAttribute(
      "href",
      `/fixed-payments/rules/${uid(61)}`,
    );
    await expect(payment).toContainText("전체 카드 명세나 계좌 출금 합계는 아니에요");
    await expect(payment.getByRole("link", { name: state.cards[0]!.alias! })).toHaveAttribute(
      "href",
      `/cards/${uid(50)}`,
    );
    const income = page.getByRole("region", { name: "계좌에 연결된 수입" });
    await expect(income.getByRole("link")).toHaveAttribute("href", `/income/${uid(454)}`);
    await expect(income).toContainText("무효 기록");
    expect(state.reads.filter((row) => row.path === "/api/v1/income").length).toBeGreaterThan(50);
    await page.goto(`/cards/${uid(50)}`);
    await expect(page.getByRole("region", { name: "정기 결제 연결" })).toContainText(
      "연결 규칙 2개",
    );
    await expect(
      page.getByRole("link", { name: sampleAccount.asset.name, exact: true }),
    ).toHaveAttribute("href", `/accounts/${uid(30)}`);
    expect(state.writes).toHaveLength(0);
    if (bridge) expect(bridge.http).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
  test(`income links the exact payout return and both case allocations ${native ? "native" : "web"}`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    const recordId = uid(42);
    state.incomes[2]!.kind = "insurance_return";
    state.incomes[2]!.flow = "out";
    state.insuranceSources.set(recordId, {
      record_id: recordId,
      payout_id: uid(1100),
      return_id: uid(1190),
      original_allocation_id: uid(2101),
      allocations: [
        { id: uid(2100), case_id: uid(90), case_title: "합성 첫 사건", amount_krw: "100000" },
        { id: uid(2101), case_id: uid(95), case_title: "합성 두 번째 사건", amount_krw: "500000" },
      ],
    });
    const bridge = native ? await mockNativeCashflow(page, state) : null;
    await page.goto(`/income/${recordId}`);
    const source = page.getByRole("region", { name: "보험금 원본과 배분 사건" });
    await expect(source.getByRole("link", { name: "실제 입금 원본과 전체 배분" })).toHaveAttribute(
      "href",
      `/insurance/payouts/${uid(1100)}`,
    );
    await expect(source.getByRole("link", { name: "실제 반환 원본" })).toHaveAttribute(
      "href",
      `/insurance/returns/${uid(1190)}`,
    );
    await expect(source.getByRole("link", { name: "합성 첫 사건" })).toHaveAttribute(
      "href",
      `/insurance/cases/${uid(90)}`,
    );
    await expect(source.getByRole("link", { name: "합성 두 번째 사건" })).toHaveAttribute(
      "href",
      `/insurance/cases/${uid(95)}`,
    );
    await expect(
      source.getByRole("listitem").filter({ hasText: "합성 두 번째 사건" }),
    ).toContainText("500,000원 · 이 반환의 대상 배분");
    expect(state.writes).toHaveLength(0);
    if (bridge) {
      expect(bridge.calls.some((row) => row.method === "getIncomeInsuranceSource")).toBe(true);
      expect(bridge.http).toEqual([]);
    }
  });
  test(`ended rule insurance link remains named and navigable ${native ? "native" : "web"}`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    state.ruleInsuranceLinks.set(uid(60), {
      rule_id: uid(60),
      link: {
        id: uid(100),
        policy_id: uid(80),
        product_name: "합성 종료 보험",
        insurer: "합성 보험사",
        policy_status: "ended",
        active: false,
        ended_at: "2025-02-01T00:00:00Z",
      },
    });
    const bridge = native ? await mockNativeCashflow(page, state) : null;
    await page.goto(`/fixed-payments/rules/${uid(60)}`);
    const region = page.getByRole("region", { name: "납부 규칙의 보험 계약" });
    await expect(
      region.getByRole("link", { name: "합성 종료 보험 · 합성 보험사" }),
    ).toHaveAttribute("href", `/insurance/policies/${uid(80)}`);
    await expect(region).toContainText("계약 종료 · 보험료 연결 종료");
    await expect(
      page.getByRole("link", { name: `${state.cards[0]!.alias} · 연결 카드 · 승인 계획` }).first(),
    ).toBeVisible();
    expect(state.writes).toHaveLength(0);
    if (bridge) {
      expect(bridge.calls.some((row) => row.method === "getRecurringRuleInsuranceLink")).toBe(true);
      expect(bridge.http).toEqual([]);
    }
  });
}
test("asset resolves a closed linked account after the first page", async ({ page }) => {
  const state = await mockCashflow(page);
  state.finance.assets[1]!.status = "archived";
  state.finance.assets[1]!.ended_on = "2025-02-01";
  state.finance.accounts = [
    { ...sampleAccount, id: uid(300), asset_id: uid(10) },
    { ...sampleAccount, status: "closed", closed_on: "2025-02-01" },
  ];
  let pages = 0;
  await page.route("**/api/v1/accounts?**", (route) => {
    pages++;
    const after = new URL(route.request().url()).searchParams.has("cursor");
    return route.fulfill({
      json: {
        items: [state.finance.accounts[after ? 1 : 0]],
        next_cursor: after ? null : uid(300),
      },
    });
  });
  await page.goto(`/assets/${uid(11)}`);
  const region = page.getByRole("region", { name: "자산의 연결 계좌" });
  await expect(region.getByRole("link")).toHaveAttribute("href", `/accounts/${uid(30)}`);
  await expect(region).toContainText("사용 종료");
  await expect(region).toContainText("한 번만 합산");
  expect(pages).toBeGreaterThanOrEqual(2);
});
test("a changed connection page requires retry instead of publishing a partial summary", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.linksRequired = true;
  state.linksMore = true;
  state.linksRace = true;
  await page.goto(`/cards/${uid(50)}`);
  const region = page.getByRole("region", { name: "정기 결제 연결" });
  await expect(region.getByRole("button", { name: "연결 기록 다시 확인" })).toBeVisible();
  await expect(region.getByText("연결 규칙 2개", { exact: false })).toHaveCount(0);
  await region.getByRole("button", { name: "연결 기록 다시 확인" }).click();
  await expect(region).toContainText("연결 규칙 2개");
  expect(state.writes).toHaveLength(0);
});
