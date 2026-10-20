import { openDisclosure } from "./support/task-ui";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockCashflow, incomeRow } from "./support/cashflow";
import { closedAccount, uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});

test("income summary separates earned and insurance inflow and filters only the record list", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.pageSize = 1;
  await page.goto("/income");
  const summary = page.getByRole("region", { name: "등록 수입 요약" });
  await expect(summary).toContainText("3,200,000원");
  await expect(summary).toContainText("800,000원");
  await expect(summary).toContainText("4,000,000원");
  await openDisclosure(page, "수입 기록 찾기");
  await page.getByRole("combobox", { name: "수입 구성원 필터", exact: true }).selectOption(uid(2));
  await expect(page).toHaveURL(/member=/);
  await expect(page.getByRole("link", { name: "급여 · 3,000,000원", exact: true })).toBeVisible();
  await expect(summary).toContainText("4,000,000원");
  await page.reload();
  await expect(page.getByRole("combobox", { name: "수입 구성원 필터", exact: true })).toHaveValue(
    uid(2),
  );
  await page.getByRole("button", { name: "수입 필터 초기화", exact: true }).click();
  await page.getByRole("button", { name: "수입 더 보기", exact: true }).click();
  await expect(page.getByRole("link", { name: "상여 · 200,000원", exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(0);
});
test("month income preserves large integer and refetches current capabilities after an immutable receipt", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.staleReceipt = true;
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("9007199254740993");
  await page.getByRole("combobox", { name: "입금계좌", exact: true }).selectOption(uid(30));
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
  await expect(page.getByText("메모: 더 최근 합성 메모", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "수입 정정", exact: true })).toBeVisible();
  await expect(page.getByText("9,007,199,254,740,993원 · 유입", { exact: true })).toBeVisible();
  expect(state.writes[0]!.body).toMatchObject({
    amount_krw: "9007199254740993",
    date_precision: "month",
    occurred_on: null,
    member_id: uid(2),
    account_id: uid(30),
    duplicate_acknowledged: false,
  });
  expect(Object.hasOwn(state.writes[0]!.body, "card_id")).toBe(false);
  expect(
    state.reads.some((read) => read.path === `/api/v1/income/${state.incomes.at(-1)!.id}`),
  ).toBe(true);
});
test("mixed precision requires explicit duplicate review and changing the amount clears acknowledgement", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await page.getByRole("combobox", { name: "날짜 정밀도", exact: true }).selectOption("day");
  await page.getByLabel("실제 입금일", { exact: true }).fill("2025-02-19");
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("1000");
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(page.getByRole("region", { name: "수입 중복 검토" })).toContainText("3,000,000원");
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("기존 기록과 별개의 수입임을 확인했어요.", { exact: true }).check();
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("2000");
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(
    page.getByLabel("기존 기록과 별개의 수입임을 확인했어요.", { exact: true }),
  ).not.toBeChecked();
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("기존 기록과 별개의 수입임을 확인했어요.", { exact: true }).check();
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
  expect(state.writes[0]!.body).toMatchObject({
    duplicate_acknowledged: true,
    date_precision: "day",
    occurred_on: "2025-02-19",
    amount_krw: "2000",
  });
});
for (const failure of ["before", "after"] as const)
  test(`income ${failure}-commit network ambiguity retries one operation identity`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    state.failure = failure;
    await page.goto("/income/new");
    await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
    await page.getByLabel("수입 금액 (원)", { exact: true }).fill("3000");
    await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("처리 결과를 확인하지 못했어요");
    expect(state.writes).toHaveLength(1);
    await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
    await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
    expect(state.writes).toHaveLength(2);
    expect(state.writes[0]!.key).toBeTruthy();
    expect(state.writes[1]!.key).toBe(state.writes[0]!.key);
    expect(state.incomes.filter((row) => row.amount_krw === "3000")).toHaveLength(1);
  });
