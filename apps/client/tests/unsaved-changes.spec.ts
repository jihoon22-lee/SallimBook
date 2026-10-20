import { expect, test } from "@playwright/test";
import type { Page, TestInfo } from "@playwright/test";
import { installAndroidBack } from "./support/android-back";
import { mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { uid } from "./support/finance";

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});

const dialog = (page: Page) =>
  page.getByRole("alertdialog", { name: "저장하지 않은 입력이 있어요", exact: true });
const amount = (page: Page) => page.getByLabel("수입 금액 (원)", { exact: true });
const nav = (page: Page, testInfo: TestInfo) =>
  page.getByRole("navigation", {
    name: testInfo.project.name === "android-size" ? "주 메뉴" : "전체 메뉴",
    exact: true,
  });

test("dirty income form asks before a tab leaves and keeps the typed amount", async ({
  page,
}, testInfo) => {
  const state = await mockCashflow(page);
  await page.goto("/income/new");
  await amount(page).fill("3500000");
  await nav(page, testInfo).getByRole("link", { name: "자산", exact: true }).click();
  await expect(dialog(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "계속 입력하기", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "계속 입력하기", exact: true }).click();
  await expect(dialog(page)).toHaveCount(0);
  await expect(page).toHaveURL(/\/income\/new$/);
  await expect(amount(page)).toHaveValue("3500000");
  expect(state.writes).toHaveLength(0);
});

test("leaving through cancel asks, writes nothing and back skips the form", async ({ page }) => {
  const state = await mockCashflow(page);
  await page.goto("/income");
  await page.getByRole("link", { name: "수입 입력", exact: true }).click();
  await amount(page).fill("3500000");
  await page.getByRole("link", { name: "입력 취소", exact: true }).click();
  await page.getByRole("button", { name: "입력 버리고 나가기", exact: true }).click();
  await expect(page).toHaveURL(/\/income$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/income$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("월간 수입");
  expect(state.writes).toHaveLength(0);
});

test("saving income leaves without a prompt and back returns to the list", async ({ page }) => {
  const state = await mockCashflow(page);
  await page.goto("/income");
  await page.getByRole("link", { name: "수입 입력", exact: true }).click();
  await page.getByRole("combobox", { name: "수입 구성원", exact: true }).selectOption(uid(2));
  await amount(page).fill("3000");
  await page.getByRole("button", { name: "수입 기록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
  await expect(dialog(page)).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(/\/income$/);
  expect(state.writes).toHaveLength(1);
});

test("browser back on a dirty form asks first", async ({ page }) => {
  await mockCashflow(page);
  await page.goto("/income");
  await page.getByRole("link", { name: "수입 입력", exact: true }).click();
  await amount(page).fill("3500000");
  await page.goBack();
  await expect(dialog(page)).toBeVisible();
  await page.getByRole("button", { name: "계속 입력하기", exact: true }).click();
  await expect(page).toHaveURL(/\/income\/new$/);
  await expect(amount(page)).toHaveValue("3500000");
});

test("Android back on a dirty native form asks and a second back keeps editing", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await mockNativeCashflow(page, state);
  const back = await installAndroidBack(page);
  await page.goto("/income");
  await page.getByRole("link", { name: "수입 입력", exact: true }).click();
  await amount(page).fill("3500000");
  await back.press();
  await expect(dialog(page)).toBeVisible();
  await back.press();
  await expect(dialog(page)).toHaveCount(0);
  await expect(page).toHaveURL(/\/income\/new$/);
  await expect(amount(page)).toHaveValue("3500000");
});

test("closing a dirty form triggers the browser leave prompt", async ({ page }) => {
  await mockCashflow(page);
  await page.goto("/income/new");
  await amount(page).click();
  await amount(page).pressSequentially("1000");
  const prompt = new Promise<string>((resolve) =>
    page.once("dialog", (shown) => {
      resolve(shown.type());
      void shown.dismiss();
    }),
  );
  await page.close({ runBeforeUnload: true });
  expect(await prompt).toBe("beforeunload");
});
