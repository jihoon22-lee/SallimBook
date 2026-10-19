import { expect, test } from "@playwright/test";
import { mockComparison } from "./support/comparison";
import { mockHomecare } from "./support/homecare";
import { mockOnboarding } from "./support/onboarding";
import { mockFinance, uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });

async function homeData(page: import("@playwright/test").Page) {
  const comparison = await mockComparison(page);
  await mockHomecare(page);
  await page.route("**/api/v1/asset-comparison?*", (route) =>
    route.fulfill({ json: comparison.response(new URL(route.request().url()).searchParams) }),
  );
  return comparison;
}

test("home keeps date and scope cautions visible before expanding precise comparison details", async ({
  page,
}) => {
  await homeData(page);
  await page.goto("/");
  await page.getByLabel("확인할 월").fill("2025-02");
  const assets = page.getByRole("region", { name: "자산의 변화", exact: true });
  await expect(assets.getByText("2,040원", { exact: true })).toBeVisible();
  await expect(assets.getByText("비교 대상·지분 변경", { exact: true })).toBeVisible();
  await expect(assets.getByText("기준일 확인 필요", { exact: true })).toBeVisible();
  await expect(assets.locator("details")).not.toHaveAttribute("open", "");
  await assets.getByText("비교 기준과 상세 금액", { exact: true }).click();
  await expect(assets.getByText("+40원", { exact: true })).toBeVisible();
  await expect(assets.getByText("서로 다른 기준일이 섞여 있어요", { exact: false })).toBeVisible();
});

