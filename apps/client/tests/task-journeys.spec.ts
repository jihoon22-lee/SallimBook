import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { mockFinance, uid } from "./support/finance";
import { mockInsuranceEvents, claimRow } from "./support/insurance-events";
import { mockHomecare } from "./support/homecare";
import { mockMonths } from "./support/months";
import { openDisclosure } from "./support/task-ui";

test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-28T03:00:00Z"));
});

async function noOverflow(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

async function withinMobileWorkArea(page: Page, control: Locator) {
  const rect = await control.boundingBox();
  const nav = await page.locator("nav.mobile-tabs").boundingBox();
  expect(rect!.height).toBeGreaterThanOrEqual(48);
  if (nav) expect(rect!.y + rect!.height).toBeLessThanOrEqual(nav.y);
}

test("a monthly payment opens directly from its list and saves one actual principal and interest payment", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto("/fixed-payments?view=payments");
  const loan = page
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: "합성 대출 원리금", exact: true }) });
  await expect(loan.getByText("납부 성격·수단·차액 상세", { exact: true })).toBeVisible();
  await loan.getByRole("link", { name: "납부 기록", exact: true }).click();
  await expect(page.getByRole("region", { name: "실제 납부 입력", exact: true })).toBeFocused();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill("1000000");
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-28");
  await page.getByLabel("실제 원금 상환액 (원)", { exact: true }).fill("700000");
  await page.getByLabel("실제 이자 (원)", { exact: true }).fill("300000");
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await expect(
    page.getByText("실제 납부를 저장했어요. 아래 납부 내역에서 확인할 수 있어요.", { exact: true }),
  ).toBeFocused();
  await expect(page).not.toHaveURL(/task=/);
  expect(state.payments).toHaveLength(1);
  expect(state.payments[0]).toMatchObject({
    principal_krw: "700000",
    consumption_krw: "300000",
    asset_transfer_krw: "0",
  });
  expect(state.writes).toHaveLength(1);
});

test("payment management stays secondary and cancelling returns keyboard focus without a write", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto(`/fixed-payments/${uid(70)}`);
  await withinMobileWorkArea(
    page,
    page.getByRole("button", { name: "실제 납부 기록", exact: true }),
  );
  await expect(page.getByRole("button", { name: "예정일 변경", exact: true })).toBeHidden();
  await openDisclosure(page, "예정일 변경·회차 관리");
  const trigger = page.getByRole("button", { name: "예정일 변경", exact: true });
  await trigger.click();
  await expect(
    page.getByRole("region", { name: "납부 회차 변경 입력", exact: true }),
  ).toBeFocused();
  await page.getByLabel("변경할 예정일", { exact: true }).fill("2025-03-05");
  await page.getByRole("button", { name: "납부 작업 닫기", exact: true }).click();
  await expect(trigger).toBeFocused();
  expect(state.writes).toHaveLength(0);
});

test("income search shows its applied scope while the household summary remains unchanged", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto("/income");
  await expect(page.getByRole("combobox", { name: "수입 구성원 필터", exact: true })).toBeHidden();
  await openDisclosure(page, "수입 기록 찾기");
  await page.getByRole("combobox", { name: "수입 구성원 필터", exact: true }).selectOption(uid(2));
  await expect(page.locator(".filter-panel > summary")).toContainText("조건 1개 적용");
  await page.reload();
  await openDisclosure(page, "수입 기록 찾기");
  await expect(page.getByRole("combobox", { name: "수입 구성원 필터", exact: true })).toHaveValue(
    uid(2),
  );
  await expect(page.getByRole("region", { name: "등록 수입 요약", exact: true })).toContainText(
    "4,000,000원",
  );
  await page.getByRole("button", { name: "수입 필터 초기화", exact: true }).click();
  await expect(page.locator(".filter-panel > summary")).toContainText("활성 기록");
  expect(state.writes).toHaveLength(0);
});

test("a failed account list can be retried without discovering a hidden filter panel", async ({
  page,
}) => {
  await mockFinance(page);
  let failed = true;
  await page.route("**/api/v1/accounts?*", async (route) =>
    failed
      ? route.fulfill({
          status: 503,
          json: { error: { code: "UNAVAILABLE", message: "synthetic", request_id: "synthetic" } },
        })
      : route.fallback(),
  );
  await page.goto("/accounts");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator(".filter-panel")).not.toHaveAttribute("open", "");
  failed = false;
  await page.getByRole("button", { name: "계좌 다시 확인", exact: true }).click();
  await expect(page.getByRole("link", { name: "합성 개인 금융 자산", exact: true })).toBeVisible();
});

