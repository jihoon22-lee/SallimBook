import { test, expect } from "@playwright/test";
import { mockFinance, uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test("expected baseline and stock award keep exact money and distinct cash confirmation", async ({
  page,
}) => {
  await mockFinance(page);
  const expected: any[] = [],
    bonuses: any[] = [],
    writes: any[] = [];
  const stamp = "2026-01-01T00:00:00Z";
  await page.route("**/api/v1/income-planning/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const rows = path.includes("/expected") ? expected : bonuses;
    if (route.request().method() === "GET")
      return route.fulfill({ json: { items: rows, next_cursor: null } });
    const body = route.request().postDataJSON();
    writes.push({ path, body });
    const row = {
      ...body,
      id: uid(900 + writes.length),
      household_id: uid(3),
      version: 1,
      created_at: stamp,
      updated_at: stamp,
      created_by_member_id: uid(2),
      updated_by_member_id: uid(2),
      ...(rows === bonuses ? { cash_record_id: uid(950) } : {}),
    };
    rows.push(row);
    return route.fulfill({ status: 201, json: row });
  });
  await page.goto("/income/planning");
  await page.getByRole("button", { name: "예상 수입 추가", exact: true }).click();
  await page.getByLabel("구성원", { exact: true }).selectOption(uid(2));
  await page.getByLabel("수입 항목", { exact: true }).fill("합성 월급");
  await page.getByLabel("예상 월 금액", { exact: true }).fill("9007199254740993");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByText(/확인된 예상 합계 9,007,199,254,740,993원/)).toBeVisible();
  expect(writes[0].body.amount_krw).toBe("9007199254740993");
  expect(writes[0].body).not.toHaveProperty("received");
  await page.getByRole("button", { name: "상여 상세 추가", exact: true }).click();
  await page.getByLabel("구성원", { exact: true }).selectOption(uid(2));
  await page.getByLabel("성과연도", { exact: true }).fill("2022");
  await page.getByLabel("상여 구분", { exact: true }).selectOption("opi");
  await page.getByLabel("실제 지급월", { exact: true }).fill("2023-01");
  await page.getByLabel("세전 금액", { exact: true }).fill("5000000");
  await page.getByLabel("세후 현금", { exact: true }).fill("3000000");
  await page.getByLabel("수령 당시 주식 평가액", { exact: true }).fill("1000000");
  await page.getByLabel("지급률 (%)", { exact: true }).fill("37.5");
  await page
    .getByLabel("실제 수령을 확인했으며, 양수 세후 현금을 지급월 수입에 연결할게요")
    .check();
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("region", { name: "2022년 성과 상여" })).toContainText(
    "합계 4,000,000원",
  );
  expect(writes[1].body).toMatchObject({
    performance_year: 2022,
    payment_month: "2023-01",
    net_cash_krw: "3000000",
    stock_grant_value_krw: "1000000",
    payout_rate_percent: "37.5",
    received: true,
  });
});

test("editing an expected baseline saves once without a mandatory explanation", async ({
  page,
}) => {
  await mockFinance(page);
  const stamp = "2026-01-01T00:00:00Z";
  let row = {
    id: uid(960),
    household_id: uid(3),
    member_id: uid(2),
    label: "합성 월급",
    amount_krw: "2500000",
    active: true,
    note: null,
    version: 1,
    created_at: stamp,
    updated_at: stamp,
    created_by_member_id: uid(2),
    updated_by_member_id: uid(2),
  };
  const writes: any[] = [];
  await page.route("**/api/v1/income-planning/**", (route) => {
    if (route.request().method() === "GET")
      return route.fulfill({
        json: {
          items: route.request().url().includes("/expected") ? [row] : [],
          next_cursor: null,
        },
      });
    const body = route.request().postDataJSON();
    writes.push(body);
    row = { ...row, ...body, version: 2 };
    return route.fulfill({ json: row });
  });
  await page.goto("/income/planning");
  await page.getByRole("button", { name: "예상 수입 수정", exact: true }).click();
  await page.getByLabel("예상 월 금액", { exact: true }).fill("2700000");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByText(/확인된 예상 합계 2,700,000원/)).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0].reason).toBe("예상 월 수입 수정");
});