test("income conflict preserves typed amount and adopts only unrelated current changes", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.conflict = true;
  await page.goto(`/income/${uid(40)}/edit`);
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("3000001");
  await page.getByLabel("정정 사유", { exact: true }).fill("합성 금액 확인 정정");
  await page.getByRole("button", { name: "수입 정정 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("작성한 내용은 유지");
  await expect(page.getByLabel("수입 금액 (원)", { exact: true })).toHaveValue("3000001");
  await page.getByRole("button", { name: "최신 수입과 비교", exact: true }).click();
  await page.getByRole("button", { name: "비교한 내 변경 유지", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "수입 메모", exact: true })).toHaveValue(
    "배우자 합성 메모",
  );
  await page.getByRole("button", { name: "수입 정정 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
  expect(state.writes.map((write) => write.version)).toEqual(['"1"', '"2"']);
  expect(state.writes.at(-1)!.body).toEqual({
    amount_krw: "3000001",
    reason: "합성 금액 확인 정정",
    duplicate_acknowledged: false,
  });
  expect(state.incomes[0]!.note).toBe("배우자 합성 메모");
});
test("partial return disables original corrections until that return is voided", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto(`/income/${uid(40)}`);
  await page.getByRole("button", { name: "수입 반환 기록", exact: true }).click();
  await page.getByLabel("반환 금액 (원)", { exact: true }).fill("100000");
  await page.getByLabel("실제 반환일", { exact: true }).fill("2025-02-20");
  await page.getByLabel("반환 사유", { exact: true }).fill("합성 일부 반환");
  await page.getByRole("button", { name: "반환 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "수입 반환", exact: true })).toBeVisible();
  const returnedId = state.incomes.at(-1)!.id;
  expect(state.writes[0]!.body.member_id).toBeUndefined();
  expect(state.writes[0]!.body.card_id).toBeUndefined();
  await page.getByRole("link", { name: "반환 원본 수입 확인", exact: true }).click();
  await expect(page.getByRole("link", { name: "수입 정정", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "무효 처리 검토", exact: true })).toHaveCount(0);
  await page.goto(`/income/${returnedId}`);
  await page.getByRole("button", { name: "무효 처리 검토", exact: true }).click();
  await page.getByLabel("무효 사유", { exact: true }).fill("합성 반환 오등록");
  await page.getByRole("button", { name: "사유와 함께 무효 처리", exact: true }).click();
  await expect(page.getByText("무효 기록 · 버전 2", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "반환 원본 수입 확인", exact: true }).click();
  await expect(page.getByRole("link", { name: "수입 정정", exact: true })).toBeVisible();
});
test("insurance projections offer source navigation and no income mutation controls", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto(`/income/${uid(42)}`);
  await expect(page.getByRole("link", { name: "보험 사건에서 관리", exact: true })).toHaveAttribute(
    "href",
    "/insurance/cases",
  );
  await expect(page.getByRole("link", { name: "수입 정정", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "수입 반환 기록", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "무효 처리 검토", exact: true })).toHaveCount(0);
  expect(state.writes).toHaveLength(0);
});
test("precision conversion requires equal totals and records all source versions without duplicate income", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto("/income/convert");
  await page.getByRole("combobox", { name: "전환 구성원", exact: true }).selectOption(uid(2));
  await page.getByRole("button", { name: "원본 수입 전체 확인", exact: true }).click();
  const first = page.getByRole("region", { name: "대체 수입 1", exact: true });
  await first.getByLabel("수입 금액 (원)", { exact: true }).fill("1000000");
  await first.getByLabel("실제 입금일", { exact: true }).fill("2025-02-01");
  await page.getByRole("button", { name: "대체 수입 추가", exact: true }).click();
  const second = page.getByRole("region", { name: "대체 수입 2", exact: true });
  await second.getByLabel("수입 금액 (원)", { exact: true }).fill("1999999");
  await second.getByLabel("실제 입금일", { exact: true }).fill("2025-02-10");
  await page.getByLabel("전환 사유", { exact: true }).fill("합성 입금일별 내역 확인");
  await page.getByLabel("원본 전체와 같은 합계의 대체 기록을 확인했어요.", { exact: true }).check();
  await page.getByRole("button", { name: "합계를 유지하고 전환", exact: true }).click();
  await expect(page.getByText("전환 전후 합계가 같아야 해요.", { exact: true })).toBeFocused();
  expect(state.writes).toHaveLength(0);
  await second.getByLabel("수입 금액 (원)", { exact: true }).fill("2000000");
  await page.getByLabel("원본 전체와 같은 합계의 대체 기록을 확인했어요.", { exact: true }).check();
  await page.getByRole("button", { name: "합계를 유지하고 전환", exact: true }).click();
  await expect(page).toHaveURL(/\/income$/);
  expect(state.writes[0]!.body.sources).toEqual([{ id: uid(40), version: 1 }]);
  expect(
    state.writes[0]!.body.replacements.every(
      (row: Record<string, unknown>) =>
        !Object.hasOwn(row, "duplicate_acknowledged") && row.date_precision === "day",
    ),
  ).toBe(true);
  expect(state.incomes[0]!.state).toBe("void");
  await expect(page.getByRole("region", { name: "등록 수입 요약" })).toContainText("4,000,000원");
});
test("history pagination keeps every version of the same record", async ({ page }) => {
  const state = await mockCashflow(page);
  state.pageSize = 1;
  state.incomes[0]!.version = 3;
  state.incomeHistory.set(uid(40), [
    incomeRow(40, { version: 1 }),
    incomeRow(40, { version: 2, action: "correct", reason: "합성 정정 하나" }),
    incomeRow(40, { version: 3, action: "correct", reason: "합성 정정 둘" }),
  ]);
  await page.goto(`/income/${uid(40)}`);
  await page.getByRole("button", { name: "수입 이력 더 보기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "버전 2 · 정정", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "수입 이력 더 보기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "버전 1 · 등록", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "버전 3 · 정정", exact: true })).toBeVisible();
});

