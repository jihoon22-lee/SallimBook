import { expect, test } from "@playwright/test";
import { mockFinance } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });

test("a route that throws shows the Korean error screen without a stack trace", async ({
  page,
}) => {
  await mockFinance(page);
  // A list row the screen cannot read makes its render throw.
  await page.route("**/api/v1/accounts?*", (route) =>
    route.fulfill({ json: { items: [null], next_cursor: null } }),
  );
  page.on("pageerror", () => {});
  await page.goto("/accounts");
  await expect(
    page.getByRole("heading", { name: "화면을 표시하지 못했어요.", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "다시 시도", exact: true })).toBeVisible();
  const home = page.getByRole("link", { name: "홈으로", exact: true });
  await expect(home).toHaveAttribute("href", "/");
  const text = await page.locator("body").innerText();
  expect(text).not.toMatch(/Unexpected Application Error|TypeError|at \S+ \(|\.tsx?:\d+/);
  expect(await page.title()).toContain("SallimBook");
  await home.click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "오늘의 살림", level: 1 })).toBeVisible();
});

test("the error screen retry reloads the page", async ({ page }) => {
  const state = await mockFinance(page);
  let broken = true;
  await page.route("**/api/v1/accounts?*", (route) =>
    broken ? route.fulfill({ json: { items: [null], next_cursor: null } }) : route.fallback(),
  );
  page.on("pageerror", () => {});
  await page.goto("/accounts");
  const retry = page.getByRole("button", { name: "다시 시도", exact: true });
  await expect(retry).toBeVisible();
  broken = false;
  await retry.click();
  await expect(page.getByRole("heading", { name: "계좌 관리", level: 1 })).toBeVisible();
  await expect.poll(() => state.accountQueries.length).toBeGreaterThan(0);
});
