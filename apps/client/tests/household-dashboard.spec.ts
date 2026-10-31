import { expect, test } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";
import { mockComparison } from "./support/comparison";
import { members, uid } from "./support/finance";
const expected = {
  known_amount_krw: "6300000",
  record_count: 3,
  unknown_count: 0,
  members: [
    { member_id: uid(2), known_amount_krw: "2500000", record_count: 1, unknown_count: 0 },
    { member_id: uid(5), known_amount_krw: "3800000", record_count: 2, unknown_count: 0 },
  ],
};
const totals = {
  salary_krw: "0",
  bonus_krw: "0",
  other_income_krw: "0",
  income_returns_krw: "0",
  insurance_receipts_krw: "0",
  insurance_returns_krw: "0",
  earned_net_krw: "0",
  insurance_net_krw: "0",
  net_inflow_krw: "0",
  record_count: 0,
};
for (const path of ["/", "/income"]) {
  test(`current expected income is visible immediately with no cash records at ${path}`, async ({
    page,
  }) => {
    if (path === "/income") await mockCashflow(page);
    else await mockComparison(page);
    const writes: string[] = [];
    page.on("request", (req) => {
      if (["POST", "PUT", "PATCH", "DELETE"].includes(req.method())) writes.push(req.url());
    });
    await page.route("**/api/v1/income/summary?*", (route) =>
      route.fulfill({
        json: {
          period_month: new URL(route.request().url()).searchParams.get("month"),
          totals,
          members: [],
          expected,
        },
      }),
    );
    await page.route("**/api/v1/income?*", (route) =>
      route.fulfill({ json: { items: [], next_cursor: null } }),
    );
    await page.goto(path);
    const baseline = page.getByRole("region", { name: "현재 예상 월 수입", exact: true });
    await expect(baseline).toContainText("6,300,000원");
    await expect(baseline).toContainText("2,500,000원");
    await expect(baseline).toContainText("3,800,000원");
    await expect(baseline).toContainText(members[0]!.display_name);
    await expect(baseline.getByRole("link", { name: "수입 기준 수정" })).toHaveAttribute(
      "href",
      "/income/planning",
    );
    if (path === "/") {
      await expect(page.getByRole("region", { name: "우리 집 보유 현황" })).toBeVisible();
      await expect(page.getByRole("region", { name: "계좌·연금", exact: true })).toContainText(
        "합성 개인 금융 자산",
      );
      await expect(page.getByRole("heading", { name: "지난달 월 기록", exact: true })).toHaveCount(
        0,
      );
      await expect(
        page.getByRole("heading", { name: "자산의 변화", exact: true }),
      ).not.toBeVisible();
    }
    expect(writes).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}
test("saved draft amounts appear in asset and account lists before month confirmation", async ({
  page,
}) => {
  const state = await mockComparison(page);
  state.mode = "unconfirmed";
  await page.goto("/assets");
  const property = page
    .locator(".asset-record")
    .filter({ has: page.getByRole("link", { name: "합성 공동 주택", exact: true }) });
  await expect(property).toContainText("1,000원");
  await expect(property).toContainText("2025.02.20 기준");
  await expect(property.getByRole("button", { name: "금액 입력·수정", exact: true })).toBeVisible();
  await page.goto("/accounts");
  await expect(
    page.locator(".finance-list > li").filter({ hasText: "합성 개인 금융 자산" }),
  ).toContainText("120원");
});
test("unknown expected amounts stay unknown rather than a zero household income", async ({
  page,
}) => {
  await mockCashflow(page);
  await page.route("**/api/v1/income/summary?*", (route) =>
    route.fulfill({
      json: {
        period_month: new URL(route.request().url()).searchParams.get("month"),
        totals,
        members: [],
        expected: {
          known_amount_krw: "0",
          record_count: 1,
          unknown_count: 1,
          members: [{ ...expected.members[0], known_amount_krw: "0", unknown_count: 1 }],
        },
      },
    }),
  );
  await page.goto("/income");
  const baseline = page.getByRole("region", { name: "현재 예상 월 수입", exact: true });
  await expect(baseline).toContainText("금액 미입력");
  await expect(baseline).not.toContainText("0원");
});

test("first asset amount saves from the list without a month setup or confirmation checklist", async ({
  page,
}) => {
  const comparison = await mockComparison(page);
  const { mockMonths } = await import("./support/months");
  const months = await mockMonths(page);
  months.record = null;
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
  await page.route("**/api/v1/asset-comparison?*", (route) => {
    comparison.mode = months.record ? "unconfirmed" : "current_missing";
    if (months.record) comparison.after = months.record.values;
    return route.fulfill({
      json: comparison.response(new URL(route.request().url()).searchParams),
    });
  });
  await page.goto("/assets");
  const asset = page
    .locator(".asset-record")
    .filter({ has: page.getByRole("link", { name: "합성 공동 주택", exact: true }) });
  await asset.getByRole("button", { name: "금액 입력·수정", exact: true }).click();
  const editor = page.getByRole("region", { name: "목록에서 금액 수정" });
  await editor.getByLabel("확인 금액 (원)", { exact: true }).fill("3000");
  await expect(editor.getByLabel("실제 확인 기준일")).toHaveValue("2025-02-20");
  await expect(editor.getByRole("button", { name: "저장 후 다음 미확인 항목" })).toHaveCount(0);
  await expect(page.getByLabel("확인할 월", { exact: true })).toBeDisabled();
  for (const button of await page
    .getByRole("button", { name: "금액 입력·수정", exact: true })
    .all())
    await expect(button).toBeDisabled();
  await editor.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(asset).toContainText("1,500원");
  expect(months.writes.map((write) => write.operation)).toEqual(["draft", "values"]);
  expect(months.record!.state).toBe("draft");
  expect(months.record!.values[0]!.input_amount_krw).toBe("3000");
});

test("quick amount entry preserves a confirmed month and offers its correction path", async ({
  page,
}) => {
  const comparison = await mockComparison(page);
  const { mockMonths } = await import("./support/months");
  const months = await mockMonths(page);
  months.record!.state = "confirmed";
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
  await page.route("**/api/v1/asset-comparison?*", (route) =>
    route.fulfill({ json: comparison.response(new URL(route.request().url()).searchParams) }),
  );
  await page.goto("/accounts");
  await page.getByRole("button", { name: "금액 입력·수정", exact: true }).click();
  await expect(page.getByText(/이미 마감한 달이에요/)).toBeVisible();
  await expect(page.getByRole("link", { name: "월 기록 열기" })).toHaveAttribute(
    "href",
    new RegExp(`asset_id=${uid(11)}`),
  );
  expect(months.writes).toEqual([]);
});

test("Android dashboard shows the same current income without browser API requests", async ({
  page,
}) => {
  const { mockHomecare } = await import("./support/homecare");
  const { mockNativeHomecare } = await import("./support/homecare-native");
  const state = await mockHomecare(page);
  const handle = state.cashflow.handle;
  state.cashflow.handle = async (...args) => {
    const response = await handle(...args);
    if (args[1] === "/api/v1/income/summary" && response?.status === 200)
      return { ...response, body: { ...(response.body as object), expected } };
    return response;
  };
  const native = await mockNativeHomecare(page, state);
  native.control.maxPending = 8;
  native.control.delayAllMs = 80;
  await page.goto("/");
  await expect(page.getByRole("region", { name: "현재 예상 월 수입", exact: true })).toContainText(
    "6,300,000원",
  );
  await expect(page.getByLabel("오늘 소모품 보기")).toBeVisible();
  await expect(page.getByRole("region", { name: "계좌·연금", exact: true })).toContainText(
    "아직 등록한 항목이 없어요",
  );
  await expect(page.getByRole("region", { name: "부동산", exact: true })).toContainText(
    "아직 등록한 항목이 없어요",
  );
  expect(native.control.rejected).toBe(0);
  expect(native.control.peakPending).toBeLessThanOrEqual(4);
  expect(native.http).toEqual([]);
  expect(native.calls.some((call) => call.method === "incomeSummary")).toBe(true);
});

test("an open amount draft survives a list reload and the Seoul month rollover", async ({
  page,
}) => {
  const comparison = await mockComparison(page);
  const { mockMonths } = await import("./support/months");
  const months = await mockMonths(page);
  await page.clock.setFixedTime(new Date("2025-02-28T14:59:00Z"));
  await page.route("**/api/v1/asset-comparison?*", (route) =>
    route.fulfill({ json: comparison.response(new URL(route.request().url()).searchParams) }),
  );
  await page.goto("/assets");
  await page
    .locator(".asset-record")
    .first()
    .getByRole("button", { name: "금액 입력·수정", exact: true })
    .click();
  const editor = page.getByRole("region", { name: "목록에서 금액 수정" });
  await editor.getByLabel("확인 금액 (원)", { exact: true }).fill("3000");
  await editor.getByLabel("실제 확인 기준일").fill("2025-02-28");
  await page.locator(".asset-filter-panel > summary").click();
  await page.getByRole("button", { name: "자산 목록 다시 불러오기", exact: true }).click();
  await expect(editor.getByLabel("확인 금액 (원)", { exact: true })).toHaveValue("3000");
  await page.clock.setFixedTime(new Date("2025-02-28T15:01:00Z"));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByLabel("확인할 월", { exact: true })).toHaveValue("2025-03");
  await expect(editor).toContainText("2025년 2월 금액을 수정하고 있어요.");
  await expect(editor.getByLabel("확인 금액 (원)", { exact: true })).toHaveValue("3000");
  await editor.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(editor).toHaveCount(0);
  expect(months.record!.month).toBe("2025-02");
  expect(months.record!.values[0]!.input_amount_krw).toBe("3000");
});

test("locking the app discards queued dashboard reads before another native call starts", async ({
  page,
}) => {
  const { mockHomecare } = await import("./support/homecare");
  const { mockNativeHomecare } = await import("./support/homecare-native");
  const native = await mockNativeHomecare(page, await mockHomecare(page));
  native.control.maxPending = 8;
  native.control.delayAllMs = 250;
  await page.goto("/");
  await expect.poll(() => native.control.pending).toBe(4);
  const started = native.control.started;
  await native.lock();
  await expect(page.getByRole("status").filter({ hasText: "앱이 잠겨 있어요" })).toBeVisible();
  await expect.poll(() => native.control.pending).toBe(0);
  expect(native.control.started).toBe(started);
  expect(native.control.rejected).toBe(0);
  expect(native.http).toEqual([]);
});