test("an income can use an account through the day it closed", async ({ page }) => {
  const state = await mockCashflow(page);
  state.finance.accounts.push(closedAccount(33, "2025-02-15"));
  await page.goto("/income/new");
  const closed = page.getByRole("option", {
    name: /^합성 종료 계좌 자산 · .* · 2025\.02\.15 사용 종료$/,
  });
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await page.getByRole("combobox", { name: "날짜 정밀도", exact: true }).selectOption("day");
  await page.getByLabel("실제 입금일", { exact: true }).fill("2025-02-16");
  await expect(closed).toHaveCount(0);
  await page.getByLabel("실제 입금일", { exact: true }).fill("2025-02-15");
  await expect(closed).toHaveJSProperty("disabled", false);
  await page.getByRole("combobox", { name: "날짜 정밀도", exact: true }).selectOption("month");
  await expect(closed).toHaveJSProperty("disabled", false);
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("1000");
  await page.getByRole("combobox", { name: "입금계좌", exact: true }).selectOption(uid(33));
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]!.body).toMatchObject({
    date_precision: "month",
    period_month: "2025-02",
    account_id: uid(33),
  });
});

async function correctToDay(page: Page) {
  await page.goto(`/income/${uid(40)}/edit`);
  await page.getByRole("combobox", { name: "날짜 정밀도", exact: true }).selectOption("day");
  await page.getByLabel("실제 입금일", { exact: true }).fill("2025-02-10");
  await page.getByLabel("정정 사유", { exact: true }).fill("합성 입금일 확인");
  await page.getByRole("button", { name: "수입 정정 저장", exact: true }).click();
}
test("an income correction never lists the record itself as a duplicate", async ({ page }) => {
  const state = await mockCashflow(page);
  await correctToDay(page);
  await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(1);
  expect(state.writes[0]!.body).toMatchObject({
    date_precision: "day",
    occurred_on: "2025-02-10",
    reason: "합성 입금일 확인",
  });
  expect(state.writes[0]!.body.duplicate_acknowledged).not.toBe(true);
});
test("another month total still needs duplicate review during a correction", async ({ page }) => {
  const state = await mockCashflow(page);
  state.incomes.push(incomeRow(44, { amount_krw: "100000" }));
  await correctToDay(page);
  const review = page.getByRole("region", { name: "수입 중복 검토", exact: true });
  await expect(review.getByRole("link")).toHaveCount(1);
  await expect(review.getByRole("link", { name: "100,000원 · 월합계", exact: true })).toBeVisible();
  await expect(
    page.getByText("아래 기존 기록을 확인하고 중복 여부를 선택해 주세요.", { exact: true }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(0);
});

async function loadConversion(page: Page) {
  await page.goto("/income/convert");
  await page.getByRole("combobox", { name: "전환 구성원", exact: true }).selectOption(uid(2));
  await page.getByRole("button", { name: "원본 수입 전체 확인", exact: true }).click();
  return page.getByRole("region", { name: "대체 수입 1", exact: true });
}
test("precision conversion keeps the shared account and note of its sources", async ({ page }) => {
  const state = await mockCashflow(page);
  state.incomes[0]!.note = "합성 급여 메모";
  const first = await loadConversion(page);
  await expect(
    page.getByRole("listitem").filter({ hasText: "3,000,000원 · 월합계" }),
  ).toContainText("합성 개인 금융 자산 · 메모 합성 급여 메모");
  await expect(first.getByRole("combobox", { name: "입금계좌", exact: true })).toHaveValue(uid(30));
  // A filled textarea inside its label adds its value to the accessible name.
  await expect(first.getByLabel("수입 메모")).toHaveValue("합성 급여 메모");
  await first.getByLabel("실제 입금일", { exact: true }).fill("2025-02-10");
  await page.getByLabel("전환 사유", { exact: true }).fill("합성 입금일 확인");
  await page.getByLabel("원본 전체와 같은 합계의 대체 기록을 확인했어요.", { exact: true }).check();
  await page.getByRole("button", { name: "합계를 유지하고 전환", exact: true }).click();
  await expect(page).toHaveURL(/\/income$/);
  expect(state.writes[0]!.body.replacements).toEqual([
    expect.objectContaining({
      amount_krw: "3000000",
      occurred_on: "2025-02-10",
      account_id: uid(30),
      note: "합성 급여 메모",
    }),
  ]);
});
test("precision conversion leaves differing source accounts for the user to choose", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.incomes.push(incomeRow(45, { amount_krw: "500000", account_id: null }));
  const first = await loadConversion(page);
  await expect(first.getByRole("combobox", { name: "입금계좌", exact: true })).toHaveValue("");
  await expect(
    page.getByText(
      "원본마다 계좌가 달라 대체 기록에 넣지 않았어요. 원본 목록을 보고 직접 입력해 주세요.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "500,000원 · 월합계" })).toContainText(
    "계좌 연결 안 함",
  );
});

test("income amount accepts thousands separators, echoes the value and sends digits only", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("3,500,000");
  await expect(page.getByText("3,500,000원", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
  expect(state.writes[0]!.body).toMatchObject({ amount_krw: "3500000" });
});

test("invalid income amount keeps save enabled and explains the field on submit", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  const amount = page.getByLabel("수입 금액 (원)", { exact: true });
  await amount.fill("1.5");
  const save = page.getByRole("button", { name: "수입 기록 저장", exact: true });
  await expect(save).toBeEnabled();
  await save.click();
  await expect(amount).toHaveAttribute("aria-invalid", "true");
  await expect(amount).toBeFocused();
  await expect(amount).toHaveAccessibleDescription(
    "원 단위 숫자로 입력해 주세요. 세 자리마다 쉼표를 쓸 수 있지만 소수점·부호는 쓸 수 없어요.",
  );
  await expect(page.getByRole("alert")).toContainText("구성원·월·금액·실제 날짜를 확인해 주세요.");
  await amount.fill("1,500");
  await expect(amount).not.toHaveAttribute("aria-invalid", "true");
  expect(state.writes).toHaveLength(0);
});
