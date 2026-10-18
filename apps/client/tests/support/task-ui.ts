import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";

/** Follow the visible disclosure control; never force hidden fields open in the DOM. */
export async function openDisclosure(page: Page, title: string) {
  const summary = page.locator("summary").filter({ hasText: title });
  await expect(summary).toHaveCount(1);
  if (!await summary.locator("..").evaluate((element) => (element as HTMLDetailsElement).open)) {
    await summary.click();
  }
}
