import { expect, test } from "@playwright/test";
import { incomeRow, mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { mockInsuranceEvents } from "./support/insurance-events";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
for (const platform of ["web", "native"] as const)
  test(`${platform} previous income becomes an unsaved current draft with explicit duplicate review`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    const previous = incomeRow(500, {
      period_month: "2025-01",
      amount_krw: "1234567",
      note: "합성 반복 급여",
    });
    state.incomes.push(
      previous,
      incomeRow(501, { period_month: "2025-01", kind: "insurance_receipt" }),
      incomeRow(502, { period_month: "2025-01", state: "void" }),
    );
    state.pageSize = 1;
    const native = platform === "native" ? await mockNativeCashflow(page, state) : null;
    await page.goto("/income/new");
    await expect(page.getByRole("combobox", { name: "수입 구성원", exact: true })).toHaveValue(
      uid(2),
    );
    await page.getByRole("button", { name: "지난달 수입에서 초안 불러오기", exact: true }).click();
    const picker = page.getByRole("region", { name: "지난달 수입 선택", exact: true });
    await expect(
      picker.getByLabel("지난달 수입 기록", { exact: true }).locator("option"),
    ).toHaveCount(2);
    await picker.getByLabel("지난달 수입 기록", { exact: true }).selectOption(previous.id);
    await picker
      .getByRole("button", { name: "선택한 기록으로 새 초안 만들기", exact: true })
      .click();
    await expect(page.getByLabel("수입 금액 (원)", { exact: true })).toHaveValue("1234567");
    await expect(page.getByLabel("수입 귀속월", { exact: true })).toHaveValue("2025-02");
    expect(state.writes).toHaveLength(0);
    await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
    await expect(page.getByRole("region", { name: "수입 중복 검토", exact: true })).toContainText(
      "3,000,000원",
    );
    expect(state.writes).toHaveLength(0);
    await page.getByLabel("기존 기록과 별개의 수입임을 확인했어요.", { exact: true }).check();
    await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
    await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
    expect(state.writes).toHaveLength(1);
    expect(state.writes[0]!.body).toMatchObject({
      period_month: "2025-02",
      amount_krw: "1234567",
      occurred_on: null,
      duplicate_acknowledged: true,
    });
    expect(previous.period_month).toBe("2025-01");
    if (native) expect(native.http).toEqual([]);
  });

test("a previous daily income leaves the new actual date empty and honors a chosen member", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const previous = incomeRow(500, {
    member_id: uid(5),
    period_month: "2025-01",
    date_precision: "day",
    occurred_on: "2025-01-19",
  });
  state.incomes.push(previous);
  await page.goto("/income/new");
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(5));
  await page.getByRole("button", { name: "지난달 수입에서 초안 불러오기", exact: true }).click();
  await page.getByLabel("지난달 수입 기록", { exact: true }).selectOption(previous.id);
  await page.getByRole("button", { name: "선택한 기록으로 새 초안 만들기", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "수입 구성원", exact: true })).toHaveValue(
    uid(5),
  );
  await expect(page.getByLabel("실제 입금일", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  expect(state.writes).toHaveLength(0);
});

test("single-event full allocation fills only a draft and is unavailable for multiple allocations", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  const count = state.payouts.length;
  await page.goto(`/insurance/payouts/new?case=${uid(90)}`);
  await page.getByLabel("보험금 수령 금액 (원)", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "받은 전액을 이 사건에 배분", exact: true }).click();
  await expect(page.getByLabel("사건 배분금액 (원)", { exact: true })).toHaveValue("123456");
  expect(state.payouts).toHaveLength(count);
  await page.getByRole("button", { name: "사건 배분 추가", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "받은 전액을 이 사건에 배분", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "배분 2 제거", exact: true }).click();
  await page.getByRole("button", { name: "실제 보험금 수령 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험금 수령 상세", exact: true })).toBeVisible();
  expect(state.payouts).toHaveLength(count + 1);
  expect(state.payouts.at(-1)!.allocations[0]!.amount_krw).toBe("123456");
});

for (const platform of ["web", "native"] as const)
  test(`${platform} copied income retries a lost response without creating a second receipt`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    state.incomes = [incomeRow(500, { period_month: "2025-01", amount_krw: "1234567" })];
    const native = platform === "native" ? await mockNativeCashflow(page, state) : null;
    await page.goto("/income/new");
    await page.getByRole("button", { name: "지난달 수입에서 초안 불러오기", exact: true }).click();
    await page.getByLabel("지난달 수입 기록", { exact: true }).selectOption(uid(500));
    await page.getByRole("button", { name: "선택한 기록으로 새 초안 만들기", exact: true }).click();
    state.failure = "after";
    await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
    await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
    expect(state.incomes.filter((row) => row.period_month === "2025-02")).toHaveLength(1);
    expect(state.writes).toHaveLength(2);
    expect(state.writes[1]).toEqual(state.writes[0]);
    if (native) expect(native.http).toEqual([]);
  });

test("earned income is the primary metric while insurance remains separately labeled", async ({
  page,
}) => {
  await mockCashflow(page);
  await page.goto("/income");
  const summary = page.getByRole("region", { name: "등록 수입 요약", exact: true });
  await expect(summary.locator(".metric-primary")).toContainText("근로·부수입 순액");
  await expect(summary.locator(".metric-primary")).toContainText("3,200,000원");
  await expect(summary).toContainText("보험금 순유입");
  await expect(summary).toContainText("800,000원");
});
