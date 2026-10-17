import { expect, test } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => { await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z")); });
test("account closure reviews direct payment plans and linked cards before archiving its one asset", async ({ page }) => {
  const state = await mockCashflow(page); state.linksRequired = true; await page.goto(`/accounts/${uid(30)}`); await page.getByRole("button", { name: "계좌 사용 종료하기", exact: true }).click(); const review = page.getByRole("region", { name: "사용 종료 영향 확인", exact: true }); await expect(review).toContainText("연결 카드 1개"); await review.getByText("연결 규칙 모두 보기", { exact: true }).click(); await expect(review).toContainText("계좌 직접 납부 계획"); await expect(page.getByRole("button", { name: "계좌 사용 종료 확인", exact: true })).toBeDisabled(); await review.getByRole("checkbox").check(); await page.getByRole("button", { name: "계좌 사용 종료 확인", exact: true }).click(); await expect(page.getByRole("button", { name: "계좌 사용 종료하기", exact: true })).toHaveCount(0);
  expect(state.writes).toHaveLength(1); expect(state.writes[0]!.path).toBe(`/api/v1/assets/${uid(11)}/archive`); expect(state.writes[0]!.body).toEqual({ ended_on: "2025-02-20", closure_ack: true, usage_digest: "1".padStart(64, "0") }); expect(state.finance.accounts[0]!.status).toBe("closed");
});
for (const editing of [false, true]) test(`linked asset ${editing ? "edit" : "archive"} uses account payment-link confirmation`, async ({ page }) => {
  const state = await mockCashflow(page); state.linksRequired = true; await page.goto(`/assets/${uid(11)}${editing ? "/edit" : ""}`);
  if (editing) await page.getByLabel("보유 종료일 (선택)", { exact: true }).fill("2025-02-20"); else { await page.getByRole("button", { name: "사용 종료하기", exact: true }).click(); await page.getByLabel("종료일", { exact: true }).fill("2025-02-20"); }
  const review = page.getByRole("region", { name: "사용 종료 영향 확인", exact: true }); await review.getByRole("checkbox").check(); await page.getByRole("button", { name: editing ? "자산 수정 저장" : "사용 종료 확인", exact: true }).click(); await expect(page.getByRole("heading", { name: "자산 상세", exact: true })).toBeVisible();
  await expect.poll(() => state.finance.accounts[0]!.status).toBe("closed"); expect(state.linksQueries.at(-1)?.get("as_of_date")).toBe("2025-02-20"); expect(state.writes.at(-1)!.body).toMatchObject({ ended_on: "2025-02-20", closure_ack: true, usage_digest: "1".padStart(64, "0") });
});
