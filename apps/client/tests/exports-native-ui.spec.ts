import { expect, test } from "@playwright/test";
import { mockExports } from "./support/exports";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
const ack = "민감한 업무 기록이 포함될 수 있고 저장한 파일을 앱에서 회수할 수 없음을 확인했어요";
test("native export uses only selected formats and document IDs and receives status only", async ({ page }) => {
  const state = await mockExports(page, true); await page.goto("/exports"); await page.getByRole("button", { name: "문서 원본 선택 열기", exact: true }).click(); await page.getByLabel("합성 영수증.png", { exact: true }).check(); await page.getByLabel("CSV — 표로 살펴보기", { exact: true }).uncheck(); await page.getByLabel(ack).check(); await page.getByRole("button", { name: "Android에서 ZIP 내보내기", exact: true }).click(); await expect(page.getByText(/Android 보호 화면에서 내보내기를 마쳤어요/)).toBeVisible();
  expect(state.calls.filter((row) => row.method === "exportArchiveUI").map((row) => row.args)).toEqual([{ input: { formats: ["json"], document_ids: [uid(8000)] } }]); expect(state.http).toEqual([]); expect(state.writes).toEqual([]);
  await expect(page.getByRole("button", { name: "패스키로 확인하고 ZIP 내보내기", exact: true })).toHaveCount(0); await expect(page.locator('input[type="password"], input[type="file"]')).toHaveCount(0);
  expect(await page.evaluate(() => ({ urls: (window as any).__exportURLs.created, local: localStorage.length, session: sessionStorage.length }))).toEqual({ urls: 0, local: 0, session: 0 });
});
for (const failure of ["cancelled", "AUTH_CANCELLED", "APP_LOCKED", "SESSION_EXPIRED", "NETWORK_UNAVAILABLE", "REAUTHENTICATION_REQUIRED"]) test(`native export ${failure} stays in protected flow without web retry`, async ({ page }) => {
  const state = await mockExports(page, true); if (failure === "cancelled") state.nativeStatus = failure; else state.nativeFailure = failure;
  await page.goto("/exports"); await page.getByLabel(ack).check(); await page.getByRole("button", { name: "Android에서 ZIP 내보내기", exact: true }).click();
  if (failure === "cancelled") await expect(page.getByText("내보내기를 취소했어요.", { exact: true })).toBeVisible();
  else if (["APP_LOCKED", "SESSION_EXPIRED"].includes(failure)) await expect(page.getByLabel(ack)).toHaveCount(0);
  else await expect(page.getByRole("alert")).toBeVisible();
  expect(state.calls.filter((row) => row.method === "exportArchiveUI")).toHaveLength(1); expect(state.http).toEqual([]); expect(state.writes).toEqual([]);
});
test("native late completion after pagehide does not produce web bytes or success", async ({ page }) => {
  const state = await mockExports(page, true); state.delay = 600; await page.goto("/exports"); await page.getByLabel(ack).check(); await page.getByRole("button", { name: "Android에서 ZIP 내보내기", exact: true }).click(); await expect.poll(() => state.calls.filter((row) => row.method === "exportArchiveUI").length).toBe(1); await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide"))); await expect(page.getByRole("alert")).toBeVisible(); await page.waitForTimeout(700); await expect(page.getByText(/Android 보호 화면에서 내보내기를 마쳤어요/)).toHaveCount(0); expect(state.http).toEqual([]);
});
