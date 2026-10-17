import { expect, test } from "@playwright/test";

test("home preserves asset and consumable priority without inventing zero balances", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page).toHaveTitle("SallimBook · 살림북");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "함께 살피는 오늘의 살림",
  );
  await expect(page.getByRole("heading", { level: 2 })).toHaveText([
    "자산의 변화",
    "살펴볼 소모품",
  ]);
  await expect(page.getByText("오늘 기준", { exact: true })).toBeVisible();
  await expect(page.getByText("0원", { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
