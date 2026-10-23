import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";
import { bytes, mockDocuments } from "./support/documents";
import { uid } from "./support/finance";
import { mockHomecare } from "./support/homecare";
import { mockInsurance } from "./support/insurance";
import { mockInsuranceEvents, claimRow } from "./support/insurance-events";
import { mockMonths, verifyAll } from "./support/months";
test.use({ trace: "off", screenshot: "off", video: "off" });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});

const dialog = (page: Page) =>
  page.getByRole("alertdialog", { name: "저장하지 않은 입력이 있어요", exact: true });
const back = (page: Page) => page.getByRole("button", { name: "뒤로", exact: true }).click();

/** Back navigation with typed input asks first and keeps the typed text when staying. */
async function expectAsksBeforeLeaving(page: Page, typed: () => ReturnType<Page["getByLabel"]>) {
  const field = typed();
  const value = await field.inputValue();
  const path = new URL(page.url()).pathname;
  await back(page);
  await expect(dialog(page)).toBeVisible();
  await page.getByRole("button", { name: "계속 입력하기", exact: true }).click();
  await expect(dialog(page)).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe(path);
  await expect(field).toHaveValue(value);
}
async function expectLeavesWithoutAsking(page: Page, from: string) {
  await back(page);
  await expect.poll(() => new URL(page.url()).pathname).not.toBe(from);
  await expect(dialog(page)).toHaveCount(0);
}

async function openReopen(page: Page) {
  const state = await mockMonths(page);
  verifyAll(state.record!);
  state.record!.state = "confirmed";
  state.record!.confirmed_at = "2025-02-28T12:00:00Z";
  state.finance.assets[0]!.household_share = "1";
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "정정 사유 남기고 다시 열기", exact: true }).click();
  await page.getByLabel("정정 사유", { exact: true }).fill("합성 평가액 확인 오류 정정");
  return state;
}

test("a typed month reopen reason asks before leaving and a save releases the guard", async ({
  page,
}) => {
  await openReopen(page);
  await expectAsksBeforeLeaving(page, () => page.getByLabel("정정 사유"));
  await page.getByRole("button", { name: "사유를 남기고 정정 시작", exact: true }).click();
  await expect(page.getByLabel("정정 사유", { exact: true })).toHaveCount(0);
  await expectLeavesWithoutAsking(page, "/assets/months/2025-02");
});

test("a typed stock cancel reason asks before leaving", async ({ page }) => {
  await mockHomecare(page);
  await page.goto(`/consumables/${uid(200)}/stock/${uid(400)}`);
  await page.getByRole("button", { name: "재고 원본 취소 검토", exact: true }).click();
  await page.getByLabel("재고 취소 사유").fill("합성 구매 취소 확인");
  await expectAsksBeforeLeaving(page, () => page.getByLabel("재고 취소 사유"));
});

test("a stock cancel that saved leaves without asking", async ({ page }) => {
  const state = await mockHomecare(page);
  state.consumables[0]!.stock_quantity = 20;
  await page.goto(`/consumables/${uid(200)}/stock/${uid(400)}`);
  await page.getByRole("button", { name: "재고 원본 취소 검토", exact: true }).click();
  await page.getByLabel("재고 취소 사유").fill("합성 구매 취소 확인");
  await page.getByLabel("원본 전체 수량을 취소하고 보정 이력을 남겨요").check();
  await page.getByRole("button", { name: "원본 취소·재고 보정" }).click();
  await expect(page.getByText("취소 보정", { exact: false }).first()).toBeVisible();
  await expect(dialog(page)).toHaveCount(0);
  await expect(page).not.toHaveURL(new RegExp(`/stock/${uid(400)}$`));
});

test("a coverage item being typed asks before leaving and a save releases the guard", async ({
  page,
}) => {
  await mockInsurance(page);
  await page.goto(`/insurance/policies/${uid(80)}`);
  await page.getByRole("button", { name: "보장 항목 추가", exact: true }).click();
  await page.getByLabel("보장 이름", { exact: true }).fill("합성 새 보장");
  await expectAsksBeforeLeaving(page, () => page.getByLabel("보장 이름"));
  await page.getByRole("button", { name: "보장 항목 저장", exact: true }).click();
  await expect(page.getByLabel("보장 이름", { exact: true })).toHaveCount(0);
  await expectLeavesWithoutAsking(page, `/insurance/policies/${uid(80)}`);
});

test("a rule end being typed asks before leaving", async ({ page }) => {
  await mockCashflow(page);
  await page.goto(`/fixed-payments/rules/${uid(60)}`);
  await page.getByRole("button", { name: "납부 규칙 종료 검토", exact: true }).click();
  await page.getByLabel("규칙 종료 사유", { exact: true }).fill("합성 해지");
  await expectAsksBeforeLeaving(page, () => page.getByLabel("규칙 종료 사유"));
});

test("an allocation link being typed asks before leaving", async ({ page }) => {
  const state = await mockInsuranceEvents(page);
  state.claims.push(claimRow(1200, [uid(1001)]));
  await page.goto(`/insurance/payouts/${uid(1100)}`);
  await page.getByRole("button", { name: "배분 1 청구 연결 정정", exact: true }).click();
  await page.getByLabel("배분 연결 정정 사유", { exact: true }).fill("합성 접수번호 나중 확인");
  await expectAsksBeforeLeaving(page, () => page.getByLabel("배분 연결 정정 사유"));
});

test("a money void reason being typed asks before leaving", async ({ page }) => {
  await mockInsuranceEvents(page);
  await page.goto(`/insurance/expenses/${uid(1001)}`);
  await page.getByRole("button", { name: "의료비 무효 검토", exact: true }).click();
  await page.getByLabel("금전 기록 무효 사유", { exact: true }).fill("합성 오등록");
  await expectAsksBeforeLeaving(page, () => page.getByLabel("금전 기록 무효 사유"));
});

test("generating occurrences releases the guard so back does not ask", async ({ page }) => {
  const state = await mockCashflow(page);
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "예정 회차 생성 열기", exact: true }).click();
  await page.getByLabel("회차 생성 종료일", { exact: true }).fill("2025-02-27");
  await page.getByRole("button", { name: "선택 기간 회차 생성", exact: true }).click();
  await expect(
    page.getByText("요청한 기간의 회차 생성을 확인했어요", { exact: false }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(1);
  await expectLeavesWithoutAsking(page, "/fixed-payments");
});

test("uploading a document on a medical node releases the guard so back does not ask", async ({
  page,
}) => {
  await mockDocuments(page);
  await page.goto(`/insurance/cases/${uid(90)}/nodes/${uid(91)}`);
  await page
    .getByRole("region", { name: "진료·약국 첨부 문서", exact: true })
    .getByRole("button", { name: "첨부 문서 열기" })
    .click();
  const form = page.getByRole("region", { name: "새 문서 첨부", exact: true });
  await form
    .getByLabel("문서 파일", { exact: true })
    .setInputFiles({ name: "합성 새 문서.png", mimeType: "image/png", buffer: bytes });
  await form.getByRole("checkbox").check();
  await form.getByRole("button", { name: "문서 업로드", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "문서 상세", exact: true })
      .getByText("보관 완료", { exact: true }),
  ).toBeVisible();
  await expectLeavesWithoutAsking(page, `/insurance/cases/${uid(90)}/nodes/${uid(91)}`);
});
