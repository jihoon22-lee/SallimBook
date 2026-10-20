import { expect, test } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";

test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});

test("back restores loaded income pages and scroll position", async ({ page }) => {
  const state = await mockCashflow(page);
  state.pageSize = 1;
  await page.setViewportSize({ width: page.viewportSize()!.width, height: 480 });
  await page.route("**/api/v1/income?*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 200));
    await route.fallback();
  });
  await page.goto("/income");
  await page.getByRole("button", { name: "수입 더 보기", exact: true }).click();
  const second = page.getByRole("link", { name: "상여 · 200,000원", exact: true });
  await expect(second).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const before = await page.evaluate(() => Math.round(window.scrollY));
  expect(before).toBeGreaterThan(0);
  await second.click();
  await expect(page.getByRole("heading", { name: "수입 상세", exact: true })).toBeVisible();
  await page.goBack();
  await expect(second).toBeVisible();
  await expect
    .poll(async () => Math.abs((await page.evaluate(() => Math.round(window.scrollY))) - before))
    .toBeLessThanOrEqual(2);
});

test("a pushed screen still starts at the top", async ({ page }) => {
  await mockCashflow(page);
  await page.setViewportSize({ width: page.viewportSize()!.width, height: 480 });
  await page.goto("/income");
  await page.evaluate(() => window.scrollTo(0, 200));
  await page.getByRole("link", { name: "수입 입력", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("수입 입력");
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});
