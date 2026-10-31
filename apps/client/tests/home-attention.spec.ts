import { expect, test } from "@playwright/test";
import { completeOverdue } from "../src/features/dashboard/HomeAttention";
import { applianceRow, mockHomecare } from "./support/homecare";
import { mockNativeHomecare } from "./support/homecare-native";
import { obligationRow } from "./support/cashflow";
import { claimRow, expenseRow } from "./support/insurance-events";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-10-17T03:00:00Z"));
});
const group = (page: import("@playwright/test").Page, name: string) =>
  page.getByRole("region", { name, exact: true });
function setup(state: Awaited<ReturnType<typeof mockHomecare>>) {
  state.cashflow.overdueAsOf = "2026-10-17";
  state.cashflow.pageSize = 2;
  state.cashflow.obligations = Array.from({ length: 5 }, (_, index) =>
    obligationRow(70 + index, {
      title: `합성 미납 ${index}`,
      scheduled_date: index === 0 ? "2025-12-31" : "2026-10-16",
    }),
  );
  state.cashflow.obligations.push(
    obligationRow(80, { title: "합성 오늘 예정", scheduled_date: "2026-10-17" }),
  );
  state.previousMonthState = "reopened";
  state.insurance.pageSize = 2;
  state.insurance.claims = [0, 1, 2, 3].map((index) => ({
    ...claimRow(1200 + index),
    claim_state: "documents_required" as const,
  }));
  state.insurance.claims.push(claimRow(1290));
  state.insurance.expenses = [expenseRow(1000), expenseRow(1001), expenseRow(1002)];
  state.insurance.expenses[0]!.provider_name = "합성 연결 검토 병원";
  state.insurance.claims[0]!.expense_ids = [uid(1001)];
  state.insurance.expenses[2]!.cash.state = "void";
  state.appliances = [
    applianceRow(100, { warranty_until: "2026-10-17" }),
    applianceRow(101, { warranty_until: "2026-11-16" }),
    applianceRow(102, { warranty_until: "2026-11-17" }),
    applianceRow(103, { warranty_until: "2026-10-16" }),
    applianceRow(104, { warranty_until: null }),
  ];
  state.pageSize = 2;
}
for (const native of [false, true]) {
  test(`${native ? "native" : "web"} home tasks page through source states and keep warranty badge visible before expansion`, async ({
    page,
  }) => {
    const state = await mockHomecare(page);
    setup(state);
    const device = native ? await mockNativeHomecare(page, state) : null;
    await page.goto("/");
    await page.getByText("예정일과 진행 중인 기록 살펴보기", { exact: true }).click();
    const overdue = group(page, "지난 예정일 납부 확인");
    await expect(overdue).toContainText("5건");
    await expect(overdue.getByRole("link", { name: "합성 미납 0", exact: true })).toHaveAttribute(
      "href",
      `/fixed-payments/${uid(70)}`,
    );
    await expect(overdue.getByText("합성 오늘 예정", { exact: true })).toHaveCount(0);
    await overdue.getByText("나머지 2건 보기", { exact: true }).click();
    await expect(overdue.getByRole("link", { name: "합성 미납 4", exact: true })).toBeVisible();
    await expect(group(page, "지난달 월 기록")).toHaveCount(0);
    await expect(group(page, "추가 서류 필요 청구")).toContainText("4건");
    await expect(group(page, "청구 연결 검토 비용")).toContainText("1건");
    await expect(group(page, "청구 연결 검토 비용").getByRole("link")).toHaveAttribute(
      "href",
      `/insurance/expenses/${uid(1000)}`,
    );
    await expect(page.locator(".home-warranties")).not.toHaveAttribute("open", "");
    await expect(page.getByText("30일 내 보증 만료 2개", { exact: true })).toBeVisible();
    await page.getByLabel("확인할 월", { exact: true }).fill("2025-01");
    await expect(overdue).toContainText("5건");
    const primary = await page.getByRole("region", { name: "우리 집 보유 현황" }).boundingBox();
    const attention = await group(page, "확인할 일").boundingBox();
    expect(primary!.y + primary!.height).toBeLessThan(attention!.y + 1);
    expect(state.cashflow.writes).toHaveLength(0);
    expect(state.insurance.writes).toHaveLength(0);
    expect(state.writes).toHaveLength(0);
    if (device) {
      expect(device.http).toEqual([]);
      expect(
        device.calls.some(
          (call) => call.method === "listOverdueObligations" && call.args.query.cursor,
        ),
      ).toBe(true);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
  test(`${native ? "native" : "web"} original completion and source retry remove home tasks with no independent writes`, async ({
    page,
  }) => {
    const state = await mockHomecare(page);
    setup(state);
    const device = native ? await mockNativeHomecare(page, state) : null;
    let failed = false;
    if (!native)
      await page.route("**/api/v1/obligations/overdue*", async (route) => {
        if (failed)
          return route.fulfill({
            status: 503,
            json: { error: { code: "DATABASE_UNAVAILABLE", message: "synthetic" } },
          });
        const response = await state.cashflow.handle(
          "GET",
          "/api/v1/obligations/overdue",
          new URL(route.request().url()).searchParams,
          {},
          {},
        );
        return route.fulfill({ status: response!.status, json: response!.body });
      });
    await page.goto("/");
    await page.getByText("예정일과 진행 중인 기록 살펴보기", { exact: true }).click();
    const overdue = group(page, "지난 예정일 납부 확인");
    await expect(overdue).toContainText("5건");
    failed = true;
    if (device) {
      device.control.failure = "NETWORK_UNAVAILABLE";
      device.control.method = "listOverdueObligations";
    }
    await overdue.getByRole("button", { name: "지난 예정일 납부 확인 새로고침" }).click();
    await expect(overdue.getByRole("alert")).toBeVisible();
    await expect(overdue.getByRole("link")).toHaveCount(0);
    await expect(overdue).not.toContainText("0건");
    failed = false;
    if (device) device.control.failure = "";
    state.cashflow.obligations.forEach((row) => {
      row.status = "paid";
      row.manually_completed = true;
    });
    await overdue.getByRole("button", { name: "지난 예정일 납부 확인 새로고침" }).click();
    await expect(overdue).toContainText("지난 예정일의 미납·부분 납부가 없어요");
    state.previousMonthState = "confirmed";
    await expect(group(page, "지난달 월 기록")).toHaveCount(0);
    state.insurance.claims.forEach((row) => {
      row.claim_state = "reviewing";
    });
    await group(page, "추가 서류 필요 청구").getByRole("button").click();
    await expect(group(page, "추가 서류 필요 청구")).toContainText(
      "추가 서류가 필요한 청구가 없어요",
    );
    state.insurance.claims[0]!.expense_ids.push(uid(1000));
    await group(page, "청구 연결 검토 비용").getByRole("button").click();
    await expect(group(page, "청구 연결 검토 비용")).toContainText(
      "청구에 연결하지 않은 활성 의료비가 없어요",
    );
    expect(state.cashflow.writes).toHaveLength(0);
    expect(state.insurance.writes).toHaveLength(0);
    if (device) expect(device.http).toEqual([]);
  });
}
test("midnight between overdue pages fails rather than mixing days", async () => {
  let count = 0;
  await expect(
    completeOverdue(async () => ({
      as_of: ++count === 1 ? "2026-10-17" : "2026-10-18",
      items: [obligationRow(count)],
      next_cursor: count === 1 ? uid(1) : null,
    })),
  ).rejects.toMatchObject({ code: "VERSION_CONFLICT" });
});
