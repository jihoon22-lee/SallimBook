import { openDisclosure } from "./support/task-ui";
import { expect, test } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
// React dispatch simulation; this does not replace native policy/JVM or device verification.
test("native income workflow uses all ten typed commands and never WebView HTTP", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.incomes = state.incomes.filter((row) => row.id !== uid(40));
  const native = await mockNativeCashflow(page, state);
  await page.goto("/income");
  await page.getByRole("link", { name: "수입 입력", exact: true }).click();
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("1000");
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await page.getByRole("link", { name: "수입 정정", exact: true }).click();
  await page.getByLabel("수입 금액 (원)", { exact: true }).fill("1001");
  await page.getByLabel("정정 사유", { exact: true }).fill("합성 앱 정정");
  await page.getByRole("button", { name: "수입 정정 저장", exact: true }).click();
  await page.getByRole("button", { name: "수입 반환 기록", exact: true }).click();
  await page.getByLabel("반환 금액 (원)", { exact: true }).fill("1");
  await page.getByLabel("실제 반환일", { exact: true }).fill("2025-02-20");
  await page.getByLabel("반환 사유", { exact: true }).fill("합성 앱 반환");
  await page.getByRole("button", { name: "반환 기록 저장", exact: true }).click();
  await page.getByRole("button", { name: "무효 처리 검토", exact: true }).click();
  await page.getByLabel("무효 사유", { exact: true }).fill("합성 앱 반환 무효");
  await page.getByRole("button", { name: "사유와 함께 무효 처리", exact: true }).click();
  await expect(page.getByText("무효 기록 · 버전 2", { exact: true })).toBeVisible();
  await page.goto("/income/convert");
  await page.getByRole("combobox", { name: "전환 구성원", exact: true }).selectOption(uid(2));
  await page.getByRole("button", { name: "원본 수입 전체 확인", exact: true }).click();
  await page.getByLabel("실제 입금일", { exact: true }).fill("2025-02-20");
  await page.getByLabel("전환 사유", { exact: true }).fill("합성 앱 일별 전환");
  await page.getByLabel("원본 전체와 같은 합계의 대체 기록을 확인했어요.", { exact: true }).check();
  await page.getByRole("button", { name: "합계를 유지하고 전환", exact: true }).click();
  await expect(page).toHaveURL(/\/income$/);
  for (const method of [
    "listIncome",
    "incomeSummary",
    "incomeDuplicateCandidates",
    "getIncome",
    "incomeHistory",
    "createIncome",
    "correctIncome",
    "returnIncome",
    "voidIncome",
    "convertIncomePrecision",
  ])
    expect(native.calls.some((call) => call.method === method)).toBe(true);
  expect(native.http).toEqual([]);
  expect(native.calls.find((call) => call.method === "correctIncome")!.args.ifMatch).toBe('"1"');
  expect(
    native.calls.find((call) => call.method === "returnIncome")!.args.input.member_id,
  ).toBeUndefined();
});
test("native card metadata create edit close and delete use six named methods and closure query", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const native = await mockNativeCashflow(page, state);
  await page.goto("/cards/new");
  await page.getByRole("combobox", { name: "카드 소유자", exact: true }).selectOption(uid(2));
  await page.getByLabel("카드사", { exact: true }).fill("합성 앱 카드사");
  await page.getByLabel("카드명", { exact: true }).fill("합성 앱 카드");
  await page.getByLabel("마지막 네 자리 (선택)", { exact: true }).fill("3333");
  await page.getByRole("button", { name: "카드 등록 저장", exact: true }).click();
  await page.getByRole("link", { name: "카드 정보 수정", exact: true }).click();
  await page.getByLabel("카드 별칭", { exact: true }).fill("합성 앱 별칭");
  await page.getByRole("button", { name: "카드 변경 저장", exact: true }).click();
  await page.getByRole("button", { name: "카드 사용 종료", exact: true }).click();
  await page.getByRole("button", { name: "카드 사용 종료 저장", exact: true }).click();
  await expect(page.getByRole("button", { name: "카드 사용 종료", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "오등록 삭제 검토", exact: true }).click();
  await page
    .getByLabel("잘못 등록한 카드이며 실제 삭제할 것을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "오등록 카드 삭제", exact: true }).click();
  await expect(page).toHaveURL(/\/cards$/);
  for (const method of [
    "listCards",
    "getCard",
    "createCard",
    "updateCard",
    "archiveCard",
    "deleteCard",
    "getCardPaymentLinks",
  ])
    await expect.poll(() => native.calls.some((call) => call.method === method)).toBe(true);
  expect(native.http).toEqual([]);
  expect(native.calls.find((call) => call.method === "archiveCard")!.args.input).toEqual({
    ended_on: "2025-02-20",
    closure_ack: false,
  });
});
test("native rule creation revision end and explicit generation use typed DTO and operation keys", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const native = await mockNativeCashflow(page, state);
  await page.goto("/fixed-payments/rules/new");
  await page.getByLabel("규칙 이름", { exact: true }).fill("합성 앱 규칙");
  await page.getByLabel("원화 예정금액 (원)", { exact: true }).fill("100");
  await page.getByLabel("주기 기준일", { exact: true }).fill("2025-01-31");
  await page.getByLabel("적용 시작일", { exact: true }).fill("2025-01-01");
  await page.getByRole("button", { name: "납부 규칙 저장", exact: true }).click();
  await page.getByRole("link", { name: "규칙 적용기간 변경", exact: true }).click();
  await page.getByLabel("원화 예정금액 (원)", { exact: true }).fill("101");
  await page.getByLabel("적용 시작일", { exact: true }).fill("2025-03-01");
  await page.getByLabel("규칙 변경 사유", { exact: true }).fill("합성 앱 새 요금");
  await page.getByRole("button", { name: "새 적용기간 저장", exact: true }).click();
  await page.getByRole("button", { name: "납부 규칙 종료 검토", exact: true }).click();
  await page.getByLabel("규칙 종료 적용일", { exact: true }).fill("2025-04-01");
  await page.getByLabel("규칙 종료 사유", { exact: true }).fill("합성 앱 종료");
  await page
    .getByLabel("종료 적용일 이후의 미래 미납 회차가 바뀌는 것을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "납부 규칙 종료 저장", exact: true }).click();
  await expect(page.getByText("종료 사유: 합성 앱 종료", { exact: true })).toBeVisible();
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "예정 회차 생성 열기", exact: true }).click();
  await page.getByRole("button", { name: "선택 기간 회차 생성", exact: true }).click();
  await expect(
    page.getByText("요청한 기간의 회차 생성을 확인했어요. 예정 월 목록에서 확인해 주세요.", {
      exact: true,
    }),
  ).toBeVisible();
  for (const method of [
    "listRecurringRules",
    "getRecurringRule",
    "createRecurringRule",
    "changeRecurringRule",
    "endRecurringRule",
    "generateObligations",
    "listObligations",
    "fixedCostSummary",
  ])
    expect(native.calls.some((call) => call.method === method)).toBe(true);
  expect(native.calls.find((call) => call.method === "changeRecurringRule")!.args.ifMatch).toBe(
    '"1"',
  );
  expect(native.calls.find((call) => call.method === "endRecurringRule")!.args.ifMatch).toBe('"2"');
  expect(native.http).toEqual([]);
});
test("native occurrence actions and actual payment cancellation use resource-specific versions", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const native = await mockNativeCashflow(page, state);
  await page.goto(`/fixed-payments/${uid(70)}`);
  for (const action of ["예정일 변경", "회차 건너뛰기", "건너뛰기 되돌리기"]) {
    await openDisclosure(page, "예정일 변경·회차 관리");
    await page.getByRole("button", { name: action, exact: true }).click();
    if (action === "예정일 변경")
      await page.getByLabel("변경할 예정일", { exact: true }).fill("2025-02-27");
    await page.getByLabel("회차 변경 사유", { exact: true }).fill(`합성 앱 ${action}`);
    await page.getByRole("button", { name: `${action} 저장`, exact: true }).click();
    await expect(page.getByRole("heading", { name: action, exact: true })).toHaveCount(0);
  }
  await page.getByRole("button", { name: "실제 납부 기록", exact: true }).click();
  await page.getByLabel("실제 납부금액 (원)", { exact: true }).fill("10000");
  await page.getByLabel("실제 납부일", { exact: true }).fill("2025-02-20");
  await page.getByRole("button", { name: "실제 납부 저장", exact: true }).click();
  for (const action of ["수동 납부 완료", "수동 완료 재개"]) {
    await openDisclosure(page, "예정일 변경·회차 관리");
    await page.getByRole("button", { name: action, exact: true }).click();
    await page.getByLabel("회차 변경 사유", { exact: true }).fill(`합성 앱 ${action}`);
    await page.getByRole("button", { name: `${action} 저장`, exact: true }).click();
    await expect(page.getByRole("heading", { name: action, exact: true })).toHaveCount(0);
  }
  await page.getByRole("button", { name: "이 납부 무효 검토", exact: true }).click();
  await page.getByLabel("납부 무효 사유", { exact: true }).fill("합성 앱 납부 무효");
  await page.getByRole("button", { name: "사유와 함께 납부 무효 처리", exact: true }).click();
  await expect(page.getByText("0원 / 0원 / 0원", { exact: true })).toBeVisible();
  for (const method of [
    "getObligation",
    "obligationHistory",
    "rescheduleObligation",
    "skipObligation",
    "unskipObligation",
    "completeObligation",
    "reopenObligation",
    "settleObligation",
    "listObligationSettlements",
    "voidFixedSettlement",
  ])
    expect(native.calls.some((call) => call.method === method)).toBe(true);
  expect(native.calls.find((call) => call.method === "voidFixedSettlement")!.args.ifMatch).toBe(
    '"1"',
  );
  expect(native.http).toEqual([]);
});
test("native linked-account closure carries date-bound digest through asset archive", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.linksRequired = true;
  const native = await mockNativeCashflow(page, state);
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "계좌 사용 종료하기", exact: true }).click();
  await page
    .getByRole("region", { name: "사용 종료 영향 확인", exact: true })
    .getByRole("checkbox")
    .check();
  await page.getByRole("button", { name: "계좌 사용 종료 확인", exact: true }).click();
  await expect(page.getByRole("button", { name: "계좌 사용 종료하기", exact: true })).toHaveCount(
    0,
  );
  expect(native.calls.find((call) => call.method === "getAccountPaymentLinks")!.args).toMatchObject(
    { resourceId: uid(30), query: { as_of_date: "2025-02-20" } },
  );
  expect(native.calls.find((call) => call.method === "archiveAsset")!.args.input).toEqual({
    ended_on: "2025-02-20",
    closure_ack: true,
    usage_digest: "1".padStart(64, "0"),
  });
  expect(native.http).toEqual([]);
});
for (const failure of ["APP_LOCKED", "SESSION_EXPIRED", "NETWORK_UNAVAILABLE"] as const)
  test(`native cashflow ${failure} remains closed to web fallback`, async ({ page }) => {
    const state = await mockCashflow(page);
    const native = await mockNativeCashflow(page, state, failure);
    await page.goto("/income");
    if (failure === "APP_LOCKED")
      await expect(page.getByRole("status").filter({ hasText: "앱이 잠겨 있어요" })).toBeVisible();
    else if (failure === "SESSION_EXPIRED")
      await expect(
        page.getByRole("heading", { name: "로그인이 필요해요", exact: true }),
      ).toBeVisible();
    else await expect(page.getByRole("alert").first()).toBeVisible();
    expect(native.http).toEqual([]);
    expect(state.writes).toHaveLength(0);
  });
