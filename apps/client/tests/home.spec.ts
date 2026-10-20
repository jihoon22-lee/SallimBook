import { expect, test } from "@playwright/test";

test("home preserves asset and consumable priority without inventing zero balances", async ({
  page,
}) => {
  const errors: string[] = [];
  await page.route("**/api/v1/household/setup", (route) =>
    route.fulfill({ json: { available: false } }),
  );
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "UNAUTHENTICATED",
          message: "로그인이 필요합니다.",
          request_id: "synthetic",
        },
      }),
    }),
  );
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page).toHaveTitle("SallimBook · 살림북");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("오늘의 살림");
  await expect(page.locator(".dashboard-grid").getByRole("heading", { level: 2 })).toHaveText([
    "자산의 변화",
    "살펴볼 소모품",
  ]);
  await expect(page.getByText("오늘 기준", { exact: true })).toBeVisible();
  await expect(page.getByText("0원", { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test("signed-out home starts with the page h1", async ({ page }) => {
  await page.route("**/api/v1/household/setup", (route) =>
    route.fulfill({ json: { available: false } }),
  );
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 401,
      json: {
        error: {
          code: "UNAUTHENTICATED",
          message: "로그인이 필요합니다.",
          request_id: "synthetic",
        },
      },
    }),
  );
  await page.goto("/");
  const levels = await page
    .getByRole("main")
    .locator("h1, h2, h3")
    .evaluateAll((els) => els.map((el) => el.tagName));
  expect(levels[0]).toBe("H1");
  await expect(page.getByRole("region", { name: "다른 기록 살펴보기" })).toBeVisible();
});
