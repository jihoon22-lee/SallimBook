import { expect, test } from "@playwright/test";
import { mockInsurance, policyRow } from "./support/insurance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
test("paged lists keep the server's business order instead of id order", async ({ page }) => {
  const state = await mockInsurance(page);
  state.pageSize = 1;
  state.policies = [
    { ...policyRow(86), product_name: "합성 최근 계약" },
    policyRow(80),
    { ...policyRow(84), product_name: "합성 오래된 계약" },
  ];
  await page.goto("/insurance/policies");
  const more = page.getByRole("button", { name: "보험 계약 더 보기" });
  await more.click();
  await more.click();
  await expect(more).toHaveCount(0);
  await expect(page.getByRole("listitem").getByRole("heading", { level: 2 })).toHaveText([
    "합성 최근 계약",
    "합성 실손 계약",
    "합성 오래된 계약",
  ]);
});
