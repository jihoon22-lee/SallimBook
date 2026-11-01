import { expect, test } from "@playwright/test";
import { mockFinance, uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });

test("a route that throws shows the Korean error screen without a stack trace", async ({
  page,
}) => {
  await mockFinance(page);
  // Keep a valid list key; an invalid nested asset makes the screen render throw.
  await page.route("**/api/v1/accounts?*", (route) =>
    route.fulfill({ json: { items: [{ id: uid(999), asset: null }], next_cursor: null } }),
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
    broken
      ? route.fulfill({ json: { items: [{ id: uid(999), asset: null }], next_cursor: null } })
      : route.fallback(),
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

test("a screen file missing after an update reloads once into the current build", async ({
  page,
}) => {
  await mockFinance(page);
  // The asset list is fetched on its first visit; the first fetch finds the old file gone.
  let missing = 1;
  await page.route("**/src/features/assets/AssetPages.tsx*", (route) =>
    missing-- > 0 ? route.fulfill({ status: 404, body: "" }) : route.fallback(),
  );
  let loads = 0;
  page.on("load", () => loads++);
  await page.goto("/");
  await page.getByRole("link", { name: "자산 전체 보기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "자산과 부채", level: 1 })).toBeVisible();
  expect(loads).toBe(2);
  await expect(page).toHaveURL(/\/assets$/);
});

test("a file still missing after that reload shows the error screen instead of looping", async ({
  page,
}) => {
  await mockFinance(page);
  page.on("pageerror", () => {});
  await page.route("**/src/features/assets/AssetPages.tsx*", (route) =>
    route.fulfill({ status: 404, body: "" }),
  );
  let loads = 0;
  page.on("load", () => loads++);
  await page.goto("/");
  await page.getByRole("link", { name: "자산 전체 보기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "화면을 표시하지 못했어요.", exact: true }),
  ).toBeVisible();
  expect(loads).toBe(2);
});

test("an offline screen fetch shows the error screen without reloading", async ({
  page,
  context,
}) => {
  await mockFinance(page);
  page.on("pageerror", () => {});
  let loads = 0;
  page.on("load", () => loads++);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "자산 전체 보기", exact: true })).toBeVisible();
  await context.setOffline(true);
  await page.getByRole("link", { name: "자산 전체 보기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "화면을 표시하지 못했어요.", exact: true }),
  ).toBeVisible();
  expect(loads).toBe(1);
});
