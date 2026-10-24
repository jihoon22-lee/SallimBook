import { openDisclosure } from "../tests/support/task-ui";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import catalog from "../../../packages/test-fixtures/catalog.json" with { type: "json" };
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as {
  login: string;
  password: string;
};
test.setTimeout(480_000);
test.use({ actionTimeout: 10_000, navigationTimeout: 15_000 });
// Real API/DB with synthetic data only. Harness keeps failures and credentials private.
const lastId = (page: Page) => new URL(page.url()).pathname.split("/").at(-1)!;
async function createPolicy(page: Page, title: string) {
  await page.goto("/insurance/policies/new");
  await page.getByLabel("보험사", { exact: true }).fill("합성 HTTPS 보험사");
  await page.getByLabel("보험 상품명", { exact: true }).fill(title);
  await page
    .getByRole("combobox", { name: "보험 피보험자", exact: true })
    .selectOption({ label: "합성 HTTPS 구성원" });
  await page.getByLabel("보장 시작일", { exact: true }).fill("2025-01-01");
  await openDisclosure(page, "계약 기간·수익자·평가액·메모");
  await page.getByLabel("계약 시작일", { exact: true }).fill("2024-12-01");
  await page.getByLabel("납입 종료일", { exact: true }).fill("2030-12-31");
  await page.getByRole("button", { name: "보험 계약 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  return lastId(page);
}
async function createCase(page: Page, title: string) {
  await page.goto("/insurance/cases/new");
  await page.getByLabel("사건 이름", { exact: true }).fill(title);
  await page
    .getByRole("combobox", { name: "사건 환자", exact: true })
    .selectOption({ label: "합성 HTTPS 구성원" });
  await page.getByLabel("사건 시작일", { exact: true }).fill("2025-02-01");
  await page.getByRole("button", { name: "보험 사건 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  return lastId(page);
}
async function createNode(
  page: Page,
  caseId: string,
  kind: string,
  label: string,
  parent?: string,
) {
  await page.goto(`/insurance/cases/${caseId}${parent ? `/nodes/${parent}` : ""}`);
  await page
    .getByRole("button", {
      name: parent ? "이 진료 아래 추가" : "사건 아래 진료 추가",
      exact: true,
    })
    .click();
  await page.getByRole("combobox", { name: "진료 종류", exact: true }).selectOption(kind);
  await page.getByLabel("진료 이름", { exact: true }).fill(label);
  await page.getByLabel("의료기관·약국 이름", { exact: true }).fill("합성 HTTPS 의료기관");
  await page.getByLabel("진료 시작일", { exact: true }).fill("2025-02-10");
  await page.getByRole("button", { name: "진료 기록 저장", exact: true }).click();
  await expect(page.getByRole("region", { name: "선택한 진료", exact: true })).toContainText(label);
  return lastId(page);
}
async function createExpense(
  page: Page,
  caseId: string,
  nodeId: string,
  amount: string,
  reference: string,
  breakdown = false,
) {
  await page.goto(`/insurance/expenses/new?case=${caseId}&node=${nodeId}`);
  await page.getByLabel("의료비 지불 금액 (원)", { exact: true }).fill(amount);
  await expect(page.getByLabel("지불 의료기관 (선택)", { exact: true })).toHaveValue(
    "합성 HTTPS 의료기관",
  );
  const suggestion = page.getByRole("button", {
    name: "진료 시작일을 실제 지불일로 사용",
    exact: true,
  });
  if (await suggestion.count()) await suggestion.click();
  await page.getByLabel("의료비 지불 실제 날짜", { exact: true }).fill("2025-02-10");
  await openDisclosure(page, "영수증 참고 정보 (선택)");
  await page.getByLabel("지불 의료기관 (선택)", { exact: true }).fill("합성 HTTPS 의료기관");
  await page.getByLabel("영수증 참고번호 (선택)", { exact: true }).fill(reference);
  if (breakdown) {
    await page.getByLabel("병원 총진료비 참고 (원)", { exact: true }).fill("1000000");
    await page.getByLabel("공단 부담액 참고 (원)", { exact: true }).fill("140000");
    for (const [index, amount] of ["600000", "260000"].entries()) {
      await page.getByRole("button", { name: "영수증 명세 추가", exact: true }).click();
      const line = page.getByRole("region", { name: `영수증 명세 ${index + 1}`, exact: true });
      await line.getByLabel("명세 이름", { exact: true }).fill(`합성 HTTPS 명세 ${index + 1}`);
      await line.getByLabel("명세 금액 (원)", { exact: true }).fill(amount);
    }
  }
  await page.getByRole("button", { name: "실제 의료비 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "의료비 상세", exact: true })).toBeVisible();
  return lastId(page);
}
async function createClaim(page: Page, caseId: string, policyId: string, reference: string) {
  await page.goto(`/insurance/claims/new?case=${caseId}&policy=${policyId}`);
  await page.getByLabel("청구 접수번호 (선택)", { exact: true }).fill(reference);
  await page.getByLabel("직접 입력한 청구액 (원)", { exact: true }).fill("600000");
  await page.getByRole("checkbox", { name: /HTTPS-INPATIENT/ }).check();
  await page.getByRole("button", { name: "청구 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험 청구 상세", exact: true })).toBeVisible();
  return lastId(page);
}
async function createPayout(
  page: Page,
  caseId: string,
  policyId: string,
  amount: string,
  benefit = "reimbursement",
  secondCase?: string,
) {
  await page.goto(`/insurance/payouts/new?case=${caseId}&policy=${policyId}`);
  await page.getByLabel("보험금 수령 금액 (원)", { exact: true }).fill(amount);
  await page.getByLabel("보험금 수령 실제 날짜", { exact: true }).fill("2025-02-15");
  const first = page.getByRole("region", { name: "보험금 배분 1", exact: true });
  await first.getByRole("combobox", { name: "배분 급부유형", exact: true }).selectOption(benefit);
  if (secondCase) await first.getByLabel("사건 배분금액 (원)", { exact: true }).fill("300000");
  else await page.getByRole("button", { name: "받은 전액을 이 사건에 배분", exact: true }).click();
  if (secondCase) {
    await page.getByRole("button", { name: "사건 배분 추가", exact: true }).click();
    const second = page.getByRole("region", { name: "보험금 배분 2", exact: true });
    await second.getByRole("combobox", { name: "배분 사건", exact: true }).selectOption(secondCase);
    await second.getByLabel("사건 배분금액 (원)", { exact: true }).fill("150000");
    await page
      .getByLabel("실제 입금 한 건과 같은 합계의 사건별 배분을 확인했어요.", { exact: true })
      .check();
    // A mismatched total keeps save enabled and explains the reason on submit.
    await page.getByRole("button", { name: "실제 보험금 수령 저장", exact: true }).click();
    await expect(
      page.getByText("배분 합계가 실제 입금액과 같아야 해요.", { exact: true }),
    ).toBeFocused();
    await second.getByLabel("사건 배분금액 (원)", { exact: true }).fill("200000");
  }
  await page
    .getByLabel("실제 입금 한 건과 같은 합계의 사건별 배분을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "실제 보험금 수령 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험금 수령 상세", exact: true })).toBeVisible();
  return lastId(page);
}
async function refund(page: Page, expenseId: string, amount: string) {
  await page.goto(`/insurance/expenses/${expenseId}/refunds/new`);
  await page.getByLabel("의료비 환불 금액 (원)", { exact: true }).fill(amount);
  await page.getByLabel("의료비 환불 실제 날짜", { exact: true }).fill("2025-02-18");
  await page.getByLabel("의료비 환불 사유", { exact: true }).fill("합성 HTTPS 병원 환불");
  await page.getByRole("button", { name: "의료비 환불 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "의료비 환불 상세", exact: true })).toBeVisible();
}
async function returned(page: Page, payoutId: string, amount: string) {
  await page.goto(`/insurance/payouts/${payoutId}/returns/new`);
  await page
    .getByRole("combobox", { name: "반환할 원래 배분", exact: true })
    .selectOption({ index: 1 });
  await page.getByLabel("보험금 반환 금액 (원)", { exact: true }).fill(amount);
  await page.getByLabel("보험금 반환 실제 날짜", { exact: true }).fill("2025-02-18");
  await page.getByLabel("보험금 반환 사유", { exact: true }).fill("합성 HTTPS 보험사 반환");
  await page.getByRole("button", { name: "보험금 반환 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "보험금 반환 상세", exact: true })).toBeVisible();
}
async function voidCurrent(page: Page, label: string) {
  await page.getByRole("button", { name: `${label} 무효 검토`, exact: true }).click();
  await page.getByLabel("금전 기록 무효 사유", { exact: true }).fill("합성 HTTPS 오등록 무효");
  await page
    .getByLabel("실제 환불·반환이 아닌 오등록 무효임을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "사유와 함께 금전 기록 무효 처리", exact: true }).click();
  await expect(page.getByRole("button", { name: `${label} 무효 검토`, exact: true })).toHaveCount(
    0,
  );
}

test("real insurance policies cases medical originals claims receipts corrections and returns preserve exact totals", async ({
  page,
}) => {
  let missingNoStore = false;
  let missingKey = false;
  page.on("response", (r) => {
    if (
      r.url().includes("/api/v1/insurance/") &&
      r.status() >= 200 &&
      r.status() < 300 &&
      !r.headers()["cache-control"]?.includes("no-store")
    )
      missingNoStore = true;
  });
  page.on("request", (r) => {
    if (
      ["POST", "PATCH"].includes(r.method()) &&
      /\/api\/v1\/insurance\/(medical-expenses|medical-refunds|payouts|returns|payout-allocations)(\/|$)/.test(
        new URL(r.url()).pathname,
      ) &&
      !r.headers()["idempotency-key"]
    )
      missingKey = true;
  });
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
  await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 보험 HTTPS");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
  ).toBeVisible();
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  await page.goto("/accounts/new");
  await page.getByLabel("금융기관", { exact: true }).fill("합성 보험 검증 기관");
  await page.getByLabel("계좌 유형", { exact: true }).selectOption("checking");
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 보험 독립 잔액");
  await page.getByLabel("소유 방식", { exact: true }).selectOption("joint");
  await page.getByLabel("가계 지분 (%)", { exact: true }).fill("100");
  await page.getByLabel("금액 입력 기준", { exact: true }).selectOption("owned");
  await page.getByLabel("보유 시작일", { exact: true }).fill("2025-01-01");
  await page.getByRole("button", { name: "계좌 등록", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 보험 독립 잔액", exact: true }),
  ).toBeVisible();
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await page.getByRole("button", { name: "합성 보험 독립 잔액 금액 확인", exact: true }).click();
  await page.getByLabel("확인 금액 (원)", { exact: true }).fill("5000000");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await page.getByRole("button", { name: "월 확정 검토", exact: true }).click();
  await page.getByRole("button", { name: "확인하고 월 확정", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "정정 사유 남기고 다시 열기", exact: true }),
  ).toBeVisible();
  const snapshot = await page.evaluate(async () => {
    const row = await fetch("/api/v1/asset-months/2025-02").then((r) => r.json());
    return {
      version: row.version,
      revision: row.revision_id,
      values: row.values.map((v: { asset_id: string; input_amount_krw: string }) => [
        v.asset_id,
        v.input_amount_krw,
      ]),
    };
  });
  for (const kind of ["policy", "case"]) {
    if (kind === "policy") await createPolicy(page, "합성 HTTPS 오등록 계약");
    else await createCase(page, "합성 HTTPS 오등록 사건");
    const noun = kind === "policy" ? "계약" : "사건";
    await page.getByRole("button", { name: `오등록 ${noun} 삭제 검토`, exact: true }).click();
    await page
      .getByLabel("연결 기록과 변경 이력이 없는 오등록 항목임을 확인했어요.", { exact: true })
      .check();
    await page.getByRole("button", { name: `오등록 ${noun} 삭제`, exact: true }).click();
    await expect(page).toHaveURL(kind === "policy" ? "/insurance/policies" : "/insurance/cases");
  }
  const policyA = await createPolicy(page, "합성 HTTPS 실손 계약");
  await page.getByRole("button", { name: "증권번호 등록·변경", exact: true }).click();
  await page.getByLabel("새 증권번호", { exact: true }).fill("SYNTHETIC-HTTPS-POLICY");
  await page.getByRole("button", { name: "증권번호 저장", exact: true }).click();
  await page.bringToFront();
  await page.getByRole("button", { name: "전체 증권번호 30초 보기", exact: true }).click();
  await expect
    .poll(() => page.evaluate(() => Boolean(document.querySelector("output")?.textContent)))
    .toBe(true);
  await page.evaluate(() => dispatchEvent(new Event("pagehide")));
  expect(await page.evaluate(() => !document.querySelector("output")?.textContent)).toBe(true);
  await page.getByRole("button", { name: "보장 항목 추가", exact: true }).click();
  await page.getByLabel("보장 이름", { exact: true }).fill("합성 미정 보장금액");
  await page.getByRole("button", { name: "보장 항목 저장", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "보장 수정: 합성 미정 보장금액", exact: true }),
  ).toBeVisible();
  const policyB = await createPolicy(page, "합성 HTTPS 정액 계약");
  await page.goto("/fixed-payments/rules/new");
  await page.getByLabel("규칙 이름", { exact: true }).fill("합성 HTTPS 보험료");
  await page.getByLabel("원화 예정금액 (원)", { exact: true }).fill("30000");
  await page.getByLabel("주기 기준일", { exact: true }).fill("2025-01-15");
  await page.getByLabel("적용 시작일", { exact: true }).fill("2025-01-01");
  await page.getByRole("button", { name: "납부 규칙 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "납부 규칙 상세", exact: true })).toBeVisible();
  const ruleId = lastId(page);
  await page.goto(`/insurance/policies/${policyA}`);
  await page
    .getByRole("combobox", { name: "연결할 보험료 규칙", exact: true })
    .selectOption(ruleId);
  await page.getByRole("button", { name: "보험료 규칙 연결", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "보험료 적용기간 변경", exact: true }),
  ).toHaveAttribute("href", `/fixed-payments/rules/${ruleId}/edit`);
  console.log("SAFE_PHASE=INSURANCE_POLICY");
  const caseA = await createCase(page, "합성 HTTPS 첫 사건");
  const caseB = await createCase(page, "합성 HTTPS 두 번째 사건");
  const outpatient = await createNode(page, caseA, "outpatient", "합성 HTTPS 첫 외래");
  const prescription = await createNode(page, caseA, "prescription", "합성 HTTPS 처방", outpatient);
  const pharmacy = await createNode(page, caseA, "pharmacy", "합성 HTTPS 약국", prescription);
  const inpatient = await createNode(page, caseA, "inpatient", "합성 HTTPS 입원");
  await createNode(page, caseA, "surgery", "합성 HTTPS 수술 설명", inpatient);
  const follow = await createNode(page, caseA, "group", "합성 HTTPS 재진");
  const followA = await createNode(page, caseA, "follow_up", "합성 HTTPS 재진 1", follow);
  await page.getByRole("button", { name: "같은 단계 진료 추가", exact: true }).click();
  await page.getByLabel("진료 이름", { exact: true }).fill("합성 HTTPS 재진 2");
  await page.getByRole("button", { name: "저장하고 같은 단계 진료 추가", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("합성 HTTPS 재진 2 진료를 저장했어요");
  const savedVisit = page.getByRole("link", { name: "방금 저장한 진료 보기", exact: true });
  const followB = (await savedVisit.getAttribute("href"))!.split("/").at(-1)!;
  await savedVisit.click();
  await expect(page.getByRole("navigation", { name: "같은 단계 진료", exact: true })).toContainText(
    "합성 HTTPS 재진 1",
  );
  await page.setViewportSize({ width: 412, height: 915 });
  const nodes = [outpatient, inpatient, pharmacy, followA, followB];
  const expenseIds: string[] = [];
  for (const [index, source] of catalog.fixtures.medical_case.cash_records.entries())
    expenseIds.push(
      await createExpense(
        page,
        caseA,
        nodes[index]!,
        source.amount_krw,
        index === 1 ? "HTTPS-INPATIENT" : `HTTPS-RECEIPT-${index}`,
        index === 1,
      ),
    );
  const claimA = await createClaim(page, caseA, policyA, "HTTPS-CLAIM-A");
  await page.goto(`/insurance/cases/${caseA}?expense_policy=${policyA}&expense_link=yes`);
  const expenseList = page.getByRole("region", { name: "사건의 의료비 원본", exact: true });
  await expect(expenseList.getByRole("listitem")).toHaveCount(1);
  await expect(expenseList).toContainText("HTTPS-INPATIENT");
  await page.goto(`/insurance/cases/${caseA}?expense_policy=${policyB}&expense_link=no`);
  await expect(expenseList.getByRole("listitem")).toHaveCount(5);
  await createClaim(page, caseA, policyB, "HTTPS-CLAIM-B");
  const costs = await page.evaluate(async (id) => {
    const r = await fetch(`/api/v1/insurance/cases/${id}/summary`).then((r) => r.json());
    const expenses = await fetch(`/api/v1/insurance/medical-expenses?case_id=${id}`).then((r) =>
      r.json(),
    );
    return (
      r.medical_paid_krw === "960000" &&
      r.insurance_received_krw === "0" &&
      expenses.items.length === 5
    );
  }, caseA);
  expect(costs).toBe(true);
  console.log("SAFE_PHASE=INSURANCE_MEDICAL_CLAIMS");
  const payoutA = await createPayout(page, caseA, policyA, "600000");
  await createPayout(page, caseA, policyB, "200000", "fixed");
  await page.goto(`/insurance/payouts/${payoutA}`);
  const originalCash = await page.evaluate(
    async (id) =>
      (await fetch(`/api/v1/insurance/payouts/${id}`).then((r) => r.json())).cash.id as string,
    payoutA,
  );
  await page.goto(`/insurance/claims/${claimA}`);
  await page.getByRole("button", { name: "같은 사건의 기존 수령 찾기", exact: true }).click();
  const receipt = page
    .getByRole("region", { name: "기존 수령 연결", exact: true })
    .locator("li")
    .filter({ hasText: "이 사건 배분 600,000원" });
  await receipt.getByRole("button", { name: "이 배분을 청구에 연결 검토", exact: true }).click();
  await page.getByLabel("기존 연결과 변경할 청구를 확인했어요.", { exact: true }).check();
  await page.getByLabel("배분 연결 정정 사유", { exact: true }).fill("합성 HTTPS 나중 청구 확인");
  await page.getByRole("button", { name: "같은 입금의 청구 연결 저장", exact: true }).click();
  await expect(
    page.getByText("이 청구의 실제 수령 600,000원 · 반환 0원 · 순수령 600,000원"),
  ).toBeVisible();
  await page.goto("/insurance/claims");
  await expect(page.getByRole("region", { name: "청구 작업 결과" })).toContainText(
    "실제 수령 600,000원",
  );
  console.log("SAFE_PHASE=INSURANCE_CLAIM_WORKBENCH");
  expect(
    await page.evaluate(
      async ({ id, original }) =>
        (await fetch(`/api/v1/insurance/payouts/${id}`).then((r) => r.json())).cash.id === original,
      { id: payoutA, original: originalCash },
    ),
  ).toBe(true);
  await refund(page, expenseIds[1]!, "10000");
  await returned(page, payoutA, "50000");
  const balanced = await page.evaluate(async (id) => {
    const s = await fetch(`/api/v1/insurance/cases/${id}/summary`).then((r) => r.json());
    const i = await fetch("/api/v1/income/summary?month=2025-02").then((r) => r.json());
    return (
      s.net_medical_krw === "950000" &&
      s.net_received_krw === "750000" &&
      s.net_burden_krw === "200000" &&
      i.totals.insurance_net_krw === "750000" &&
      i.totals.earned_net_krw === "0"
    );
  }, caseA);
  expect(balanced).toBe(true);
  console.log("SAFE_PHASE=INSURANCE_REFUND_RETURN");
  await createPayout(page, caseA, policyA, "500000", "reimbursement", caseB);
  await page.goto(`/insurance/cases/${caseA}`);
  await expect(
    page.getByRole("region", { name: "사건 실제 비용과 순부담", exact: true }),
  ).toContainText("순현금부담-100,000원");
  console.log("SAFE_PHASE=INSURANCE_MULTI_CASE");
  const temporaryExpense = await createExpense(page, caseA, outpatient, "100", "HTTPS-CORRECTION");
  await page.goto(`/insurance/expenses/${temporaryExpense}/correct`);
  await page.getByLabel("의료비 지불 금액 (원)", { exact: true }).fill("101");
  await page.getByLabel("의료비 정정 사유", { exact: true }).fill("합성 HTTPS 의료비 정정");
  await page
    .getByLabel("기존 의료비는 무효로 보존하고 새 원본으로 정정하는 것을 확인했어요.", {
      exact: true,
    })
    .check();
  await page.getByRole("button", { name: "의료비 정정 저장", exact: true }).click();
  await expect(page.getByRole("link", { name: "정정 전 원본 확인", exact: true })).toBeVisible();
  const correctedExpense = lastId(page);
  await refund(page, correctedExpense, "1");
  await page.getByRole("link", { name: "의료비 환불 원본 정정", exact: true }).click();
  await page.getByLabel("의료비 환불 금액 (원)", { exact: true }).fill("2");
  await page.getByLabel("의료비 환불 정정 사유", { exact: true }).fill("합성 HTTPS 환불 정정");
  await page.getByRole("button", { name: "의료비 환불 정정 저장", exact: true }).click();
  await expect(page.getByRole("link", { name: "정정 전 원본 확인", exact: true })).toBeVisible();
  await voidCurrent(page, "의료비 환불");
  await page.goto(`/insurance/expenses/${correctedExpense}`);
  await voidCurrent(page, "의료비");
  const temporaryPayout = await createPayout(page, caseB, policyB, "100", "fixed");
  await page.goto(`/insurance/payouts/${temporaryPayout}/correct`);
  await page.getByLabel("보험금 수령 금액 (원)", { exact: true }).fill("101");
  await page.getByLabel("사건 배분금액 (원)", { exact: true }).fill("101");
  await page.getByLabel("보험금 수령 정정 사유", { exact: true }).fill("합성 HTTPS 수령 정정");
  await page
    .getByLabel("실제 입금 한 건과 같은 합계의 사건별 배분을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "보험금 수령 정정 저장", exact: true }).click();
  await expect(page.getByRole("link", { name: "정정 전 원본 확인", exact: true })).toBeVisible();
  const correctedPayout = lastId(page);
  await returned(page, correctedPayout, "1");
  await page.getByRole("link", { name: "보험금 반환 원본 정정", exact: true }).click();
  await page.getByLabel("보험금 반환 금액 (원)", { exact: true }).fill("2");
  await page.getByLabel("보험금 반환 정정 사유", { exact: true }).fill("합성 HTTPS 반환 정정");
  await page.getByRole("button", { name: "보험금 반환 정정 저장", exact: true }).click();
  await expect(page.getByRole("link", { name: "정정 전 원본 확인", exact: true })).toBeVisible();
  await voidCurrent(page, "보험금 반환");
  await page.goto(`/insurance/payouts/${correctedPayout}`);
  await voidCurrent(page, "보험금 수령");
  console.log("SAFE_PHASE=INSURANCE_CORRECTIONS");
  await page.goto(`/insurance/cases/${caseA}/edit`);
  await page.getByRole("combobox", { name: "치료 상태", exact: true }).selectOption("ended");
  await page.getByLabel("치료 종료일", { exact: true }).fill("2025-02-28");
  await page.getByLabel("사건 변경 사유", { exact: true }).fill("합성 HTTPS 치료 종료");
  await page.getByRole("button", { name: "사건 변경 저장", exact: true }).click();
  await page.getByRole("link", { name: "사건 상태·내용 변경", exact: true }).click();
  await page.getByRole("combobox", { name: "치료 상태", exact: true }).selectOption("ongoing");
  await page.getByRole("combobox", { name: "정산 상태", exact: true }).selectOption("settled");
  await page.getByLabel("사건 변경 사유", { exact: true }).fill("합성 HTTPS 재진과 정산 구분");
  await page.getByRole("button", { name: "사건 변경 저장", exact: true }).click();
  await openDisclosure(page, "사건 변경 이력 확인");
  await expect(page.getByRole("heading", { name: "사건 버전 3", exact: true })).toBeVisible();
  const invariant = await page.evaluate(
    async ({ before, a, b, policy }) => {
      const read = (path: string) => fetch(path).then((r) => r.json());
      const [month, first, second, income, currentCase, policyRow] = await Promise.all([
        read("/api/v1/asset-months/2025-02"),
        read(`/api/v1/insurance/cases/${a}/summary`),
        read(`/api/v1/insurance/cases/${b}/summary`),
        read("/api/v1/income/summary?month=2025-02"),
        read(`/api/v1/insurance/cases/${a}`),
        read(`/api/v1/insurance/policies/${policy}`),
      ]);
      return (
        month.state === "confirmed" &&
        month.version === before.version &&
        month.revision_id === before.revision &&
        JSON.stringify(
          month.values.map((v: { asset_id: string; input_amount_krw: string }) => [
            v.asset_id,
            v.input_amount_krw,
          ]),
        ) === JSON.stringify(before.values) &&
        first.net_burden_krw === "-100000" &&
        second.net_burden_krw === "-200000" &&
        income.totals.insurance_net_krw === "1250000" &&
        currentCase.treatment_state === "ongoing" &&
        currentCase.financial_state === "settled" &&
        currentCase.end_on === null &&
        policyRow.has_number &&
        !Object.hasOwn(policyRow, "policy_number")
      );
    },
    { before: snapshot, a: caseA, b: caseB, policy: policyA },
  );
  expect(invariant).toBe(true);
  expect(missingNoStore).toBe(false);
  expect(missingKey).toBe(false);
  expect(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0)).toBe(
    true,
  );
  console.log("SAFE_PHASE=INSURANCE_INVARIANTS");
});

test("real family patient survives archive without gaining a login membership", async ({
  page,
}) => {
  const read = (path: string) =>
    page.evaluate(async (url) => {
      const response = await fetch(url, { credentials: "include", cache: "no-store" });
      if (!response.ok) throw new Error(`Synthetic family read HTTP ${response.status}`);
      return response.json();
    }, path);
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
  await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
  ).toBeVisible();
  const membersBefore = await read("/api/v1/household/members");
  await page.goto("/settings/people");
  await page.getByLabel("가족 이름", { exact: true }).fill("합성 HTTPS 자녀");
  await page.getByRole("button", { name: "가족 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: /합성 HTTPS 자녀/ })).toBeVisible();
  const people = await read("/api/v1/household/people");
  const person = people.items.find(
    (p: { display_name: string }) => p.display_name === "합성 HTTPS 자녀",
  );
  expect(person.member_id).toBeNull();
  expect(await read("/api/v1/household/members")).toEqual(membersBefore);
  await page.goto("/insurance/cases/new");
  await page.getByLabel("사건 이름", { exact: true }).fill("합성 HTTPS 가족 진료");
  await page.getByRole("combobox", { name: "사건 환자", exact: true }).selectOption(person.id);
  await page.getByLabel("사건 시작일", { exact: true }).fill("2025-02-01");
  await page.getByRole("button", { name: "보험 사건 등록", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 HTTPS 가족 진료", exact: true }),
  ).toBeVisible();
  const caseId = lastId(page);
  await page.goto("/settings/people");
  await page.getByRole("button", { name: "가족 보관", exact: true }).click();
  await expect(page.getByRole("heading", { name: /합성 HTTPS 자녀.*보관됨/ })).toBeVisible();
  await page.goto(`/insurance/cases/${caseId}/edit`);
  await expect(page.getByRole("combobox", { name: "사건 환자", exact: true })).toHaveValue(
    person.id,
  );
  await page.getByLabel("사건 이름", { exact: true }).fill("합성 HTTPS 가족 기록 유지");
  await page.getByLabel("사건 변경 사유", { exact: true }).fill("합성 설명 정정");
  await page.getByRole("button", { name: "사건 변경 저장", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 HTTPS 가족 기록 유지", exact: true }),
  ).toBeVisible();
  const history = await read(`/api/v1/insurance/cases/${caseId}/history`);
  expect(history.items).toHaveLength(2);
  expect(
    history.items.every((r: { patient_member_id: string }) => r.patient_member_id === person.id),
  ).toBe(true);
  const audit = await read("/api/v1/audit-events?entity_type=household_person");
  expect(audit.items.filter((r: { entity_id: string }) => r.entity_id === person.id)).toHaveLength(
    2,
  );
});
