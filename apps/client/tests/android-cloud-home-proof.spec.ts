import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { homeComparison, mockHomecare } from "./support/homecare";
import { mockNativeOnboarding } from "./support/onboarding";

const predicate = readFileSync(new URL("../android/app/src/androidTest/assets/sallimbook_cloud_authenticated_home.js", import.meta.url), "utf8");
test.use({ trace: "off", screenshot: "off", video: "off" });

for (const mode of ["signed-out", "loading", "error", "ready"] as const) {
  test(`cloud onboarding proof rejects headings without authenticated API data: ${mode}`, async ({ page }) => {
    const state = await mockHomecare(page);
    state.appliances.length = 0;
    state.links.length = 0;
    state.consumables.length = 0;
    if (mode === "signed-out") {
      await page.route("**/api/v1/me", (route) => route.fulfill({ status: 401, json: {
        error: { code: "UNAUTHENTICATED", message: "로그인이 필요합니다.", request_id: "synthetic" },
      } }));
    }
    let release: () => void = () => {};
    const pending = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/api/v1/asset-comparison?*", async (route) => {
      if (mode === "loading") await pending;
      if (mode === "error") return route.fulfill({ status: 503, json: {
        error: { code: "REQUEST_FAILED", message: "합성 조회 실패", request_id: "synthetic" },
      } });
      const month = new URL(route.request().url()).searchParams.get("to")!;
      const base = homeComparison(month);
      return route.fulfill({ json: { ...base, state: "current_missing", from_month: null,
        current: { ...base.current, state: "missing", revision: null, totals: null }, previous: null,
        item_count: 0, items: [], next_cursor: null,
      } });
    });
    try {
      await page.goto("/");
      await expect(page.locator("#assets-title")).toBeVisible();
      await expect(page.locator("#consumables-title")).toBeVisible();
      // The previous native assertion would falsely pass all four states.
      expect(await page.evaluate(() => location.pathname === "/" &&
        document.body.innerText.includes("자산") && document.body.innerText.includes("소모품"))).toBe(true);
      if (mode === "ready") {
        await expect.poll(() => page.evaluate(predicate)).toBe(true);
      } else {
        if (mode === "error") await expect(page.getByRole("alert").first()).toBeVisible();
        if (mode === "signed-out") await expect(page.getByText("로그인하면 우리 가계의 공용 재고와 기기별 교체 상태를 확인할 수 있어요.")).toBeVisible();
        expect(await page.evaluate(predicate)).toBe(false);
      }
    } finally {
      release();
    }
  });
}

// Native cold start is locked, unlike the ordinary signed-out browser shell.
// This verifies the initial proof premise; it does not simulate Android focus.
test("cloud initial native lock has no finance headings and cannot satisfy the home proof", async ({ page }) => {
  const state = await mockNativeOnboarding(page);
  state.locked = true;
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("앱이 잠겨 있어요");
  await expect(page.locator("#assets-title, #consumables-title")).toHaveCount(0);
  expect(await page.evaluate(predicate)).toBe(false);
  expect(state.http).toHaveLength(0);
  expect(state.calls.every((call) => call.method === "getSession")).toBe(true);
});
