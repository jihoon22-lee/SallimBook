import { openDisclosure } from "./support/task-ui";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import catalog from "../../../packages/test-fixtures/catalog.json" with { type: "json" };
import { claimRow, expenseRow, mockInsuranceEvents, payoutRow } from "./support/insurance-events";
import { policyRow } from "./support/insurance";

test("claim payout-list action preserves its case policy and claim through receipt creation", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  const currentClaim = claimRow(1200);
  state.claims.push(currentClaim);
  state.payouts = [];
  await page.goto(`/insurance/claims/${currentClaim.id}`);
  await page.getByRole("link", { name: "실제 보험금 수령 추가", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "배분 사건", exact: true })).toHaveValue(
    currentClaim.case_id,
  );
  await expect(page.getByRole("combobox", { name: "배분 보험계약", exact: true })).toHaveValue(
    currentClaim.policy_id,
  );
  await expect(page.getByRole("combobox", { name: "배분 청구 (선택)", exact: true })).toHaveValue(
    currentClaim.id,
  );
  await page.getByLabel("보험금 수령 금액 (원)", { exact: true }).fill("10000");
  await page.getByLabel("사건 배분금액 (원)", { exact: true }).fill("10000");
  await page
    .getByLabel("실제 입금 한 건과 같은 합계의 사건별 배분을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "실제 보험금 수령 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험금 수령 상세", exact: true })).toBeVisible();
  expect(state.payouts).toHaveLength(1);
  expect(state.payouts[0]!.allocations[0]).toMatchObject({
    case_id: currentClaim.case_id,
    policy_id: currentClaim.policy_id,
    claim_id: currentClaim.id,
  });
  await page.goto(`/insurance/claims/${currentClaim.id}`);
  await expect(page.getByRole("link", { name: "입금 원본 10,000원", exact: true })).toBeVisible();
});
import { closedAccount, uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
async function newExpense(page: Page, amount = "30000") {
  await page.goto(`/insurance/expenses/new?case=${uid(90)}&node=${uid(91)}`);
  await page.getByLabel("의료비 지불 금액 (원)", { exact: true }).fill(amount);
}
async function claim(page: Page, policyId = uid(80), reference = "합성 청구") {
  await page.goto(`/insurance/claims/new?case=${uid(90)}&policy=${policyId}`);
  await page.getByLabel("청구 접수번호 (선택)", { exact: true }).fill(reference);
  await page.getByRole("checkbox", { name: /SYNTHETIC-RECEIPT-1001/ }).check();
  await page.getByRole("button", { name: "청구 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험 청구 상세", exact: true })).toBeVisible();
}
async function voidCurrent(page: Page, name: string) {
  await page.getByRole("button", { name: `${name} 무효 검토`, exact: true }).click();
  await page.getByLabel("금전 기록 무효 사유", { exact: true }).fill("합성 오등록 무효");
  await page
    .getByLabel("실제 환불·반환이 아닌 오등록 무효임을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "사유와 함께 금전 기록 무효 처리", exact: true }).click();
}
test("T-12 through T-14 original medical payments stay 960000 after two contracts reference one receipt", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.core.policies.push({ ...policyRow(84), product_name: "합성 정액 계약" });
  await claim(page);
  await claim(page, uid(84), "합성 두 번째 청구");
  await page.goto(`/insurance/cases/${uid(90)}`);
  const summary = page.getByRole("region", { name: "사건 실제 비용과 순부담", exact: true });
  await expect(summary).toContainText("의료 지불금960,000원");
  await expect(summary).toContainText("실제 보험금 수령800,000원");
  await expect(summary).toContainText("순현금부담160,000원");
  expect(state.expenses).toHaveLength(catalog.fixtures.medical_case.expenses.length);
  expect(state.claims.map((c) => c.expense_ids)).toEqual([[uid(1001)], [uid(1001)]]);
  expect(state.payouts).toHaveLength(2);
});
test("claim retry after an unknown result reuses its key and records one claim", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.failure = "after";
  await page.goto(`/insurance/claims/new?case=${uid(90)}&policy=${uid(80)}`);
  await page.getByLabel("청구 접수번호 (선택)", { exact: true }).fill("합성 재시도 청구");
  await page.getByRole("checkbox", { name: /SYNTHETIC-RECEIPT-1001/ }).check();
  const save = page.getByRole("button", { name: "청구 기록 저장", exact: true });
  await save.click();
  await page
    .getByRole("button", { name: "목록에서 등록되지 않은 것을 확인했어요", exact: true })
    .click();
  await save.click();
  await expect(page.getByRole("heading", { name: "보험 청구 상세", exact: true })).toBeVisible();
  const creates = state.writes.filter((w) => w.method === "POST" && w.path.endsWith("/claims"));
  expect(creates).toHaveLength(2);
  expect(creates[0]!.key).toMatch(/^[0-9a-f-]{36}$/);
  expect(creates[1]!.key).toBe(creates[0]!.key);
  expect(state.claims).toHaveLength(1);
});
test("receipt details must exactly decompose actual payment and never add gross hospital cost", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.expenses = [];
  await newExpense(page, "860000");
  await openDisclosure(page, "영수증 참고 정보 (선택)");
  await page.getByLabel("병원 총진료비 참고 (원)", { exact: true }).fill("1000000");
  await page.getByLabel("공단 부담액 참고 (원)", { exact: true }).fill("140000");
  for (const [index, amount] of ["600000", "259999"].entries()) {
    await page.getByRole("button", { name: "영수증 명세 추가", exact: true }).click();
    const line = page.getByRole("region", { name: `영수증 명세 ${index + 1}`, exact: true });
    await line.getByLabel("명세 이름", { exact: true }).fill(`합성 설명 ${index + 1}`);
    await line.getByLabel("명세 금액 (원)", { exact: true }).fill(amount);
  }
  await page.getByRole("button", { name: "실제 의료비 저장", exact: true }).click();
  await expect(
    page.getByText("명세 합계와 실제 지불금이 같아야 해요.", { exact: true }),
  ).toBeFocused();
  expect(state.writes).toHaveLength(0);
  await page
    .getByRole("region", { name: "영수증 명세 2", exact: true })
    .getByLabel("명세 금액 (원)", { exact: true })
    .fill("260000");
  await page.getByRole("button", { name: "실제 의료비 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "의료비 상세", exact: true })).toBeVisible();
  expect(state.expenses).toHaveLength(1);
  expect(state.expenses[0]!.cash.amount_krw).toBe("860000");
  expect(state.expenses[0]!.lines.map((l) => l.amount_krw)).toEqual(["600000", "260000"]);
  expect(state.expenses[0]!.gross_medical_krw).toBe("1000000");
});
test("prescription is not selectable as an expense source", async ({ page }) => {
  const state = await mockInsuranceEvents(page);
  await newExpense(page);
  const nodes = page.getByRole("combobox", { name: "비용 귀속 진료", exact: true });
  await expect(nodes.locator(`option[value="${uid(92)}"]`)).toHaveJSProperty("disabled", true);
  await page.goto(`/insurance/expenses/new?case=${uid(90)}&node=${uid(92)}`);
  await page.getByLabel("의료비 지불 금액 (원)", { exact: true }).fill("30000");
  await page.getByRole("button", { name: "실제 의료비 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "비용 사건·귀속 진료·지불 금액·실제 날짜를 확인해 주세요. 무금액 처방에는 비용을 연결할 수 없어요.",
  );
  expect(state.writes).toHaveLength(0);
});
for (const failure of ["before", "after"] as const)
  test(`expense ${failure} commit response loss preserves one idempotency identity`, async ({
    page,
  }) => {
    const state = await mockInsuranceEvents(page);
    state.failure = failure;
    await newExpense(page);
    await page.getByRole("button", { name: "실제 의료비 저장", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "실제 의료비 저장", exact: true }).click();
    await expect(page.getByRole("heading", { name: "의료비 상세", exact: true })).toBeVisible();
    expect(state.expenses).toHaveLength(6);
    expect(state.writes[0]!.key).toBeTruthy();
    expect(state.writes[1]!.key).toBe(state.writes[0]!.key);
  });
test("expense correction compares current domain version and preserves unrelated current note", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.conflict = true;
  await page.goto(`/insurance/expenses/${uid(1000)}/correct`);
  await page.getByLabel("의료비 지불 금액 (원)", { exact: true }).fill("31000");
  await page.getByLabel("의료비 정정 사유", { exact: true }).fill("합성 영수증 보완");
  await page
    .getByLabel("기존 의료비는 무효로 보존하고 새 원본으로 정정하는 것을 확인했어요.", {
      exact: true,
    })
    .check();
  await page.getByRole("button", { name: "의료비 정정 저장", exact: true }).click();
  await page.getByRole("button", { name: "의료비 현재 원본 비교", exact: true }).click();
  await page.getByRole("button", { name: "비교한 의료비 정정 유지", exact: true }).click();
  await expect(page.getByLabel("의료비 지불 금액 (원)", { exact: true })).toHaveValue("31000");
  await expect(page.getByRole("textbox", { name: "의료비 지불 메모", exact: true })).toHaveValue(
    "합성 다른 원본 메모",
  );
  await page
    .getByLabel("기존 의료비는 무효로 보존하고 새 원본으로 정정하는 것을 확인했어요.", {
      exact: true,
    })
    .check();
  await page.getByRole("button", { name: "의료비 정정 저장", exact: true }).click();
  await expect(page.getByRole("link", { name: "정정 전 원본 확인", exact: true })).toBeVisible();
  expect(state.expenses[0]!.cash.state).toBe("void");
  expect(state.expenses.at(-1)!.cash.amount_krw).toBe("31000");
  expect(state.writes.map((w) => w.version)).toEqual(['"7"', '"8"']);
});
test("T-15 hospital refund and T-16 insurance return keep separate originals and net burden 200000", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  await page.goto(`/insurance/expenses/${uid(1001)}/refunds/new`);
  await page
    .getByLabel("의료비 환불 금액 (원)", { exact: true })
    .fill(catalog.fixtures.medical_case.refund.amount_krw);
  await page.getByLabel("의료비 환불 사유", { exact: true }).fill("합성 병원 환불");
  await page.getByRole("button", { name: "의료비 환불 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "의료비 환불 상세", exact: true })).toBeVisible();
  expect(state.writes[0]!.version).toBe('"7"');
  await page.goto(`/insurance/payouts/${uid(1100)}/returns/new`);
  await page
    .getByRole("combobox", { name: "반환할 원래 배분", exact: true })
    .selectOption(uid(2100));
  await page
    .getByLabel("보험금 반환 금액 (원)", { exact: true })
    .fill(catalog.fixtures.insurance_return.amount_krw);
  await page.getByLabel("보험금 반환 사유", { exact: true }).fill("합성 보험사 반환");
  await page.getByRole("button", { name: "보험금 반환 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험금 반환 상세", exact: true })).toBeVisible();
  expect(state.writes[1]!.version).toBe('"5"');
  await page.goto(`/insurance/cases/${uid(90)}`);
  const summary = page.getByRole("region", { name: "사건 실제 비용과 순부담", exact: true });
  await expect(summary).toContainText("순의료비950,000원");
  await expect(summary).toContainText("순보험금750,000원");
  await expect(summary).toContainText("순현금부담200,000원");
  expect(state.expenses[1]!.cash.state).toBe("active");
  expect(state.payouts[0]!.cash.state).toBe("active");
});
test("refund correction and void preserve reversal history and enforce original refund cap", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  await page.goto(`/insurance/expenses/${uid(1000)}/refunds/new`);
  await page.getByLabel("의료비 환불 금액 (원)", { exact: true }).fill("30001");
  await page.getByLabel("의료비 환불 사유", { exact: true }).fill("합성 환불");
  await page.getByRole("button", { name: "의료비 환불 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "의료비 환불 금액·날짜·사유를 확인해 주세요. 금액은 남은 환불 가능액 이하여야 해요.",
  );
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("의료비 환불 금액 (원)", { exact: true }).fill("10000");
  await page.getByRole("button", { name: "의료비 환불 저장", exact: true }).click();
  await page.getByRole("link", { name: "의료비 환불 원본 정정", exact: true }).click();
  await page.getByLabel("의료비 환불 금액 (원)", { exact: true }).fill("20000");
  await page.getByLabel("의료비 환불 정정 사유", { exact: true }).fill("합성 반환액 보완");
  await page.getByRole("button", { name: "의료비 환불 정정 저장", exact: true }).click();
  await expect(page.getByRole("link", { name: "정정 전 원본 확인", exact: true })).toBeVisible();
  await voidCurrent(page, "의료비 환불");
  await expect(page.getByRole("link", { name: "의료비 환불 원본 정정", exact: true })).toHaveCount(
    0,
  );
  expect(state.refunds.map((r) => r.cash.state)).toEqual(["void", "void"]);
  expect(state.writes.map((w) => w.version)).toEqual(['"7"', '"1"', '"1"']);
});
test("T-18 one 500000 receipt requires T-19 equal multi-case allocation before saving", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.payouts = [];
  await page.goto(`/insurance/payouts/new?case=${uid(90)}`);
  await page.getByLabel("보험금 수령 금액 (원)", { exact: true }).fill("500000");
  const first = page.getByRole("region", { name: "보험금 배분 1", exact: true });
  await first.getByLabel("사건 배분금액 (원)", { exact: true }).fill("300000");
  await page.getByRole("button", { name: "사건 배분 추가", exact: true }).click();
  const second = page.getByRole("region", { name: "보험금 배분 2", exact: true });
  await second.getByRole("combobox", { name: "배분 사건", exact: true }).selectOption(uid(95));
  await second.getByLabel("사건 배분금액 (원)", { exact: true }).fill("150000");
  await page
    .getByLabel("실제 입금 한 건과 같은 합계의 사건별 배분을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "실제 보험금 수령 저장", exact: true }).click();
  await expect(
    page.getByText("배분 합계가 실제 입금액과 같아야 해요.", { exact: true }),
  ).toBeFocused();
  expect(state.writes).toHaveLength(0);
  await second.getByLabel("사건 배분금액 (원)", { exact: true }).fill("200000");
  await expect(
    page.getByLabel("실제 입금 한 건과 같은 합계의 사건별 배분을 확인했어요.", { exact: true }),
  ).not.toBeChecked();
  await page
    .getByLabel("실제 입금 한 건과 같은 합계의 사건별 배분을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "실제 보험금 수령 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험금 수령 상세", exact: true })).toBeVisible();
  expect(state.payouts).toHaveLength(1);
  expect(state.payouts[0]!.allocations.map((a) => a.amount_krw)).toEqual(["300000", "200000"]);
  expect(state.payouts[0]!.cash.amount_krw).toBe("500000");
  expect(state.writes[0]!.body.card_id).toBeUndefined();
});
test("direct payout later links a claim with typed history and creates no second receipt", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.claims.push(claimRow(1200, [uid(1001)]));
  const cashId = state.payouts[0]!.cash.id;
  await page.goto(`/insurance/payouts/${uid(1100)}`);
  await page.getByRole("button", { name: "배분 1 청구 연결 정정", exact: true }).click();
  await page
    .getByRole("combobox", { name: "배분 청구 (선택)", exact: true })
    .selectOption(uid(1200));
  await page.getByLabel("배분 연결 정정 사유", { exact: true }).fill("합성 접수번호 나중 확인");
  await page.getByRole("button", { name: "같은 입금의 청구 연결 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "배분 버전 2", exact: true })).toBeVisible();
  expect(state.payouts).toHaveLength(2);
  expect(state.payouts[0]!.cash.id).toBe(cashId);
  expect(state.payouts[0]!.allocations[0]!.claim_id).toBe(uid(1200));
  expect(state.writes[0]!.body).toEqual({ claim_id: uid(1200), reason: "합성 접수번호 나중 확인" });
});
test("claim corrections distinguish undecided from zero and preserve paged evidence history", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.claims.push(claimRow(1200, [uid(1001)]));
  state.pageSize = 1;
  await page.goto(`/insurance/claims/${uid(1200)}`);
  await expect(page.getByText("미입력", { exact: true }).first()).toBeVisible();
  await page.getByRole("link", { name: "청구 상태·근거 정정", exact: true }).click();
  await page.getByRole("combobox", { name: "청구 상태", exact: true }).selectOption("closed");
  await page.getByLabel("심사 결정액 (원)", { exact: true }).fill("0");
  await page.getByLabel("청구 정정 사유", { exact: true }).fill("합성 심사 결과 기록");
  await page.getByRole("button", { name: "청구 정정 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험 청구 상세", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "청구 이력 더 보기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "청구 버전 1", exact: true })).toBeVisible();
  expect(state.claims[0]!.decided_krw).toBe("0");
  expect(state.claims[0]!.claim_state).toBe("closed");
  expect(state.payouts).toHaveLength(2);
  expect(state.writes[0]!.key).toBeUndefined();
});
test("active claim evidence blocks expense void without deleting the original", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.claims.push(claimRow(1200, [uid(1001)]));
  await page.goto(`/insurance/expenses/${uid(1001)}`);
  await voidCurrent(page, "의료비");
  await expect(page.getByRole("alert")).toContainText("청구에 연결된 의료비");
  expect(state.expenses[1]!.cash.state).toBe("active");
  expect(state.expenses[1]!.version).toBe(7);
});
test("T-17 fixed benefit can exceed medical cost and the signed burden stays negative", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.expenses = [expenseRow(1000, "100000")];
  state.payouts = [payoutRow(1100, "150000", "fixed")];
  await page.goto(`/insurance/cases/${uid(90)}`);
  const summary = page.getByRole("region", { name: "사건 실제 비용과 순부담", exact: true });
  await expect(summary).toContainText("순현금부담-50,000원");
  await expect(summary).toContainText("정액: 수령 150,000원");
  await expect(summary).not.toContainText("순현금부담0원");
});
test("insurance return cap follows the selected allocation and correction preserves its source", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  const p = state.payouts[0]!;
  p.allocations[0]!.amount_krw = "300000";
  p.allocations.push({ ...p.allocations[0]!, id: uid(2102), case_id: uid(95) });
  p.allocation_count = 2;
  await page.goto(`/insurance/payouts/${p.id}/returns/new`);
  await page
    .getByRole("combobox", { name: "반환할 원래 배분", exact: true })
    .selectOption(uid(2100));
  await page.getByLabel("보험금 반환 금액 (원)", { exact: true }).fill("300001");
  await page.getByLabel("보험금 반환 사유", { exact: true }).fill("합성 반환 확인");
  await page.getByRole("button", { name: "보험금 반환 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "반환할 원래 배분과 보험금 반환 금액·날짜·사유를 확인해 주세요. 금액은 남은 반환 가능액 이하여야 해요.",
  );
  await page.getByLabel("보험금 반환 금액 (원)", { exact: true }).fill("50000");
  await page.getByRole("button", { name: "보험금 반환 저장", exact: true }).click();
  await page.getByRole("link", { name: "보험금 반환 원본 정정", exact: true }).click();
  await page.getByLabel("보험금 반환 금액 (원)", { exact: true }).fill("60000");
  await page.getByLabel("보험금 반환 정정 사유", { exact: true }).fill("합성 반환액 정정");
  await page.getByRole("button", { name: "보험금 반환 정정 저장", exact: true }).click();
  await expect(page.getByRole("link", { name: "정정 전 원본 확인", exact: true })).toBeVisible();
  expect(state.returns.map((r) => r.original_allocation_id)).toEqual([uid(2100), uid(2100)]);
  expect(state.returns.map((r) => r.cash.state)).toEqual(["void", "active"]);
  expect(state.writes.at(-1)!.body.card_id).toBeUndefined();
  await voidCurrent(page, "보험금 반환");
  await expect(page.getByRole("link", { name: "보험금 반환 원본 정정", exact: true })).toHaveCount(
    0,
  );
});
test("payout correction uses the domain version and preserves the prior original and reason", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  await page.goto(`/insurance/payouts/${uid(1100)}/correct`);
  await page.getByLabel("보험금 수령 금액 (원)", { exact: true }).fill("610000");
  await page.getByLabel("사건 배분금액 (원)", { exact: true }).fill("610000");
  await page.getByLabel("보험금 수령 정정 사유", { exact: true }).fill("합성 입금액 보완");
  await page
    .getByLabel("실제 입금 한 건과 같은 합계의 사건별 배분을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "보험금 수령 정정 저장", exact: true }).click();
  await expect(page.getByRole("link", { name: "정정 전 원본 확인", exact: true })).toBeVisible();
  expect(state.payouts[0]!.cash.state).toBe("void");
  expect(state.payouts.at(-1)!.cash.amount_krw).toBe("610000");
  expect(state.writes[0]!.version).toBe('"5"');
  expect(state.writes.every((w) => w.path.includes("/insurance/"))).toBe(true);
});

test("an expense dated on an account's last day can use that account", async ({ page }) => {
  const state = await mockInsuranceEvents(page);
  state.cashflow.finance.accounts.push(closedAccount(33, "2025-02-15"));
  await newExpense(page);
  const closed = page.getByRole("option", {
    name: /^합성 종료 계좌 자산 · .* · 2025\.02\.15 사용 종료$/,
  });
  await page.getByRole("combobox", { name: "납부수단 구분", exact: true }).selectOption("account");
  await page.getByLabel("의료비 지불 실제 날짜", { exact: true }).fill("2025-02-16");
  await expect(closed).toHaveCount(0);
  await page.getByLabel("의료비 지불 실제 날짜", { exact: true }).fill("2025-02-15");
  await expect(closed).toHaveJSProperty("disabled", false);
});

test("ended policy stays selectable for a late claim and a direct allocation with a status note", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.core.policies.push({ ...policyRow(84), product_name: "합성 종료 계약", status: "ended" });
  await page.goto(`/insurance/claims/new?case=${uid(90)}`);
  const policy = page.getByRole("combobox", { name: "청구 보험계약", exact: true });
  const ended = policy.locator(`option[value="${uid(84)}"]`);
  await expect(ended).toHaveText("합성 보험사 · 합성 종료 계약 · 합성 구성원 둘 · 계약 종료");
  await expect(ended).toHaveJSProperty("disabled", false);
  await policy.selectOption(uid(84));
  await expect(
    page.getByText(
      "선택한 계약은 계약 종료 상태예요. 종료 전 진료에 대한 청구·보험금은 나중에도 기록할 수 있어요.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByRole("checkbox", { name: /SYNTHETIC-RECEIPT-1001/ }).check();
  await page.getByRole("button", { name: "청구 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험 청구 상세", exact: true })).toBeVisible();
  expect(state.claims.at(-1)!.policy_id).toBe(uid(84));
  await page.goto(`/insurance/payouts/new?case=${uid(90)}`);
  await expect(
    page
      .getByRole("combobox", { name: "배분 보험계약", exact: true })
      .locator(`option[value="${uid(84)}"]`),
  ).toHaveJSProperty("disabled", false);
});

test("correcting a refund keeps its reason and explains where the correction reason goes", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  await page.goto(`/insurance/expenses/${uid(1001)}/refunds/new`);
  await page.getByLabel("의료비 환불 금액 (원)", { exact: true }).fill("1000");
  await page.getByLabel("의료비 환불 사유", { exact: true }).fill("합성 본인부담 환불");
  await page.getByRole("button", { name: "의료비 환불 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "의료비 환불 상세", exact: true })).toBeVisible();
  await page.goto(`/insurance/refunds/${state.refunds.at(-1)!.id}/correct`);
  await expect(
    page.getByText(
      "원래 의료비 환불 사유 “합성 본인부담 환불”은 그대로 남아요. 정정 사유는 금전 이력에 기록돼요. 사유 자체가 틀렸다면 무효 처리 후 새로 기록해 주세요.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByLabel("의료비 환불 금액 (원)", { exact: true }).fill("900");
  await page.getByLabel("의료비 환불 정정 사유", { exact: true }).fill("합성 금액 오타 정정");
  await page.getByRole("button", { name: "의료비 환불 정정 저장", exact: true }).click();
  await expect(page.getByText("사유: 합성 본인부담 환불", { exact: true })).toBeVisible();
  expect(state.refunds.at(-1)!.reason).toBe("합성 본인부담 환불");
});

test("claim detail shows only this claim's received, returned and net amounts", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.claims.push({
    ...claimRow(1200, [uid(1001)]),
    received_krw: "600000",
    returned_krw: "50000",
    net_received_krw: "550000",
  });
  await page.goto(`/insurance/claims/${uid(1200)}`);
  await expect(
    page.getByText("이 청구의 실제 수령 600,000원 · 반환 50,000원 · 순수령 550,000원", {
      exact: true,
    }),
  ).toBeVisible();
});

test("case summary leads with the five specified totals in calculation order", async ({ page }) => {
  await mockInsuranceEvents(page);
  await page.goto(`/insurance/cases/${uid(90)}`);
  const summary = page.getByRole("region", { name: "사건 실제 비용과 순부담", exact: true });
  await expect(summary.locator("dl.metric-strip dt")).toHaveText([
    "의료 지불금",
    "환불",
    "순의료비",
    "순보험금",
    "순현금부담",
  ]);
  await expect(summary.locator("dl.metric-strip .metric-primary dt")).toHaveText("순현금부담");
  await expect(summary.getByText("의료 지불금", { exact: true })).toHaveCount(1);
});

test("an expense shows the claims citing it and a rule conflict does not offer a version compare", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.claims.push(claimRow(1200, [uid(1001)])); // The mock refuses voiding a cited expense with MEDICAL_EXPENSE_IN_CLAIM, like the server.
  await page.goto(`/insurance/expenses/${uid(1001)}`);
  const citing = page.getByRole("region", { name: "이 비용을 인용한 청구", exact: true });
  await expect(citing.getByRole("link")).toHaveCount(1);
  await expect(citing.getByRole("link").first()).toHaveAttribute(
    "href",
    `/insurance/claims/${uid(1200)}`,
  );
  await page.getByRole("button", { name: "의료비 무효 검토", exact: true }).click();
  await page.getByLabel("금전 기록 무효 사유", { exact: true }).fill("합성 오등록");
  await page
    .getByLabel("실제 환불·반환이 아닌 오등록 무효임을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "사유와 함께 금전 기록 무효 처리", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("청구에 연결된 의료비예요.");
  await expect(
    page.getByRole("button", { name: "무효 처리 전 원본 다시 비교", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "사유와 함께 금전 기록 무효 처리", exact: true }),
  ).toBeEnabled();
});

test("medical expense accepts grouped amounts and sends digits only", async ({ page }) => {
  const state = await mockInsuranceEvents(page);
  state.expenses = [];
  await newExpense(page, "30,000");
  await expect(page.getByText("30,000원", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "실제 의료비 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "의료비 상세", exact: true })).toBeVisible();
  expect(state.expenses[0]!.cash.amount_krw).toBe("30000");
});

test("new expense inherits its visit provider but uses the visit date only after explicit selection", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  await newExpense(page);
  await expect(page.getByLabel("지불 의료기관 (선택)", { exact: true })).toHaveValue(
    "합성 의료기관",
  );
  await expect(page.getByLabel("의료비 지불 실제 날짜", { exact: true })).toHaveValue("2025-02-20");
  await page.getByRole("button", { name: "진료 시작일을 실제 지불일로 사용", exact: true }).click();
  await expect(page.getByLabel("의료비 지불 실제 날짜", { exact: true })).toHaveValue("2025-02-01");
  await page.getByLabel("지불 의료기관 (선택)", { exact: true }).fill("합성 직접 확인한 기관");
  await page.getByRole("combobox", { name: "비용 귀속 진료", exact: true }).selectOption(uid(93));
  await expect(page.getByLabel("지불 의료기관 (선택)", { exact: true })).toHaveValue(
    "합성 직접 확인한 기관",
  );
  await page.getByRole("button", { name: "실제 의료비 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "의료비 상세", exact: true })).toBeVisible();
  expect(state.expenses.at(-1)).toMatchObject({
    provider_name: "합성 직접 확인한 기관",
    node_id: uid(93),
    cash: { occurred_on: "2025-02-01", amount_krw: "30000" },
  });
});

test("expense connection filter is explicit about its contract and persists through navigation", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  state.core.policies.push({ ...policyRow(84), product_name: "합성 정액 계약" });
  state.claims.push({ ...claimRow(), expense_ids: [uid(1001)] });
  await page.goto(`/insurance/cases/${uid(90)}`);
  const list = page.getByRole("region", { name: "사건의 의료비 원본", exact: true });
  await list.locator("summary").filter({ hasText: "비용 청구 연결 확인" }).click();
  const dialog = page.getByRole("dialog", { name: "비용 청구 연결 확인", exact: true });
  await expect(
    dialog.getByRole("combobox", { name: "선택 계약의 청구 연결", exact: true }),
  ).toBeDisabled();
  await dialog
    .getByRole("combobox", { name: "비용 청구 확인 계약", exact: true })
    .selectOption(uid(80));
  await dialog
    .getByRole("combobox", { name: "선택 계약의 청구 연결", exact: true })
    .selectOption("no");
  await dialog.getByRole("button", { name: "필터 닫기", exact: true }).click();
  await expect(list.getByText("영수증 SYNTHETIC-RECEIPT-1001", { exact: true })).toHaveCount(0);
  await expect(list.getByRole("listitem")).toHaveCount(4);
  await expect(page).toHaveURL(/expense_link=no/);
  await list.locator("summary").filter({ hasText: "비용 청구 연결 확인" }).click();
  await dialog
    .getByRole("combobox", { name: "비용 청구 확인 계약", exact: true })
    .selectOption(uid(84));
  await dialog.getByRole("button", { name: "필터 닫기", exact: true }).click();
  await expect(list.getByRole("listitem")).toHaveCount(5);
  await page.reload();
  await expect(list.getByRole("listitem")).toHaveCount(5);
  expect(state.expenses).toHaveLength(5);
  expect(state.writes).toHaveLength(0);
});