test("a card type filter remains visible as applied even without an owner or settlement account filter", async ({
  page,
}) => {
  await mockCashflow(page);
  await page.goto("/cards?type=credit");
  await page.locator(".filter-panel > summary").click();
  await expect(page.locator(".filter-panel > summary")).toContainText("조건 1개 적용");
  await expect(page.getByRole("combobox", { name: "카드 유형 필터", exact: true })).toHaveValue(
    "credit",
  );
  await expect(page.getByText("•••• 1111", { exact: true })).toBeVisible();
});

test("monthly confirmation uses the compact amount row and keeps its saved ownership available", async ({
  page,
}) => {
  const state = await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  const card = page
    .locator(".month-value-card")
    .filter({ has: page.getByRole("heading", { name: "합성 공동 주택", exact: true }) });
  await expect(card.locator("details")).not.toHaveAttribute("open", "");
  await expect(card).toContainText("불러온 값 · 미확인");
  await card.getByRole("button", { name: "합성 공동 주택 금액 확인", exact: true }).click();
  await page.getByLabel("입력 방식", { exact: true }).selectOption("unchanged");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(page.getByText("확인한 금액과 기준일을 저장했어요.", { exact: true })).toBeVisible();
  await card.locator("summary").click();
  await expect(card.locator("details")).toHaveAttribute("open", "");
  await expect(card.locator("details")).toContainText("50%");
  expect(state.writes).toHaveLength(1);
  expect(state.writes[0]!.body.unchanged).toBe(true);
});

