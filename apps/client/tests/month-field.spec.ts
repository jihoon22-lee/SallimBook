import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockComparison } from "./support/comparison";
import { mockMonths } from "./support/months";
test.use({ trace: "off", screenshot: "off", video: "off" });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});

/** Browsers without a month picker (desktop Firefox and Safari) show a plain text box. */
async function showMonthInputsAsText(page: Page) {
  await page.addInitScript(() => {
    const original = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "type")!;
    Object.defineProperty(HTMLInputElement.prototype, "type", {
      configurable: true,
      enumerable: original.enumerable,
      get() {
        return original.get!.call(this);
      },
      set(value: string) {
        original.set!.call(this, value === "month" ? "text" : value);
      },
    });
  });
}
const historyLength = (page: Page) => page.evaluate(() => window.history.length);
/** Every address the app writes to the history, with the method that wrote it. */
async function recordHistoryWrites(page: Page) {
  await page.addInitScript(() => {
    const writes: string[] = [];
    (window as unknown as { historyWrites: string[] }).historyWrites = writes;
    for (const method of ["pushState", "replaceState"] as const) {
      const original = history[method].bind(history);
      history[method] = (data: unknown, unused: string, url?: string | URL | null) => {
        writes.push(`${method} ${url ?? ""}`);
        original(data, unused, url);
      };
    }
  });
  return () =>
    page.evaluate(() => (window as unknown as { historyWrites: string[] }).historyWrites);
}

test("month field accepts typed digits when the browser shows a text box", async ({ page }) => {
  await showMonthInputsAsText(page);
  const writes = await recordHistoryWrites(page);
  await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  const field = page.getByLabel("확인할 월", { exact: true });
  await expect(field).toHaveValue("2025-02");
  expect(await field.evaluate((input: HTMLInputElement) => input.type)).toBe("text");
  const entries = await historyLength(page);
  const before = (await writes()).length;
  await field.fill("");
  await field.pressSequentially("2025-03");
  await expect(page).toHaveURL(/\/assets\/months\/2025-03$/);
  await expect(field).toHaveValue("2025-03");
  await expect(page.getByText("서울 기준 · 2025년 3월", { exact: true })).toBeVisible();
  expect(await historyLength(page)).toBe(entries);
  // Only the finished month reaches the address, once, replacing the current entry.
  expect((await writes()).slice(before)).toEqual(["replaceState /assets/months/2025-03"]);
});

test("a half-typed month is restored when the field loses focus", async ({ page }) => {
  await showMonthInputsAsText(page);
  await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  const field = page.getByLabel("확인할 월", { exact: true });
  await field.fill("");
  await field.pressSequentially("2025-1");
  await expect(page).toHaveURL(/\/assets\/months\/2025-02$/);
  await field.blur();
  await expect(field).toHaveValue("2025-02");
  await field.fill("");
  await field.pressSequentially("2025-13");
  await field.blur();
  await expect(field).toHaveValue("2025-02");
  await expect(page).toHaveURL(/\/assets\/months\/2025-02$/);
});

test("month buttons move one month and the shortcut returns to this month", async ({ page }) => {
  await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  const field = page.getByLabel("확인할 월", { exact: true });
  const previous = page.getByRole("button", { name: "이전 달", exact: true });
  const next = page.getByRole("button", { name: "다음 달", exact: true });
  const today = page.getByRole("button", { name: "이번 달", exact: true });
  const entries = await historyLength(page);
  // This month is already shown, so the shortcut has nothing to do yet.
  await expect(today).toHaveCount(0);
  await previous.click();
  await expect(page).toHaveURL(/\/assets\/months\/2025-01$/);
  await expect(field).toHaveValue("2025-01");
  await expect(today).toBeVisible();
  await next.click();
  await expect(field).toHaveValue("2025-02");
  await next.click();
  await expect(field).toHaveValue("2025-03");
  await next.click();
  await expect(page).toHaveURL(/\/assets\/months\/2025-04$/);
  await expect(field).toHaveValue("2025-04");
  await today.click();
  await expect(page).toHaveURL(/\/assets\/months\/2025-02$/);
  await expect(field).toHaveValue("2025-02");
  await expect(today).toHaveCount(0);
  await expect(previous).toBeFocused();
  expect(await historyLength(page)).toBe(entries);
});

test("month buttons keep the focused button when the first month is reached", async ({ page }) => {
  await mockMonths(page);
  await page.goto("/assets/months/0001-02");
  const previous = page.getByRole("button", { name: "이전 달", exact: true });
  await previous.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/assets\/months\/0001-01$/);
  await expect(previous).toBeFocused();
  await expect(previous).toBeDisabled();
});

test("the shared home month selector has the same buttons", async ({ page }) => {
  await mockMonths(page);
  await page.goto("/");
  const field = page.getByLabel("확인할 월", { exact: true });
  await expect(field).toHaveValue("2025-02");
  await page.getByRole("button", { name: "이전 달", exact: true }).click();
  await expect(field).toHaveValue("2025-01");
  await expect(page.getByText("서울 기준 · 2025년 1월", { exact: true })).toBeAttached();
  await page.getByRole("button", { name: "이번 달", exact: true }).click();
  await expect(field).toHaveValue("2025-02");
});

test("comparison month filters step and type without stacking history entries", async ({
  page,
}) => {
  await showMonthInputsAsText(page);
  await mockComparison(page);
  await page.goto("/assets/compare?to=2025-02&from=2025-01");
  const to = page.getByLabel("확인할 월", { exact: true });
  const from = page.getByLabel("비교할 이전 월", { exact: true });
  const entries = await historyLength(page);
  await to.fill("");
  await to.pressSequentially("2025-04");
  await expect(page).toHaveURL(/to=2025-04/);
  await expect(to).toHaveValue("2025-04");
  await expect(from).toHaveAttribute("max", "2025-03");
  await from.fill("");
  await from.pressSequentially("2025-03");
  await expect(page).toHaveURL(/from=2025-03/);
  await expect(from).toHaveValue("2025-03");
  // "from" can never reach the month being compared.
  const filters = page.getByRole("region", { name: "비교할 월과 대상", exact: true });
  const next = filters.getByRole("button", { name: "다음 달", exact: true }).nth(1);
  await expect(next).toBeDisabled();
  await next.click({ force: true });
  await expect(from).toHaveValue("2025-03");
  await expect(page).toHaveURL(/from=2025-03/);
  expect(await historyLength(page)).toBe(entries);
});
