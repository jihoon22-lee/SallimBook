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

test("keep editing leaves focus in a field the person picked before the dialog finished closing", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "지출 계획 추가", exact: true }).click();
  const editor = page.getByRole("region", { name: "지출 계획 편집", exact: true });
  const name = editor.getByLabel("이름", { exact: true });
  await name.fill("합성 이름");
  await editor.getByText("결제수단·주기·관련 구성원·메모", { exact: true }).click();
  const note = editor.getByRole("textbox", { name: "메모", exact: true });
  await note.fill("합성 메모");
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(dialog(page)).toBeVisible();
  // Hold animation frames: the deferred refocus then runs only after a field was picked, as on a
  // slow device where the person is already typing again.
  await page.evaluate(() => {
    const held: FrameRequestCallback[] = [];
    const original = window.requestAnimationFrame;
    window.requestAnimationFrame = (callback) => held.push(callback);
    Object.assign(window, {
      syntheticFlushFrames: () => {
        for (let round = 0; round < 5 && held.length; round++)
          for (const callback of held.splice(0)) callback(performance.now());
        window.requestAnimationFrame = original;
      },
    });
  });
  await page.getByRole("button", { name: "계속 입력하기", exact: true }).click();
  await expect(dialog(page)).toHaveCount(0);
  await note.focus();
  await page.evaluate(() =>
    (window as unknown as { syntheticFlushFrames: () => void }).syntheticFlushFrames(),
  );
  await expect(note).toBeFocused();
  await page.keyboard.type(" 추가");
  await expect(note).toHaveValue("합성 메모 추가");
  await expect(name).toHaveValue("합성 이름");
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
