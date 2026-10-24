import { expect, test } from "@playwright/test";
import { mockFinance, uid } from "./support/finance";
import { mockInsurance } from "./support/insurance";
import { mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { installAndroidBack } from "./support/android-back";
import { openDisclosure } from "./support/task-ui";

test.use({ trace: "off", screenshot: "off", video: "off" });

test("new account keeps optional fields folded and edit shows stored optional values", async ({
  page,
}) => {
  await mockFinance(page);
  await page.goto("/accounts/new");
  await expect(page.getByLabel("용도 (선택)", { exact: true })).toBeHidden();
  await expect(page.getByLabel("보유 종료일 (선택)", { exact: true })).toBeHidden();
  await expect(page.getByLabel("보유 시작일", { exact: true })).toBeVisible();
  await openDisclosure(page, "계좌 용도·개설일");
  await page.getByLabel("용도 (선택)", { exact: true }).fill("합성 선택 정보");
  await page.locator("summary").filter({ hasText: "계좌 용도·개설일" }).click();
  await openDisclosure(page, "계좌 용도·개설일");
  await expect(page.getByLabel("용도 (선택)", { exact: true })).toHaveValue("합성 선택 정보");
  await page.goto(`/accounts/${uid(30)}/edit`);
  await expect(page.getByLabel("용도 (선택)", { exact: true })).toBeVisible();
  await expect(page.getByLabel("용도 (선택)", { exact: true })).toHaveValue("합성 은퇴 준비");
});

test("a folded invalid date reopens, shows its bound and prevents a policy write", async ({
  page,
}) => {
  const state = await mockInsurance(page);
  await page.goto("/insurance/policies/new");
  await page.getByLabel("보험사", { exact: true }).fill("합성 보험사");
  await page.getByLabel("보험 상품명", { exact: true }).fill("합성 기간 확인");
  await page.getByLabel("보장 시작일", { exact: true }).fill("2025-02-01");
  await expect(page.getByLabel("계약 종료일", { exact: true })).toBeHidden();
  await openDisclosure(page, "계약 기간·수익자·평가액·메모");
  await page.getByLabel("보장 종료일", { exact: true }).fill("2025-01-01");
  const optional = page.locator("details.optional-fields");
  await optional.locator("summary").click();
  await page.getByRole("button", { name: "보험 계약 등록", exact: true }).click();
  await expect(optional).toHaveAttribute("open", "");
  await expect(optional.getByRole("alert")).toContainText("2025-02-01");
  await expect(optional.locator('input[aria-invalid="true"]')).toBeFocused();
  expect(state.writes).toHaveLength(0);
  await optional.locator('input[aria-invalid="true"]').fill("2025-03-01");
  await page.getByRole("button", { name: "보험 계약 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 기간 확인", exact: true })).toBeVisible();
  expect(state.writes[0]!.body.coverage_end).toBe("2025-03-01");
});

for (const width of [320, 390, 1280]) {
  test(`filter panel at ${width}px keeps keyboard focus, URL conditions and usable touch sizes`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 820 });
    await page.emulateMedia({ colorScheme: "dark" });
    const state = await mockCashflow(page);
    await page.goto("/income");
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    const trigger = page.locator(".filter-panel > summary");
    await trigger.focus();
    await page.keyboard.press("Enter");
    const panel = page.getByRole("dialog", { name: "수입 기록 찾기", exact: true });
    await expect(panel).toBeVisible();
    await panel
      .getByRole("combobox", { name: "수입 구성원 필터", exact: true })
      .selectOption(uid(2));
    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(trigger).toBeFocused();
    await expect(trigger).toContainText("조건 1개 적용");
    await trigger.click();
    await expect(
      panel.getByRole("combobox", { name: "수입 구성원 필터", exact: true }),
    ).toHaveValue(uid(2));
    const button = panel.getByRole("button", { name: "필터 닫기", exact: true });
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(48);
    expect(await panel.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    await button.click();
    expect(state.writes).toHaveLength(0);
  });
}

test("Android back closes a filter before leaving the page", async ({ page }) => {
  const state = await mockCashflow(page);
  await mockNativeCashflow(page, state);
  const back = await installAndroidBack(page);
  await page.goto("/income");
  await openDisclosure(page, "수입 기록 찾기");
  await expect(page.getByRole("dialog", { name: "수입 기록 찾기" })).toBeVisible();
  await back.press();
  await expect(page.getByRole("dialog", { name: "수입 기록 찾기" })).toBeHidden();
  await expect(page).toHaveURL(/\/income$/);
  await expect(page.locator(".filter-panel > summary")).toBeFocused();
});

test("closing an account returns focus to its trigger without losing the detail", async ({
  page,
}) => {
  await mockFinance(page);
  await page.goto(`/accounts/${uid(30)}`);
  const trigger = page.getByRole("button", { name: "계좌 사용 종료하기", exact: true });
  await trigger.click();
  await expect(page.getByRole("region", { name: "계좌 사용 종료", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "계좌 종료 취소", exact: true }).click();
  await expect(trigger).toBeFocused();
});

test("a policy can be saved with only its required fields", async ({ page }) => {
  const state = await mockInsurance(page);
  await page.goto("/insurance/policies/new");
  await page.getByLabel("보험사", { exact: true }).fill("합성 최소 보험사");
  await page.getByLabel("보험 상품명", { exact: true }).fill("합성 필수 입력 계약");
  await page.getByLabel("보장 시작일", { exact: true }).fill("2025-02-01");
  await page.getByRole("button", { name: "보험 계약 등록", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 필수 입력 계약", exact: true }),
  ).toBeVisible();
  expect(state.writes[0]!.body).toMatchObject({
    coverage_start: "2025-02-01",
    contract_start: null,
    contract_end: null,
    beneficiary_note: null,
    note: null,
  });
});

for (const kind of ["asset", "account"] as const) {
  test(`${kind} reload after conflict keeps the detail and entered closing date visible`, async ({
    page,
  }) => {
    const state = await mockFinance(page);
    state.archiveConflictOnce = true;
    const path = `/${kind === "asset" ? "assets" : "accounts"}/${uid(kind === "asset" ? 10 : 30)}`;
    await page.goto(path);
    await page
      .getByRole("button", {
        name: kind === "asset" ? "사용 종료하기" : "계좌 사용 종료하기",
        exact: true,
      })
      .click();
    const date = page.getByLabel(kind === "asset" ? "종료일" : "계좌 종료일", { exact: true });
    await date.fill("2026-09-20");
    await page
      .getByRole("button", {
        name: kind === "asset" ? "사용 종료 확인" : "계좌 사용 종료 확인",
        exact: true,
      })
      .click();
    await expect(page.getByRole("alert")).toBeVisible();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(`**/api/v1${path}`, async (route) => {
      await gate;
      await route.fallback();
    });
    try {
      await page
        .getByRole("button", {
          name: kind === "asset" ? "최신 자산 정보 다시 확인" : "종료 전 최신 계좌 정보 확인",
          exact: true,
        })
        .click();
      await expect(page.getByText("기존 내용을 유지하며", { exact: false })).toBeVisible();
      await expect(date).toBeVisible();
      await expect(date).toHaveValue("2026-09-20");
    } finally {
      release();
    }
    await expect(page.getByText("기존 내용을 유지하며", { exact: false })).toHaveCount(0);
    await expect(date).toHaveValue("2026-09-20");
  });
}
