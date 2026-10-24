import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import catalog from "../../../packages/test-fixtures/catalog.json" with { type: "json" };
import { mockOrders } from "./support/consumable-orders";
import { mockNativeHomecare } from "./support/homecare-native";
import { consumableRow } from "./support/homecare";
import { uid } from "./support/finance";
import { completePlan } from "../src/features/homecare/orders/model";
test.use({ trace: "off", screenshot: "off", video: "off" });
async function ordered(page: Page) {
  await page.getByRole("button", { name: "실제 주문 확인", exact: true }).click();
  await page.getByLabel("실제 주문일", { exact: true }).fill("2026-10-17");
  await page.getByLabel("판매처에서 실제 주문을 완료한 것을 확인했어요").check();
  await page.getByRole("button", { name: "주문 중으로 저장", exact: true }).click();
  await expect(page.getByRole("region", { name: "소모품 주문 원본" })).toContainText("주문 중");
}
for (const native of [false, true]) {
  const mode = native ? "native" : "web";
  test(`${mode}: shared fixture plan, one retry-safe order and one physical receipt`, async ({
    page,
  }) => {
    await page.clock.setFixedTime(new Date("2026-10-17T01:00:00Z"));
    const { state, orders, control } = await mockOrders(page);
    const bridge = native ? await mockNativeHomecare(page, state) : null;
    await page.goto("/purchase-plan?through=2026-11-16");
    const row = page.getByRole("listitem", { name: "합성 공용 필터 구매 계획", exact: true });
    const fixture = catalog.edge_cases.shared_purchase_plan;
    await expect(row.locator("dl > div").filter({ hasText: "확인된 기간 수요" })).toContainText(
      `${fixture.expected.demand_quantity} 개`,
    );
    await expect(row.locator("dl > div").filter({ hasText: "현재 재고로 부족" })).toContainText(
      `${fixture.expected.shortage_quantity} 개`,
    );
    await expect(row.getByRole("link", { name: "마지막 구매 링크", exact: true })).toHaveAttribute(
      "href",
      "https://example.test/filter",
    );
    await row.getByText("기기별 수요 근거", { exact: true }).click();
    await expect(row).toContainText("합성 거실 청정기");
    await expect(row).toContainText("합성 안방 청정기");
    await row.getByRole("link", { name: "구매 예정 추가", exact: true }).click();
    await expect(page.getByLabel("구매 수량 (개)", { exact: true })).toHaveValue("1");
    await expect(page.getByLabel("단위당 참고 가격 (원, 선택)", { exact: true })).toHaveValue("0");
    control.failAfter = "create";
    await page.getByRole("button", { name: "구매 예정 저장", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByLabel("구매 수량 (개)", { exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "같은 구매 예정 다시 확인", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "소모품 주문 상세", exact: true }),
    ).toBeVisible();
    expect(orders).toHaveLength(1);
    expect(state.consumables[0]!.stock_quantity).toBe(1);
    await ordered(page);
    expect(state.consumables[0]!.stock_quantity).toBe(1);
    await page.getByRole("button", { name: "전체 입고 확인", exact: true }).click();
    await page.getByLabel("실제 입고일", { exact: true }).fill("2026-10-17");
    await page.getByLabel("표시된 전체 수량이 도착했고 재고에 더할 것을 확인했어요").check();
    control.failAfter = "receive";
    await page.getByRole("button", { name: "전체 입고·재고 저장", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "같은 주문 처리 다시 확인", exact: true }).click();
    await expect(page.getByRole("region", { name: "소모품 주문 원본" })).toContainText("입고 완료");
    await expect(page.getByRole("region", { name: "소모품 주문 원본" })).toContainText(
      "현재 합성 공용 필터 공용 재고: 2 개",
    );
    expect(state.consumables[0]!.stock_quantity).toBe(2);
    for (const suffix of ["/api/v1/consumable-orders", "/receive"]) {
      const writes = state.writes.filter((write) => write.path.endsWith(suffix));
      expect(writes).toHaveLength(2);
      expect(writes[1]!.key).toBe(writes[0]!.key);
    }
    await expect(
      page.getByRole("link", { name: "시작 화면으로 돌아가기", exact: true }),
    ).toHaveAttribute("href", "/purchase-plan?through=2026-11-16");
    await page.getByRole("link", { name: "시작 화면으로 돌아가기", exact: true }).click();
    await expect(row.locator("dl > div").filter({ hasText: "현재 재고로 부족" })).toContainText(
      "0 개",
    );
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    if (bridge) expect(bridge.http).toEqual([]);
  });
  test(`${mode}: edit and stock conflicts preserve drafts until explicit comparison`, async ({
    page,
  }) => {
    await page.clock.setFixedTime(new Date("2026-10-17T01:00:00Z"));
    const { state, orders, control, orderRow } = await mockOrders(page);
    orders.push(orderRow(2100, uid(200)));
    const bridge = native ? await mockNativeHomecare(page, state) : null;
    await page.goto(`/consumable-orders/${uid(2100)}`);
    await page.getByRole("button", { name: "주문 내용 수정", exact: true }).click();
    await page.getByLabel("구매 수량 (개)", { exact: true }).fill("4");
    control.conflict = "edit";
    await page.getByRole("button", { name: "주문 내용 저장", exact: true }).click();
    await expect(page.getByLabel("구매 수량 (개)", { exact: true })).toHaveValue("4");
    await page.getByRole("button", { name: "현재 주문과 비교", exact: true }).click();
    await expect(page.getByRole("region", { name: "주문 내용 충돌 비교" })).toContainText(
      "합성 배우자 메모",
    );
    await expect(page.getByRole("button", { name: "주문 내용 저장", exact: true })).toBeDisabled();
    await page
      .getByRole("button", { name: "내 수정만 유지하고 현재 내용 반영", exact: true })
      .click();
    await expect(page.getByLabel("주문 메모 (선택)", { exact: true })).toHaveValue(
      "합성 배우자 메모",
    );
    await page.getByRole("button", { name: "주문 내용 저장", exact: true }).click();
    await expect.poll(() => orders[0]!.quantity).toBe(4);
    expect(orders[0]!.note).toBe("합성 배우자 메모");
    await ordered(page);
    await page.getByRole("button", { name: "전체 입고 확인", exact: true }).click();
    await page.getByLabel("실제 입고일", { exact: true }).fill("2026-10-17");
    await page.getByLabel("표시된 전체 수량이 도착했고 재고에 더할 것을 확인했어요").check();
    control.conflict = "receive";
    await page.getByRole("button", { name: "전체 입고·재고 저장", exact: true }).click();
    await expect(page.getByLabel("실제 입고일", { exact: true })).toHaveValue("2026-10-17");
    await page.getByRole("button", { name: "현재 주문·재고와 비교", exact: true }).click();
    await expect(page.getByRole("region", { name: "주문·재고 충돌 비교" })).toContainText(
      "4 · 5 개",
    );
    await page.getByRole("button", { name: "확인한 현재 기록으로 다시 검토", exact: true }).click();
    await expect(
      page.getByLabel("표시된 전체 수량이 도착했고 재고에 더할 것을 확인했어요"),
    ).not.toBeChecked();
    await page.getByLabel("표시된 전체 수량이 도착했고 재고에 더할 것을 확인했어요").check();
    await page.getByRole("button", { name: "전체 입고·재고 저장", exact: true }).click();
    await expect.poll(() => state.consumables[0]!.stock_quantity).toBe(7);
    expect(
      state.writes.filter((write) => write.path.endsWith("/receive")).map((write) => write.version),
    ).toEqual(['"4"', '"5"']);
    if (bridge) expect(bridge.http).toEqual([]);
  });
  test(`${mode}: cancelled plans leave stock unchanged and remain available in history`, async ({
    page,
  }) => {
    const { state, orders, orderRow } = await mockOrders(page);
    orders.push(orderRow(2100, uid(200)));
    const bridge = native ? await mockNativeHomecare(page, state) : null;
    await page.goto(`/consumable-orders/${uid(2100)}`);
    await page.getByRole("button", { name: "주문 취소 검토", exact: true }).click();
    await page.getByLabel("주문 취소 사유", { exact: true }).fill("합성 중복 계획 취소");
    await page.getByRole("button", { name: "주문 취소 저장", exact: true }).click();
    await expect(page.getByRole("region", { name: "소모품 주문 원본" })).toContainText("취소됨");
    expect(state.consumables[0]!.stock_quantity).toBe(1);
    await page.goto("/consumable-orders");
    await expect(page.getByText(/이 조건의 구매·주문 기록이 없어요/)).toBeVisible();
    await page.getByLabel("구매·주문 상태", { exact: true }).selectOption("cancelled");
    await page.getByRole("link", { name: "합성 공용 필터 · 1 개", exact: true }).click();
    await expect(page.getByRole("region", { name: "소모품 주문 원본" })).toContainText(
      "합성 중복 계획 취소",
    );
    if (bridge) expect(bridge.http).toEqual([]);
  });
}

test("planning reads all pages and unknown schedules or read errors are never a zero claim", async ({
  page,
}) => {
  const { state, control } = await mockOrders(page);
  state.consumables.push(consumableRow(201, { name: "합성 다른 필터" }));
  state.pageSize = 1;
  control.unknown = true;
  await page.goto("/purchase-plan");
  await expect(
    page
      .getByRole("listitem")
      .filter({ has: page.getByRole("heading", { name: "합성 공용 필터", exact: true }) }),
  ).toContainText("다음 확인일 미정 1개 연결");
  expect(state.reads.some((read) => read.query.has("cursor"))).toBe(true);
  control.planFailure = true;
  await page.getByRole("button", { name: "구매 계획 새로고침", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("listitem", { name: "합성 공용 필터 구매 계획", exact: true }),
  ).toHaveCount(0);
  control.planFailure = false;
  control.dateRace = true;
  await page.getByRole("button", { name: "현재 기록 다시 확인", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("listitem", { name: "합성 공용 필터 구매 계획", exact: true }),
  ).toHaveCount(0);
});

test("server order search finds records outside the first page and preserves its filter", async ({
  page,
}) => {
  const { state, orders, orderRow } = await mockOrders(page);
  state.consumables.push(consumableRow(201, { name: "합성 찾을 필터" }));
  for (let n = 0; n < 55; n++) orders.push(orderRow(3000 + n, uid(200)));
  orders.push(orderRow(3999, uid(201)));
  await page.goto("/consumable-orders");
  await expect(page.getByRole("link", { name: "합성 찾을 필터 · 1 개", exact: true })).toHaveCount(
    0,
  );
  await page
    .getByRole("searchbox", { name: "주문 소모품 이름·규격 검색", exact: true })
    .fill("찾을");
  await page.getByRole("button", { name: "이름 검색", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "합성 찾을 필터 · 1 개", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("searchbox", { name: "주문 소모품 이름·규격 검색", exact: true }),
  ).toHaveValue("찾을");
});

test("native purchase-plan failure never falls back to WebView HTTP", async ({ page }) => {
  const { state } = await mockOrders(page);
  const bridge = await mockNativeHomecare(page, state);
  bridge.control.failure = "NETWORK_UNAVAILABLE";
  bridge.control.method = "getPurchasePlan";
  await page.goto("/purchase-plan");
  await expect(page.getByRole("alert")).toBeVisible();
  expect(bridge.calls.some((call) => call.method === "getPurchasePlan")).toBe(true);
  expect(bridge.http).toEqual([]);
});

test("cross-midnight planning pages refuse to combine different date bases", async () => {
  const first = { as_of: "2026-10-17", through: "2026-10-17", items: [], next_cursor: uid(1) };
  await expect(
    completePlan(async (cursor) =>
      cursor ? { ...first, as_of: "2026-10-18", next_cursor: null } : first,
    ),
  ).rejects.toMatchObject({ status: 409 });
});

test("narrow enlarged dark purchase forms keep controls and explicit validation usable", async ({
  page,
}) => {
  const { state } = await mockOrders(page);
  state.consumables[0]!.name = "합성 긴 공용 소모품 이름 ".repeat(5).trim();
  await page.setViewportSize({ width: 320, height: 800 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/purchase-plan");
  await page.addStyleTag({ content: ":root { font-size: 20px; }" });
  await page.getByRole("link", { name: "구매 예정 추가", exact: true }).click();
  await page.getByLabel("구매 수량 (개)", { exact: true }).fill("0");
  await expect(page.getByRole("button", { name: "구매 예정 저장", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "구매 예정 저장", exact: true }).click();
  await expect(
    page.getByText("1 이상 1,000,000 이하 정수로 입력해 주세요.", { exact: true }),
  ).toBeVisible();
  expect(state.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
