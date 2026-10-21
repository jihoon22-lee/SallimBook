import { openDisclosure } from "./support/task-ui";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import fixtures from "../../../packages/test-fixtures/catalog.json" with { type: "json" };
import { incomeRow, mockCashflow, sampleCard } from "./support/cashflow";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
test("fixed summary separates known plans, unknown amounts and actuals without automatic generation", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto("/fixed-payments");
  const summary = page.getByRole("region", { name: "고정 납부 월 요약", exact: true });
  await expect(summary).toContainText("1,033,000원");
  await expect(summary).toContainText("예정액 미정1개");
  await expect(summary).toContainText("실제 납부액0원");
  await expect(page.getByRole("link", { name: "합성 미정 납부", exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(0);
  await page.getByRole("button", { name: "예정 회차 생성 열기", exact: true }).click();
  await page.getByLabel("회차 생성 종료일", { exact: true }).fill("2026-02-02");
  await page.getByRole("button", { name: "선택 기간 회차 생성", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "회차 생성 기간은 시작일부터 1년 이내로 정해 주세요.",
  );
  expect(state.writes).toHaveLength(0);
});
test("explicit generation retries the same key after a committed response is lost", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.failure = "after";
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "예정 회차 생성 열기", exact: true }).click();
  await page.getByRole("button", { name: "선택 기간 회차 생성", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("처리 결과를 확인하지 못했어요");
  expect(state.writes).toHaveLength(1);
  await page.getByRole("button", { name: "선택 기간 회차 생성", exact: true }).click();
  await expect(
    page.getByText("요청한 기간의 회차 생성을 확인했어요. 예정 월 목록에서 확인해 주세요.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(state.writes.map((write) => write.key)).toEqual([
    state.writes[0]!.key,
    state.writes[0]!.key,
  ]);
  expect(state.writes[0]!.key).toBeTruthy();
  expect(state.writes[0]!.body).toEqual({
    start_date: "2025-02-01",
    end_date: "2025-02-28",
    rule_id: null,
  });
  expect(state.obligations).toHaveLength(3);
  await page.getByRole("button", { name: "선택 기간 회차 생성", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(3);
  expect(state.writes[2]!.key).not.toBe(state.writes[0]!.key);
  expect(state.obligations).toHaveLength(3);
});
test("annual variable rule keeps unknown KRW separate from foreign reference and explicit zero", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto("/fixed-payments/rules/new");
  await page.getByLabel("규칙 이름", { exact: true }).fill("합성 연간 외화 구독");
  await page.getByRole("combobox", { name: "예정금액 방식", exact: true }).selectOption("variable");
  await page.getByRole("combobox", { name: "반복 주기", exact: true }).selectOption("annual");
  await page.getByLabel("주기 기준일", { exact: true }).fill("2024-02-29");
  await page.getByLabel("적용 시작일", { exact: true }).fill("2025-01-01");
  await page.getByLabel("외화 참고 통화 (선택)", { exact: true }).fill("USD");
  await page.getByLabel("외화 참고금액 (선택)", { exact: true }).fill("20.12345678");
  await page.getByRole("button", { name: "납부 규칙 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "납부 규칙 상세", exact: true })).toBeVisible();
  expect(state.writes[0]!.body).toMatchObject({
    frequency: "annual",
    anchor_date: "2024-02-29",
    amount_mode: "variable",
    expected_amount_krw: null,
    currency_reference: "USD",
    foreign_amount_reference: "20.12345678",
  });
  await expect(page.getByText("미정 · 변동 금액", { exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
test("future scheduled end permits new terms before the cutoff without rewriting prior amounts", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.rules[0]!.ended_on = "2025-12-31";
  state.rules[0]!.end_reason = "합성 연말 종료";
  state.rules[0]!.versions[0]!.effective_until = "2025-12-31";
  await page.goto(`/fixed-payments/rules/${uid(60)}`);
  await page.getByRole("link", { name: "규칙 적용기간 변경", exact: true }).click();
  await page.getByLabel("원화 예정금액 (원)", { exact: true }).fill("34000");
  await page.getByLabel("적용 시작일", { exact: true }).fill("2025-12-31");
  await page.getByLabel("규칙 변경 사유", { exact: true }).fill("합성 요금 변경");
  await page
    .getByLabel(
      "새 적용기간의 미래 미납 회차가 바뀌며, 과거·실제 납부·수동 예외는 보존됨을 확인했어요.",
      { exact: true },
    )
    .check();
  await page.getByRole("button", { name: "새 적용기간 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "필수 정보·날짜·금액과 적용 범위를 확인해 주세요.",
  );
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("적용 시작일", { exact: true }).fill("2025-03-01");
  await page
    .getByLabel(
      "새 적용기간의 미래 미납 회차가 바뀌며, 과거·실제 납부·수동 예외는 보존됨을 확인했어요.",
      { exact: true },
    )
    .check();
  await page.getByRole("button", { name: "새 적용기간 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "납부 규칙 상세", exact: true })).toBeVisible();
  expect(state.rules[0]!.ended_on).toBe("2025-12-31");
  expect(state.rules[0]!.end_reason).toBe("합성 연말 종료");
  expect(state.rules[0]!.versions.map((row) => row.expected_amount_krw)).toEqual([
    "33000",
    "34000",
  ]);
  expect(state.rules[0]!.versions[1]!.effective_until).toBe("2025-12-31");
  expect(state.writes[0]!.body.effective_until).toBeUndefined();
});
test("a future rule cutoff can be shortened but not extended from the end form", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.rules[0]!.ended_on = "2025-12-31";
  state.rules[0]!.versions[0]!.effective_until = "2025-12-31";
  await page.goto(`/fixed-payments/rules/${uid(60)}`);
  await page.getByRole("button", { name: "규칙 종료일 앞당기기 검토", exact: true }).click();
  await page.getByLabel("규칙 종료 적용일", { exact: true }).fill("2026-01-01");
  await page.getByLabel("규칙 종료 사유", { exact: true }).fill("합성 일정 앞당김");
  await page
    .getByLabel("종료 적용일 이후의 미래 미납 회차가 바뀌는 것을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "납부 규칙 종료 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "종료 적용일·종료 사유·확인란을 확인해 주세요. 종료 적용일은 오늘 이후, 마지막 적용 시작일 뒤, 기존 종료일 전이어야 해요.",
  );
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("규칙 종료 적용일", { exact: true }).fill("2025-08-01");
  await page
    .getByLabel("종료 적용일 이후의 미래 미납 회차가 바뀌는 것을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "납부 규칙 종료 저장", exact: true }).click();
  await expect(page.getByText("종료 사유: 합성 일정 앞당김", { exact: true })).toBeVisible();
  expect(state.rules[0]!.ended_on).toBe("2025-08-01");
});
test("T-11 partial and overpayment show actual 35000 rather than planned plus actual", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto(`/fixed-payments/${uid(70)}`);
  for (const amount of ["10000", "25000"]) {
    await page.getByRole("button", { name: "실제 납부 기록", exact: true }).click();
    await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill(amount);
    await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-20");
    await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
    await expect(page.getByRole("heading", { name: "실제 납부 기록", exact: true })).toHaveCount(0);
  }
  expect(state.obligations[0]).toMatchObject({
    expected_amount_krw: "33000",
    actual_amount_krw: "35000",
    difference_krw: "2000",
    status: "paid",
  });
  await expect(page.getByText("+2,000원", { exact: true })).toBeVisible();
  await expect(page.getByText("68,000원", { exact: true })).toHaveCount(0);
  expect(state.writes.map((write) => write.version)).toEqual(['"1"', '"2"']);
  expect(state.writes[0]!.key).not.toBe(state.writes[1]!.key);
});
test("T-09 loan payment validates exact principal plus interest and reports consumption separately", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const fixture = fixtures.vectors.find((row) => row.id === "T-09")!;
  const input = fixture.inputs as {
    payment_krw: string;
    principal_krw: string;
    interest_krw: string;
  };
  await page.goto(`/fixed-payments/${uid(71)}`);
  await page.getByRole("button", { name: "실제 납부 기록", exact: true }).click();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill(input.payment_krw);
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-20");
  await page.getByLabel("실제 원금 상환액 (원)", { exact: true }).fill(input.principal_krw);
  await page.getByLabel("실제 이자 (원)", { exact: true }).fill("299999");
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "실제 납부금액·납부일·납부 수단을 확인해 주세요. 대출 상환은 원금과 이자의 합이 납부금액과 같아야 해요.",
  );
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("실제 이자 (원)", { exact: true }).fill(input.interest_krw);
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await expect(page.getByText("300,000원 / 700,000원 / 0원", { exact: true })).toBeVisible();
  expect(state.payments[0]).toMatchObject({
    principal_krw: "700000",
    consumption_krw: "300000",
    asset_transfer_krw: "0",
  });
  expect(state.writes.every((write) => write.path.endsWith("/settlements"))).toBe(true);
});
test("unknown asset-transfer payment can be manually completed reopened and voided using cash version", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.obligations[2]!.economic_type = "asset_transfer";
  await page.goto(`/fixed-payments/${uid(72)}`);
  await expect(page.getByText("예정액 미정으로 계산하지 않음", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "실제 납부 기록", exact: true }).click();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill("5000");
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-20");
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await expect(page.getByText("0원 / 0원 / 5,000원", { exact: true })).toBeVisible();
  for (const action of ["수동 납부 완료", "수동 완료 재개"]) {
    await openDisclosure(page, "예정일 변경·회차 관리");
    await page.getByRole("button", { name: action, exact: true }).click();
    await page.getByLabel("회차 변경 사유", { exact: true }).fill(`합성 ${action}`);
    await page.getByRole("button", { name: `${action} 저장`, exact: true }).click();
    await expect(page.getByRole("heading", { name: action, exact: true })).toHaveCount(0);
  }
  await page.getByRole("button", { name: "이 납부 무효 검토", exact: true }).click();
  await page.getByLabel("납부 무효 사유", { exact: true }).fill("합성 납부 오등록");
  await page.getByRole("button", { name: "사유와 함께 납부 무효 처리", exact: true }).click();
  await expect(page.getByText("0원 / 0원 / 0원", { exact: true })).toBeVisible();
  expect(state.writes.at(-1)!.version).toBe('"1"');
  expect(state.obligations[2]!.version).toBe(5);
  expect(state.payments[0]!.cash.state).toBe("void");
});
test("rescheduling conflict preserves chosen date and original nominal date with paged history", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.conflict = true;
  state.pageSize = 1;
  await page.goto(`/fixed-payments/${uid(70)}`);
  await openDisclosure(page, "예정일 변경·회차 관리");
  await page.getByRole("button", { name: "예정일 변경", exact: true }).click();
  await page.getByLabel("변경할 예정일", { exact: true }).fill("2025-03-01");
  await page.getByLabel("회차 변경 사유", { exact: true }).fill("합성 실제 예정일 확인");
  await page.getByRole("button", { name: "예정일 변경 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("변경할 예정일", { exact: true })).toHaveValue("2025-03-01");
  await page.getByRole("button", { name: "현재 회차와 비교", exact: true }).click();
  await page.getByRole("button", { name: "현재 회차를 확인하고 계속", exact: true }).click();
  await page.getByRole("button", { name: "예정일 변경 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "예정일 변경", exact: true })).toHaveCount(0);
  expect(state.obligations[0]).toMatchObject({
    scheduled_date: "2025-03-01",
    nominal_date: "2025-02-28",
    manual_override: true,
  });
  await page.getByRole("button", { name: "회차 이력 더 보기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "버전 1 · 회차 생성", exact: true }),
  ).toBeVisible();
  expect(state.writes.map((write) => write.version)).toEqual(['"1"', '"2"']);
});
test("skipping and restoring an unpaid occurrence create no cash event", async ({ page }) => {
  const state = await mockCashflow(page);
  await page.goto(`/fixed-payments/${uid(70)}`);
  for (const action of ["회차 건너뛰기", "건너뛰기 되돌리기"]) {
    await openDisclosure(page, "예정일 변경·회차 관리");
    await page.getByRole("button", { name: action, exact: true }).click();
    await page.getByLabel("회차 변경 사유", { exact: true }).fill(`합성 ${action}`);
    await page.getByRole("button", { name: `${action} 저장`, exact: true }).click();
    await expect(page.getByRole("heading", { name: action, exact: true })).toHaveCount(0);
  }
  expect(state.payments).toHaveLength(0);
  expect(state.obligations[0]!.skipped).toBe(false);
  expect(state.writes.map((write) => write.path.split("/").at(-1))).toEqual(["skip", "unskip"]);
  expect(state.obligations[0]!.manual_override).toBe(false);
  await expect(page.getByText("2025.02.28 · 수동 예외", { exact: true })).toHaveCount(0);
});

test("calendar loads every page and places occurrences by scheduled day without creating cash", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.pageSize = 1;
  state.obligations[0]!.scheduled_date = "2025-02-25";
  state.obligations[0]!.manual_override = true;
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "달력 보기", exact: true }).click();
  const calendar = page.getByRole("region", { name: "월 납부 달력", exact: true });
  await expect(calendar).toContainText("이 달의 생성된 회차 3개");
  const day = calendar.getByRole("listitem", { name: "2025-02-25 예정", exact: true });
  await expect(day).toContainText("수동 예외");
  await expect(day).toContainText("예정 33,000원");
  await expect(day).toContainText("실제 0원");
  expect(state.writes).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await day.getByRole("link", { name: "합성 AI 구독", exact: true }).click();
  await expect(page.getByRole("heading", { name: "고정 납부 상세", exact: true })).toBeVisible();
});

function withPendingChange(state: Awaited<ReturnType<typeof mockCashflow>>) {
  const rule = state.rules[0]!;
  rule.versions[0]!.effective_until = "2025-12-01";
  rule.versions.push({
    ...structuredClone(rule.versions[0]!),
    id: uid(260),
    effective_from: "2025-12-01",
    effective_until: null,
    expected_amount_krw: "34000",
    reason: "합성 예정 변경",
  });
  return rule;
}
async function endRuleOn(page: Page, date: string) {
  await page.goto(`/fixed-payments/rules/${uid(60)}`);
  await page.getByRole("button", { name: "납부 규칙 종료 검토", exact: true }).click();
  await page.getByLabel("규칙 종료 적용일", { exact: true }).fill(date);
  await page.getByLabel("규칙 종료 사유", { exact: true }).fill("합성 해지");
  await page
    .getByLabel("종료 적용일 이후의 미래 미납 회차가 바뀌는 것을 확인했어요.", { exact: true })
    .check();
}
test("ending before a pending change withdraws it and keeps the current terms", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const rule = withPendingChange(state);
  await endRuleOn(page, "2025-11-15");
  await expect(
    page.getByText("2025.12.01 적용 예정 변경은 함께 철회돼요.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "납부 규칙 종료 저장", exact: true }).click();
  await expect(page.getByText("종료 사유: 합성 해지", { exact: true })).toBeVisible();
  expect(state.writes.at(-1)!.body).toEqual({ effective_on: "2025-11-15", reason: "합성 해지" });
  expect(rule.ended_on).toBe("2025-11-15");
  expect(rule.versions.map((row) => [row.effective_from, row.effective_until])).toEqual([
    ["2025-01-01", "2025-11-15"],
  ]);
});
test("a pending amount typo is replaced at its own start date", async ({ page }) => {
  const state = await mockCashflow(page);
  const rule = withPendingChange(state);
  await page.goto(`/fixed-payments/rules/${uid(60)}/edit`);
  await page.getByLabel("원화 예정금액 (원)", { exact: true }).fill("35000");
  await page.getByLabel("적용 시작일", { exact: true }).fill("2025-12-01");
  await expect(
    page.getByText("2025.12.01 적용 예정 변경은 함께 철회돼요.", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("규칙 변경 사유", { exact: true }).fill("합성 금액 오타 수정");
  await page
    .getByLabel(
      "새 적용기간의 미래 미납 회차가 바뀌며, 과거·실제 납부·수동 예외는 보존됨을 확인했어요.",
      { exact: true },
    )
    .check();
  await page.getByRole("button", { name: "새 적용기간 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "납부 규칙 상세", exact: true })).toBeVisible();
  expect(
    rule.versions.map((row) => [row.effective_from, row.effective_until, row.expected_amount_krw]),
  ).toEqual([
    ["2025-01-01", "2025-12-01", "33000"],
    ["2025-12-01", null, "35000"],
  ]);
  expect(state.writes.at(-1)!.body).toMatchObject({
    effective_from: "2025-12-01",
    expected_amount_krw: "35000",
    reason: "합성 금액 오타 수정",
  });
  expect(state.writes.at(-1)!.version).toBe('"1"');
});
test("a pending change with handled occurrences explains why it cannot be withdrawn", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  withPendingChange(state);
  state.withdrawalBlocked = true;
  await endRuleOn(page, "2025-11-15");
  await page.getByRole("button", { name: "납부 규칙 종료 저장", exact: true }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "철회할 예정 변경에 실제 납부나 수동 변경한 회차가 있어요." }),
  ).toBeVisible();
  await expect(page.getByLabel("규칙 종료 적용일", { exact: true })).toHaveValue("2025-11-15");
  expect(state.rules[0]!.versions).toHaveLength(2);
  expect(state.rules[0]!.ended_on).toBeNull();
});

test("a card closed after the payment date can still record that payment", async ({ page }) => {
  const state = await mockCashflow(page);
  state.cards.push({
    ...structuredClone(sampleCard),
    id: uid(52),
    alias: "합성 종료 카드",
    last_four: "2222",
    masked_number: "•••• 2222",
    ended_on: "2025-02-15",
    status: "closed",
  });
  const closed = page.getByRole("option", {
    name: "합성 종료 카드 · •••• 2222 · 2025.02.15 사용 종료",
    exact: true,
  });
  await page.goto(`/fixed-payments/${uid(70)}`);
  await page.getByRole("button", { name: "실제 납부 기록", exact: true }).click();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill("33000");
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-16");
  await expect(closed).toHaveCount(0);
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-15");
  await expect(closed).toHaveJSProperty("disabled", false);
  await page.getByRole("combobox", { name: "납부 카드", exact: true }).selectOption(uid(52));
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "실제 납부 기록", exact: true })).toHaveCount(0);
  expect(state.writes.at(-1)!.body).toMatchObject({
    occurred_on: "2025-02-15",
    card_id: uid(52),
    account_id: null,
  });
  await page.goto("/fixed-payments/rules/new");
  await page.getByRole("combobox", { name: "납부수단 구분", exact: true }).selectOption("card");
  await expect(closed).toHaveCount(0);
});

test("a paid occurrence asks before recording an additional payment", async ({ page }) => {
  const state = await mockCashflow(page);
  const paid = state.obligations[0]!;
  Object.assign(paid, { status: "paid", actual_amount_krw: "33000", difference_krw: "0" });
  // The mock recomputes status from payments, so the earlier payment has to exist too.
  state.payments.push({
    id: uid(280),
    obligation_id: paid.id,
    economic_type: paid.economic_type,
    principal_krw: "0",
    consumption_krw: "33000",
    asset_transfer_krw: "0",
    cash: incomeRow(281, {
      kind: "fixed_payment",
      flow: "out",
      amount_krw: "33000",
      occurred_on: "2025-02-10",
      date_precision: "day",
      member_id: null,
    }),
  });
  await page.goto("/fixed-payments");
  const paidRow = page
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: "합성 AI 구독", exact: true }) });
  await expect(paidRow.getByRole("link", { name: "납부 기록", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "납부 기록", exact: true })).toHaveCount(2);
  await page.goto(`/fixed-payments/${uid(70)}?task=settle`);
  await expect(
    page.getByRole("heading", { name: "이미 납부를 마친 회차예요", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("실제 납부금액 (원)", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "실제 납부 기록", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "추가 납부 기록", exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "추가 납부 입력 계속", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("납부 내역을 확인했고, 이 회차에 추가로 낸 금액이 있어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "추가 납부 입력 계속", exact: true }).click();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill("1000");
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-20");
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await expect(
    page.getByText("실제 납부를 저장했어요. 아래 납부 내역에서 확인할 수 있어요.", { exact: true }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(1);
  await page.getByRole("button", { name: "추가 납부 기록", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "이미 납부를 마친 회차예요", exact: true }),
  ).toBeVisible();
});

test("a payment that conflicts with a partner's completed payment asks again before saving", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const row = state.obligations[0]!;
  await page.goto(`/fixed-payments/${row.id}`);
  await page.getByRole("button", { name: "실제 납부 기록", exact: true }).click();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill("33000");
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-20");
  // The partner records the full payment before this form is saved.
  state.payments.push({
    id: uid(280),
    obligation_id: row.id,
    economic_type: row.economic_type,
    principal_krw: "0",
    consumption_krw: "33000",
    asset_transfer_krw: "0",
    cash: incomeRow(281, {
      kind: "fixed_payment",
      flow: "out",
      amount_krw: "33000",
      occurred_on: "2025-02-19",
      date_precision: "day",
      member_id: null,
    }),
  });
  Object.assign(row, {
    status: "paid",
    actual_amount_krw: "33000",
    difference_krw: "0",
    version: row.version + 1,
  });
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await page.getByRole("button", { name: "납부 전 현재 회차 비교", exact: true }).click();
  const proceed = page.getByRole("button", { name: "현재 납부 기준으로 계속", exact: true });
  await expect(proceed).toBeDisabled();
  await page
    .getByLabel("납부 내역을 확인했고, 이 회차에 추가로 낸 금액이 있어요.", { exact: true })
    .check();
  await proceed.click();
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await expect(
    page.getByText("실제 납부를 저장했어요. 아래 납부 내역에서 확인할 수 있어요.", { exact: true }),
  ).toBeVisible();
  expect(state.payments).toHaveLength(2);
});

test("a conflict on a still-unpaid occurrence continues without the additional check", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.conflict = true;
  await page.goto(`/fixed-payments/${uid(70)}`);
  await page.getByRole("button", { name: "실제 납부 기록", exact: true }).click();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill("33000");
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-20");
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await page.getByRole("button", { name: "납부 전 현재 회차 비교", exact: true }).click();
  await expect(
    page.getByLabel("납부 내역을 확인했고, 이 회차에 추가로 낸 금액이 있어요.", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "현재 납부 기준으로 계속", exact: true }).click();
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await expect(
    page.getByText("실제 납부를 저장했어요. 아래 납부 내역에서 확인할 수 있어요.", { exact: true }),
  ).toBeVisible();
  expect(state.payments).toHaveLength(1);
});

test("occurrence history names rule-driven regeneration", async ({ page }) => {
  const state = await mockCashflow(page);
  const row = state.obligations[0]!;
  row.version = 3;
  const item = (
    version: number,
    action: components["schemas"]["ObligationHistoryItem"]["action"],
    patch: Partial<components["schemas"]["ObligationHistoryItem"]> = {},
  ): components["schemas"]["ObligationHistoryItem"] => ({
    id: row.id,
    version,
    rule_version_id: row.rule_version_id,
    expected_amount_krw: row.expected_amount_krw,
    nominal_date: row.nominal_date,
    scheduled_date: row.scheduled_date,
    schedule_state: "active",
    manual_override: false,
    skipped: false,
    manually_completed: false,
    action,
    reason: null,
    updated_at: "2025-02-20T03:00:00Z",
    ...patch,
  });
  state.obligationHistory.set(row.id, [
    item(1, "create"),
    item(2, "regenerate", { expected_amount_krw: "34000" }),
    item(3, "regenerate", { schedule_state: "superseded" }),
  ]);
  await page.goto(`/fixed-payments/${uid(70)}`);
  await expect(
    page.getByRole("heading", { name: "버전 2 · 규칙 변경 반영", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "버전 3 · 규칙 종료로 대체", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: /회차 상태 변경$/ })).toHaveCount(0);
});

test("actual payment accepts grouped amounts and sends digits only", async ({ page }) => {
  const state = await mockCashflow(page);
  await page.goto(`/fixed-payments/${uid(70)}`);
  await page.getByRole("button", { name: "실제 납부 기록", exact: true }).click();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill("17,000");
  await expect(page.getByText("17,000원", { exact: true })).toBeVisible();
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-20");
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]!.body).toMatchObject({ amount_krw: "17000" });
});
test("the occurrence list title names the selected month", async ({ page }) => {
  await mockCashflow(page);
  await page.goto("/fixed-payments");
  await page.getByLabel("확인할 월").fill("2025-01");
  await expect(
    page.getByRole("heading", { name: "2025년 1월 납부 목록", exact: true }),
  ).toBeVisible();
});
