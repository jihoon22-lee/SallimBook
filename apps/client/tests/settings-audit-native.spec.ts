import { expect, test } from "@playwright/test";
import { mockAudit } from "./support/audit";
test.use({ trace: "off", screenshot: "off", video: "off" });
test("native audit uses typed metadata pagination without web HTTP or secret UI", async ({ page }) => {
  const state = await mockAudit(page, true); await page.goto("/settings/audit"); const list = page.getByRole("region", { name: "감사 기록 목록", exact: true }); await expect(list.getByRole("listitem")).toHaveCount(2);
  await page.getByRole("button", { name: "감사 기록 더 보기", exact: true }).click(); await expect(list.getByRole("listitem")).toHaveCount(3);
  const reads = state.calls.filter((call) => call.method === "listAuditEvents").map((call) => call.args); expect(reads.filter((call) => call.query.cursor)).toEqual([{ query: { limit: 50, cursor: "synthetic-next-2" } }]); expect(reads.filter((call) => !call.query.cursor).every((call) => JSON.stringify(call) === JSON.stringify({ query: { limit: 50 } }))).toBe(true); expect(state.http).toEqual([]); await expect(page.locator('input[type="password"], input[type="file"]')).toHaveCount(0);
});
for (const failure of ["APP_LOCKED", "SESSION_EXPIRED", "NETWORK_UNAVAILABLE", "ACCESS_DENIED"]) test(`native audit ${failure} never falls back to web`, async ({ page }) => {
  const state = await mockAudit(page, true); state.nativeFailure = failure; await page.goto("/settings/audit");
  if (failure === "APP_LOCKED") await expect(page.getByText("앱이 잠겨 있어요. Android 보호 화면에서 다시 열어 주세요.", { exact: true })).toBeVisible();
  else if (failure === "SESSION_EXPIRED") await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible();
  else await expect(page.getByRole("alert")).toBeVisible();
  if (["APP_LOCKED", "SESSION_EXPIRED"].includes(failure)) await expect(page.getByRole("region", { name: "감사 기록 목록", exact: true })).toHaveCount(0);
  await expect.poll(() => state.calls.some((call) => call.method === "listAuditEvents")).toBe(true); expect(state.http).toEqual([]);
});
test("settings native lock uses existing protected action and reports failure", async ({ page }) => {
  const state = await mockAudit(page, true); state.lockFailure = "NETWORK_UNAVAILABLE"; await page.goto("/settings"); await page.getByRole("button", { name: "이 Android 앱 잠그기", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("서버 연결"); expect(state.calls.filter((call) => call.method === "lockApp")).toHaveLength(1); expect(state.http).toEqual([]);
});

test("unsupported native audit explains the missing connection without web fallback", async ({ page }) => {
  const state = await mockAudit(page, true); state.nativeThrows = true; await page.goto("/settings/audit"); await expect(page.getByRole("alert")).toContainText("감사 이력 보호 연결"); expect(state.http).toEqual([]); await expect(page.getByRole("region", { name: "감사 기록 목록", exact: true }).getByRole("listitem")).toHaveCount(0);
});