test("390px home presents consumable attention count and first status above the bottom navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await homeData(page);
  await page.goto("/");
  await page.getByLabel("확인할 월").fill("2025-02");
  await expect(page.getByText("기준일 확인 필요", { exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const today = await page.locator(".home-today .care-status").first().boundingBox();
  await expect(page.locator(".home-today .care-count")).toHaveText("확인할 소모품 2개");
  const nav = await page.getByRole("navigation", { name: "주 메뉴", exact: true }).boundingBox();
  expect(today!.y + today!.height).toBeLessThan(nav!.y);
  for (const link of await page.locator(".asset-detail-actions > a").all())
    expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(48);
  const settings = await page.getByRole("link", { name: "설정", exact: true }).boundingBox();
  expect(settings!.width).toBeGreaterThanOrEqual(48);
  expect(settings!.height).toBeGreaterThanOrEqual(48);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const currentState of ["draft", "reopened"] as const)
  test(`first month shows its ${currentState} state even when every amount is verified`, async ({
    page,
  }) => {
    const state = await homeData(page);
    state.mode = "no_previous_month";
    await page.route("**/api/v1/asset-comparison?*", (route) => {
      const data = state.response(new URL(route.request().url()).searchParams);
      data.current.state = currentState;
      data.current.confirmed_at = null;
      data.previous = null;
      data.from_month = null;
      expect(data.current.totals!.provisional).toBe(false);
      expect(data.current.totals!.verified_count).toBe(data.current.totals!.item_count);
      return route.fulfill({ json: data });
    });
    await page.goto("/");
    const assets = page.getByRole("region", { name: "자산의 변화", exact: true });
    await expect(assets.locator("details")).not.toHaveAttribute("open", "");
    await expect(
      assets.getByText(currentState === "draft" ? "확인 월 작성 중" : "확인 월 정정 중", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(assets.getByText("이전 월 기록 없음", { exact: true })).toBeVisible();
    await expect(assets.getByRole("status")).toHaveText(
      "확인한 합계 · 확인 4/4개 · 미입력 0개 · 전월값 미확인 0개",
    );
    await expect(assets.getByText("비교할 수 없음", { exact: true }).first()).toBeVisible();
  });

for (const available of [false, true])
  test(`login starts within the mobile viewport and keeps onboarding available (${available})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const state = await mockOnboarding(page);
    state.available = available;
    await page.goto("/login");
    const login = page.getByLabel("로그인 이름", { exact: true });
    await expect(login).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    expect((await login.boundingBox())!.y + (await login.boundingBox())!.height).toBeLessThan(700);
    await expect(page.getByRole("link", { name: "배우자 연결", exact: true })).toBeVisible();
    if (available)
      await expect(
        page.getByRole("link", { name: "우리 가계 시작하기", exact: true }),
      ).toBeVisible();
    expect(
      (await page.getByRole("button", { name: "로그인", exact: true }).boundingBox())!.y +
        (await page.getByRole("button", { name: "로그인", exact: true }).boundingBox())!.height,
    ).toBeLessThan(844);
    await expect(page.getByRole("navigation", { name: "주 메뉴", exact: true })).toBeHidden();
    await expect(page.getByRole("link", { name: "설정", exact: true })).toBeVisible();
    for (const field of await page
      .locator(".auth-form input:visible, .auth-form button:visible")
      .all())
      expect((await field.boundingBox())!.height).toBeGreaterThanOrEqual(48);
  });

test("dark enlarged narrow layouts retain exact large money and insurance content", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 320, height: 720 });
  const state = await homeData(page);
  await page.route("**/api/v1/asset-comparison?*", (route) => {
    const data = state.response(new URL(route.request().url()).searchParams);
    data.current.totals!.net_assets_krw = "9007199254740993";
    return route.fulfill({ json: data });
  });
  await page.goto("/");
  await page.addStyleTag({ content: "html { font-size: 200%; }" });
  await expect(page.getByText("9,007,199,254,740,993원", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(
    "dark",
  );
  await page.goto(`/insurance/cases/${uid(90)}`);
  await page.addStyleTag({ content: "html { font-size: 200%; }" });
  await expect(page.getByRole("heading", { name: "보험 사건 상세", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("invalid changed device name reopens its control before password submission", async ({
  page,
}) => {
  const state = await mockOnboarding(page);
  state.available = false;
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill("owner");
  await page.getByLabel("비밀번호", { exact: true }).fill("synthetic-design-only-password");
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill("");
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.getByLabel("이 기기 이름", { exact: true })).toBeVisible();
  expect(state.loginWrites).toBe(0);
});

for (const mode of ["zero", "negative", "unconfirmed"] as const)
  test(`home detailed comparison retains the unavailable rate explanation (${mode})`, async ({
    page,
  }) => {
    const state = await homeData(page);
    if (mode === "zero") state.zeroPrevious = true;
    if (mode === "negative") state.negativePrevious = true;
    if (mode === "unconfirmed") state.mode = "unconfirmed";
    await page.goto("/");
    const assets = page.getByRole("region", { name: "자산의 변화", exact: true });
    await assets.getByText("비교 기준과 상세 금액", { exact: true }).click();
    await expect(
      assets.getByText(
        mode === "zero"
          ? "이전 순자산이 0원이어서 증감률을 계산하지 않아요."
          : mode === "negative"
            ? "이전 순자산이 음수여서 증감률을 계산하지 않아요. 원 단위 변화를 확인해 주세요."
            : "두 월의 확정 기록이 필요해요.",
        { exact: true },
      ),
    ).toBeVisible();
    if (mode === "unconfirmed")
      await expect(
        assets.getByText(
          "위에 보이는 월 금액은 현재 작성본의 참고 합계예요. 미확인 금액을 포함할 수 있어요.",
          { exact: true },
        ),
      ).toBeVisible();
  });

test("failed home comparison retains navigation to month records and asset management", async ({
  page,
}) => {
  await homeData(page);
  await page.route("**/api/v1/asset-comparison?*", (route) =>
    route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "synthetic", request_id: "synthetic" } },
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "홈 자산 정보 다시 확인", exact: true }),
  ).toBeVisible();
  const assets = page.getByRole("region", { name: "자산의 변화", exact: true });
  for (const name of ["월간 비교 자세히 보기", "이 달 기록 확인", "자산 관리"])
    await expect(assets.getByRole("link", { name, exact: true })).toBeVisible();
});

test("390px enlarged home moves the month selector to its own readable row", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await homeData(page);
  await page.goto("/");
  await page.addStyleTag({ content: "html { font-size: 200%; }" });
  await page.evaluate(() => document.fonts.ready);
  const title = await page.getByRole("heading", { level: 1 }).boundingBox();
  const month = await page.getByLabel("확인할 월", { exact: true }).boundingBox();
  expect(month!.y).toBeGreaterThanOrEqual(title!.y + title!.height);
  expect(month!.width).toBeGreaterThan(280);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("asset error offers a visible retry while filters remain collapsed", async ({ page }) => {
  const state = await mockFinance(page);
  state.listFailure = true;
  await page.goto("/assets");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator(".asset-filter-panel")).not.toHaveAttribute("open", "");
  const retry = page.getByRole("button", { name: "자산 목록 다시 불러오기", exact: true });
  await expect(retry).toBeVisible();
  state.listFailure = false;
  await retry.click();
  await expect(page.getByRole("link", { name: "합성 공동 주택", exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