test("the first-screen month action advances through unverified included assets without editing an excluded row", async ({
  page,
}) => {
  const state = await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  const next = page.getByRole("button", { name: "미확인 항목 확인하기", exact: true });
  await withinMobileWorkArea(page, next);
  await next.click();
  await expect(
    page.getByRole("heading", { name: "합성 공동 주택 금액 확인", exact: true }),
  ).toBeVisible();
  await page.getByLabel("입력 방식", { exact: true }).selectOption("unchanged");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await next.click();
  await expect(
    page.getByRole("heading", { name: "합성 종료 대출 금액 확인", exact: true }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(1);
  expect(state.record!.values.find((row) => row.asset_id === uid(11))!.verification_state).toBe(
    "missing",
  );
});

test("a delayed native return cannot send the next void operation to the old income record", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const handle = state.handle;
  let release!: () => void;
  const response = new Promise<void>((resolve) => {
    release = resolve;
  });
  state.handle = async (...args) => {
    const result = await handle(...args);
    if (args[0] === "POST" && args[1].endsWith("/returns")) await response;
    return result;
  };
  const native = await mockNativeCashflow(page, state);
  await page.goto(`/income/${uid(40)}`);
  await page.getByRole("button", { name: "수입 반환 기록", exact: true }).click();
  await page.getByLabel("반환 금액 (원)", { exact: true }).fill("1");
  await page.getByLabel("실제 반환일", { exact: true }).fill("2025-02-28");
  await page.getByLabel("반환 사유", { exact: true }).fill("합성 반환 확인");
  await page.getByRole("button", { name: "반환 기록 저장", exact: true }).click();
  try {
    await expect.poll(() => native.calls.some((call) => call.method === "returnIncome")).toBe(true);
    await expect(page.getByRole("button", { name: "무효 처리 검토", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "작업 닫기", exact: true })).toBeDisabled();
    expect(native.calls.some((call) => call.method === "voidIncome")).toBe(false);
  } finally {
    release();
  }
  const returned = state.incomes.find((row) => row.reverses_id === uid(40))!;
  await expect(page).toHaveURL(new RegExp(`/income/${returned.id}$`));
  await page.getByRole("button", { name: "무효 처리 검토", exact: true }).click();
  await page.getByLabel("무효 사유", { exact: true }).fill("합성 반환 오등록 확인");
  await page.getByRole("button", { name: "사유와 함께 무효 처리", exact: true }).click();
  await expect(page.getByText("무효 기록 · 버전 2", { exact: true })).toBeVisible();
  expect(native.calls.find((call) => call.method === "voidIncome")!.args.recordId).toBe(
    returned.id,
  );
  expect(state.incomes.find((row) => row.id === uid(40))!.state).toBe("active");
  expect(native.http).toEqual([]);
});

test("a pending payment keeps its draft open and prevents a competing schedule action", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const handle = state.handle;
  let release!: () => void;
  const response = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/obligations/*/settlements", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const request = route.request();
    const url = new URL(request.url());
    const result = await handle(
      "POST",
      url.pathname,
      url.searchParams,
      request.postDataJSON(),
      request.headers(),
    );
    if (!result) throw new Error("Expected the synthetic settlement handler");
    await response;
    await route.fulfill({ status: result.status, json: result.body });
  });
  await page.goto(`/fixed-payments/${uid(70)}`);
  await openDisclosure(page, "예정일 변경·회차 관리");
  await page.getByRole("button", { name: "실제 납부 기록", exact: true }).click();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill("33000");
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  try {
    await expect.poll(() => state.payments.length).toBe(1);
    await expect(page.getByRole("button", { name: "예정일 변경", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "납부 작업 닫기", exact: true })).toBeDisabled();
  } finally {
    release();
  }
  await expect(
    page.getByText("실제 납부를 저장했어요. 아래 납부 내역에서 확인할 수 있어요.", { exact: true }),
  ).toBeFocused();
  expect(state.payments).toHaveLength(1);
  expect(state.writes).toHaveLength(1);
});

test("case task shortcuts move both the viewport and keyboard focus to the chosen work", async ({
  page,
}) => {
  await mockInsuranceEvents(page);
  await page.goto(`/insurance/cases/${uid(90)}`);
  const nav = page.getByRole("navigation", { name: "사건 작업 바로가기", exact: true });
  for (const [title, id] of [
    ["의료비", "case-expenses"],
    ["보험 청구", "case-claims"],
    ["보험금", "case-payouts"],
    ["진료·약국", "case-care"],
  ]) {
    await nav.getByRole("link", { name: new RegExp(`^${title}`) }).click();
    await expect(page.locator(`#${id}`)).toBeFocused();
    const target = await page.locator(`#${id}`).boundingBox();
    expect(target!.y).toBeGreaterThanOrEqual(0);
    expect(target!.y).toBeLessThan(300);
  }
});

test("a medical payment can be recorded from its case without entering optional receipt metadata", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  const before = state.expenses.length;
  await page.goto(`/insurance/cases/${uid(90)}`);
  await page
    .getByRole("navigation", { name: "사건 작업 바로가기" })
    .getByRole("link", { name: /^의료비/ })
    .click();
  await page
    .locator("#case-expenses")
    .getByRole("link", { name: "실제 의료비 추가", exact: true })
    .click();
  await expect(page.getByRole("combobox", { name: "비용 사건", exact: true })).toHaveValue(uid(90));
  await page.getByRole("combobox", { name: "비용 귀속 진료", exact: true }).selectOption(uid(91));
  await expect(page.getByLabel("영수증 참고번호 (선택)", { exact: true })).toBeHidden();
  await page.getByLabel("의료비 지불 금액 (원)", { exact: true }).fill("30000");
  await page.getByRole("button", { name: "실제 의료비 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "의료비 상세", exact: true })).toBeVisible();
  expect(state.expenses).toHaveLength(before + 1);
  expect(state.expenses.at(-1)).toMatchObject({
    case_id: uid(90),
    node_id: uid(91),
    gross_medical_krw: null,
    cash: { amount_krw: "30000" },
  });
});

test("a claim starts from the case shortcut and references an existing expense without adding a payment", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  const before = state.expenses.length;
  await page.goto(`/insurance/cases/${uid(90)}`);
  await page
    .getByRole("navigation", { name: "사건 작업 바로가기" })
    .getByRole("link", { name: /^보험 청구/ })
    .click();
  await page.locator("#case-claims").getByRole("link", { name: "청구 추가", exact: true }).click();
  await page.getByRole("combobox", { name: "청구 보험계약", exact: true }).selectOption(uid(80));
  await page.getByRole("checkbox", { name: /SYNTHETIC-RECEIPT-1001/ }).check();
  await page.getByRole("button", { name: "청구 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험 청구 상세", exact: true })).toBeVisible();
  expect(state.claims).toHaveLength(1);
  expect(state.claims[0]!.expense_ids).toEqual([uid(1001)]);
  expect(state.expenses).toHaveLength(before);
});

test("a claim's receipt task retains its allocation context and can be cancelled after confirming without a write", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  const row = claimRow();
  state.claims.push(row);
  await page.goto(`/insurance/claims/${row.id}`);
  await page.getByRole("link", { name: "이 청구의 실제 수령 기록", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "배분 사건", exact: true })).toHaveValue(
    row.case_id,
  );
  await expect(page.getByRole("combobox", { name: "배분 청구 (선택)", exact: true })).toHaveValue(
    row.id,
  );
  await page.getByLabel("보험금 수령 금액 (원)", { exact: true }).fill("50000");
  await page.getByRole("link", { name: "입력 취소", exact: true }).click();
  await page.getByRole("button", { name: "입력 버리고 나가기", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/insurance/cases/${row.case_id}$`));
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/insurance/claims/${row.id}$`));
  expect(state.writes).toHaveLength(0);
});

test("adding a medical node focuses its form and cancelling restores the add action", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  await page.goto(`/insurance/cases/${uid(90)}`);
  const trigger = page.getByRole("button", { name: "사건 아래 진료 추가", exact: true });
  await trigger.click();
  await expect(page.getByRole("region", { name: "진료·약국 입력", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "입력 취소", exact: true }).click();
  await expect(trigger).toBeFocused();
  expect(state.core.writes).toHaveLength(0);
});

test("opening a medical node lands at its own details instead of restarting at the case header", async ({
  page,
}) => {
  await mockInsuranceEvents(page);
  await page.goto(`/insurance/cases/${uid(90)}`);
  await page
    .getByRole("region", { name: "사건 진료 트리", exact: true })
    .getByRole("link", { name: "합성 첫 외래", exact: true })
    .click();
  await expect(page.getByRole("region", { name: "선택한 진료 작업", exact: true })).toBeFocused();
  await expect(
    page
      .getByRole("region", { name: "선택한 진료", exact: true })
      .getByRole("heading", { name: "합성 첫 외래", exact: true }),
  ).toBeVisible();
});

test("stock is the first consumable workspace and a replacement consumes one unit through its device", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  await page.goto("/consumables");
  const stock = page.getByRole("region", { name: "소모품 규격 목록", exact: true });
  const today = page.getByRole("region", { name: "오늘 교체 확인", exact: true });
  expect((await stock.boundingBox())!.y).toBeLessThan((await today.boundingBox())!.y);
  await stock.getByRole("link", { name: "합성 공용 필터", exact: true }).click();
  const device = page
    .locator(".device-record")
    .filter({ has: page.getByRole("link", { name: "합성 거실 청정기", exact: true }) });
  await device.getByRole("link", { name: "교체 기록", exact: true }).click();
  await page.getByLabel("실제 교체일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "실제 교체·재고 사용 저장", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/consumables/${uid(200)}$`));
  await expect(page.getByLabel("재고 저장 결과")).toContainText("공용 재고 3 → 2개");
  expect(state.consumables[0]!.stock_quantity).toBe(2);
  expect(state.replacements).toHaveLength(2);
});

test("replacement is reachable on the first mobile screen and cancelling setup restores focus", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  await page.goto(`/appliance-consumables/${uid(300)}`);
  await withinMobileWorkArea(page, page.getByRole("link", { name: "교체 기록", exact: true }));
  const edit = page.getByRole("button", { name: "기기별 주기·연결 수정", exact: true });
  await edit.click();
  await expect(
    page.getByRole("region", { name: "기기별 소모품 설정 입력", exact: true }),
  ).toBeFocused();
  await page.getByRole("button", { name: "입력 취소", exact: true }).click();
  await expect(edit).toBeFocused();
  expect(state.writes).toHaveLength(0);
});

test("an appliance's compact stock summary preserves a consumable's custom unit", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.consumables[0]!.unit = "매";
  await page.goto(`/appliances/${uid(100)}`);
  const row = page
    .locator(".device-record")
    .filter({ has: page.getByRole("link", { name: "합성 공용 필터", exact: true }) });
  await expect(row.locator(".record-facts")).toContainText("공용 재고 3매");
  await expect(row.locator(".record-details")).not.toHaveAttribute("open", "");
});

for (const [name, path, setup] of [
  [
    "medical expense",
    `/insurance/expenses/new?case=${uid(90)}&node=${uid(91)}`,
    mockInsuranceEvents,
  ],
  ["insurance receipt", `/insurance/payouts/new?case=${uid(90)}`, mockInsuranceEvents],
  ["recurring rule", "/fixed-payments/rules/new", mockCashflow],
  ["stock receipt", `/consumables/${uid(200)}/stock/new`, mockHomecare],
] as const)
  test(`${name} form keeps controls separated, supports cancellation, and fits enlarged narrow text`, async ({
    page,
  }) => {
    await setup(page);
    await page.goto(path);
    await expect(page.getByRole("link", { name: "입력 취소", exact: true })).toBeVisible();
    const controls = page.locator(
      'form input:not([type="checkbox"]):not([type="radio"]):visible, form select:visible',
    );
    const boxes = (
      await Promise.all((await controls.all()).map((control) => control.boundingBox()))
    ).filter((box) => box !== null);
    expect(boxes.length).toBeGreaterThan(2);
    for (const box of boxes) expect(box!.height).toBeGreaterThanOrEqual(48);
    for (const [index, box] of boxes.entries()) {
      const next = boxes
        .slice(index + 1)
        .find((other) => Math.abs(other!.x - box!.x) < 2 && other!.y >= box!.y + box!.height);
      if (next) expect(next.y - box!.y - box!.height).toBeGreaterThanOrEqual(12);
    }
    await page.setViewportSize({ width: 320, height: 720 });
    await page.addStyleTag({ content: "html { font-size: 200%; }" });
    await noOverflow(page);
  });
