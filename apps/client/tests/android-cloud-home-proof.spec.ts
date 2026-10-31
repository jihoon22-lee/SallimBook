import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { homeComparison, mockHomecare } from "./support/homecare";
import { mockNativeOnboarding } from "./support/onboarding";

const predicate = readFileSync(
  new URL(
    "../android/app/src/androidTest/assets/sallimbook_cloud_authenticated_home.js",
    import.meta.url,
  ),
  "utf8",
);
const homeState = readFileSync(
  new URL("../android/app/src/androidTest/assets/sallimbook_cloud_home_state.js", import.meta.url),
  "utf8",
);
test.use({ trace: "off", screenshot: "off", video: "off" });

for (const mode of ["signed-out", "loading", "error", "ready"] as const) {
  test(`cloud onboarding proof rejects headings without authenticated API data: ${mode}`, async ({
    page,
  }) => {
    const state = await mockHomecare(page);
    state.appliances.length = 0;
    state.links.length = 0;
    state.consumables.length = 0;
    if (mode === "signed-out") {
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
    }
    let release: () => void = () => {};
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/v1/asset-comparison?*", async (route) => {
      if (mode === "loading") await pending;
      if (mode === "error")
        return route.fulfill({
          status: 503,
          json: {
            error: { code: "REQUEST_FAILED", message: "합성 조회 실패", request_id: "synthetic" },
          },
        });
      const month = new URL(route.request().url()).searchParams.get("to")!;
      const base = homeComparison(month);
      return route.fulfill({
        json: {
          ...base,
          state: "current_missing",
          from_month: null,
          current: { ...base.current, state: "missing", revision: null, totals: null },
          previous: null,
          item_count: 0,
          items: [],
          next_cursor: null,
        },
      });
    });
    try {
      await page.goto("/");
      await expect(
        page.getByRole("heading", { name: "우리 집 보유 현황", exact: true }),
      ).toBeVisible();
      await expect(page.locator("#consumables-title")).toBeVisible();
      // The previous native assertion would falsely pass all four states.
      expect(
        await page.evaluate(
          () =>
            location.pathname === "/" &&
            document.body.innerText.includes("자산") &&
            document.body.innerText.includes("소모품"),
        ),
      ).toBe(true);
      if (mode === "ready") {
        await expect.poll(() => page.evaluate(predicate)).toBe(true);
        expect(await page.evaluate(homeState)).toBe("1111000111");
      } else {
        if (mode === "error") await expect(page.getByRole("alert").first()).toBeVisible();
        if (mode === "signed-out")
          await expect(
            page.getByText(
              "로그인하면 우리 가계의 공용 재고와 기기별 교체 상태를 확인할 수 있어요.",
            ),
          ).toBeVisible();
        expect(await page.evaluate(predicate)).toBe(false);
        expect(await page.evaluate(homeState)).toMatch(/^[01]{10}$/);
      }
    } finally {
      release();
    }
  });
}

// Native cold start is locked, unlike the ordinary signed-out browser shell.
// This verifies the initial proof premise; it does not simulate Android focus.
test("cloud initial native lock has no finance headings and cannot satisfy the home proof", async ({
  page,
}) => {
  const state = await mockNativeOnboarding(page);
  state.locked = true;
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("앱이 잠겨 있어요");
  await expect(page.locator("#assets-title, #consumables-title")).toHaveCount(0);
  expect(await page.evaluate(predicate)).toBe(false);
  expect(await page.evaluate(homeState)).toBe("1000000000");
  expect(state.http).toHaveLength(0);
  expect(state.calls.every((call) => call.method === "getSession")).toBe(true);
});

const careError = readFileSync(
  new URL("../android/app/src/androidTest/assets/sallimbook_cloud_care_error.js", import.meta.url),
  "utf8",
);
test("care diagnostics return only known public classifications, excluding warranty and arbitrary text", async ({
  page,
}) => {
  await page.setContent(
    '<section aria-labelledby="consumables-title"><div role="alert"><p></p></div><details><div role="alert"><p>이 작업을 할 권한이 없어요.</p></div></details></section>',
  );
  const samples = [
    ["서버 연결을 확인하지 못했어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.", "NETWORK"],
    ["입력 형식과 필수 항목을 확인해 주세요.", "VALIDATION"],
    [
      "앱의 네이티브 인증을 준비하고 있어요. 지금은 앱에서 로그인할 수 없어요.",
      "NATIVE_UNAVAILABLE",
    ],
    ["synthetic-sensitive", "OTHER"],
    ["이 작업을 할 권한이 없어요. synthetic-sensitive", "OTHER"],
  ];
  for (const [text, classification] of samples) {
    await page.locator('section > [role="alert"] p').evaluate((p, text) => {
      p.textContent = text;
    }, text);
    expect(await page.evaluate(careError)).toBe(classification);
  }
  await page.locator('section > [role="alert"]').evaluate((alert) => alert.remove());
  expect(await page.evaluate(careError)).toBe("NONE");
});
