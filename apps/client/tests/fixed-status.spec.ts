import { expect, test } from "@playwright/test";
import { mockCashflow, obligationRow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { uid } from "./support/finance";

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
for (const native of [false, true]) {
  test(`${native ? "native" : "web"} unpaid dates are plans and variable paid keeps the additional-payment check`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    state.obligations = [
      obligationRow(270, { title: "합성 미래 예정", scheduled_date: "2025-02-28" }),
      obligationRow(271, { title: "합성 지난 예정", scheduled_date: "2025-02-10" }),
      obligationRow(272, { title: "합성 오늘 예정", scheduled_date: "2025-02-20" }),
      obligationRow(273, {
        title: "합성 변동 납부",
        amount_mode: "variable",
        expected_amount_krw: null,
        difference_krw: null,
        status: "paid",
        actual_amount_krw: "12000",
        consumption_krw: "12000",
      }),
    ];
    state.obligations.forEach((row) => state.rememberObligation(row, "create"));
    const bridge = native ? await mockNativeCashflow(page, state) : null;
    await page.goto("/fixed-payments?view=payments");
    for (const [title, status] of [
      ["합성 미래 예정", "납부 예정"],
      ["합성 지난 예정", "예정일 지남 · 확인 필요"],
      ["합성 오늘 예정", "오늘 예정 · 납부 확인 전"],
      ["합성 변동 납부", "납부 확인 · 예정액 미정"],
    ]) {
      await expect(
        page
          .getByRole("listitem")
          .filter({ has: page.getByRole("link", { name: title, exact: true }) }),
      ).toContainText(status!);
    }
    expect(state.writes).toHaveLength(0);
    await page.goto(`/fixed-payments/${uid(273)}?task=settle`);
    await expect(
      page.getByRole("heading", { name: "이미 납부를 마친 회차예요", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "추가 납부 입력 계속", exact: true }),
    ).toBeDisabled();
    await expect(page.getByLabel("실제 납부금액 (원)", { exact: true })).toHaveCount(0);
    if (bridge) expect(bridge.http).toEqual([]);
  });
}

test("a fixed refresh keeps the list and summary but a different month never shows the old month's amount", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  let armed = false,
    release = () => {};
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route(/\/api\/v1\/obligations(?:\/summary)?\?/, async (route) => {
    if (armed) await gate;
    await route.fallback();
  });
  await page.goto("/fixed-payments?view=payments");
  const summary = page.getByRole("region", { name: "고정 납부 월 요약", exact: true });
  await expect(summary).toContainText("1,033,000원");
  const link = page.getByRole("link", { name: "합성 AI 구독", exact: true });
  const node = await link.elementHandle();
  armed = true;
  await page.getByRole("button", { name: "월 납부 목록 다시 확인", exact: true }).click();
  await expect(summary).toHaveAttribute("aria-busy", "true");
  await expect(summary).toContainText("1,033,000원");
  expect(await node!.evaluate((n) => n.isConnected)).toBe(true);
  release();
  await expect(summary).toHaveAttribute("aria-busy", "false");
  state.obligations = [];
  await page.getByLabel("확인할 월", { exact: true }).fill("2025-03");
  await expect(summary).not.toContainText("1,033,000원");
});

test("fixed detail remains mounted while a stale read refreshes", async ({ page }) => {
  await mockCashflow(page);
  let release = () => {},
    armed = false;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route(`**/api/v1/obligations/${uid(70)}`, async (route) => {
    if (armed) await gate;
    await route.fallback();
  });
  await page.goto(`/fixed-payments/${uid(70)}`);
  const heading = page.getByRole("heading", { name: "합성 AI 구독", exact: true });
  await expect(heading).toBeVisible();
  const node = await heading.elementHandle();
  armed = true;
  await page.clock.setFixedTime(new Date("2025-02-20T03:03:00Z"));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByText("납부 회차를 다시 확인하고 있어요.", { exact: true })).toBeVisible();
  expect(await node!.evaluate((n) => n.isConnected)).toBe(true);
  await expect(page.getByRole("button", { name: "실제 납부 기록", exact: true })).toBeDisabled();
  release();
  await expect(page.getByRole("button", { name: "실제 납부 기록", exact: true })).toBeEnabled();
});
