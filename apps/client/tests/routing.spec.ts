import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/household/setup", (route) =>
    route.fulfill({ json: { available: false } }),
  );
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "UNAUTHENTICATED",
          message: "로그인이 필요합니다.",
          request_id: "synthetic",
        },
      }),
    }),
  );
});

const routes = [
  ["/login", "로그인"],
  ["/onboarding", "공동 가계 시작"],
  ["/", "오늘의 살림"],
  ["/assets", "자산과 부채"],
  ["/assets/synthetic-asset", "자산 상세"],
  ["/assets/months/2026-10", "월별 자산 확인"],
  ["/assets/compare", "월간 자산 비교"],
  ["/accounts", "계좌 관리"],
  ["/accounts/synthetic-account", "계좌 상세"],
  ["/income", "월간 수입"],
  ["/income/new", "수입 입력"],
  ["/fixed-payments", "고정 납부"],
  ["/fixed-payments/synthetic-payment", "고정 납부 상세"],
  ["/cards", "카드 관리"],
  ["/cards/synthetic-card", "카드 상세"],
  ["/vault", "보관함"],
  ["/insurance/policies", "보험 계약"],
  ["/insurance/policies/synthetic-policy", "보험 계약 상세"],
  ["/insurance/cases", "보험 사건"],
  ["/insurance/cases/synthetic-case", "보험 사건 상세"],
  ["/insurance/payouts/new", "보험금 수령 입력"],
  ["/appliances", "가전 관리"],
  ["/appliances/synthetic-appliance", "가전 상세"],
  ["/consumables", "소모품 관리"],
  ["/consumables/synthetic-consumable", "소모품 상세"],
  ["/settings", "설정"],
] as const;

for (const [path, title] of routes)
  test(`direct entry and reload keep ${path} usable without inventing records`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
    await expect(page.getByText("기능 준비 중 · 현재는 화면 탐색만 가능해요.")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "기록 기능을 준비하고 있어요", exact: true }),
    ).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(errors).toEqual([]);
  });

test("navigation exposes five mobile tabs or the expanded desktop sidebar", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  const mobile = page.getByRole("navigation", { name: "주 메뉴", exact: true });
  const desktop = page.getByRole("navigation", { name: "전체 메뉴", exact: true });
  const nav = testInfo.project.name === "android-size" ? mobile : desktop;
  await expect(nav).toBeVisible();
  if (testInfo.project.name === "android-size") {
    await expect(desktop).toBeHidden();
    await expect(mobile.getByRole("link")).toHaveText(["홈", "자산", "생활비", "보험", "더보기"]);
    for (const link of await mobile.getByRole("link").all()) {
      const bounds = await link.boundingBox();
      expect(bounds!.height).toBeGreaterThanOrEqual(48);
      expect(bounds!.width).toBeGreaterThanOrEqual(48);
    }
  } else {
    await expect(mobile).toBeHidden();
    for (const label of [
      "계좌",
      "수입",
      "고정 납부",
      "카드",
      "계약",
      "사건·청구·지급",
      "가전",
      "소모품",
      "설정",
    ]) {
      await expect(desktop.getByRole("link", { name: label, exact: true })).toBeVisible();
    }
  }
  await nav.getByRole("link", { name: "생활비", exact: true }).click();
  await page.getByRole("main").getByRole("link", { name: "카드 관리", exact: false }).click();
  await expect(page).toHaveURL(/\/cards$/);
  // /cards is a sub-page of 생활비: the section is marked, but it is not the current page.
  await expect(nav.getByRole("link", { name: "생활비", exact: true })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(page.getByRole("main")).toBeFocused();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(page).toHaveURL(/\/living$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
});

test("fresh deep link back stays within the app and unknown paths have a safe home link", async ({
  page,
}) => {
  await page.goto("/insurance/cases/synthetic-case");
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(page).toHaveURL(/\/insurance\/cases$/);
  await page.goto("/not-a-screen");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("페이지를 찾을 수 없어요");
  await page.getByRole("link", { name: "홈으로 이동", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  for (const month of ["2026-13", "0000-01", "not-a-month"]) {
    await page.goto(`/assets/months/${month}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("월을 확인해 주세요");
  }
});

test("month selection follows monthly records while consumables remain today-based", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("확인할 월").fill("2025-02");
  await expect(page.getByText("월간 기록 · 2025년 2월")).toBeVisible();
  await expect(page.getByText("오늘 기준", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "자산 관리", exact: true }).click();
  await expect(page.getByLabel("확인할 월")).toHaveValue("2025-02");
  await page.getByRole("link", { name: "2025년 2월 월 기록 확인" }).click();
  await expect(page).toHaveURL(/\/assets\/months\/2025-02$/);
  await expect(page.getByText("서울 기준 · 2025년 2월", { exact: true })).toBeVisible();
});

for (const reload of [false, true]) {
  test(`a monthly deep link synchronizes the shared selector after back${reload ? " and reload" : ""}`, async ({
    page,
  }) => {
    await page.goto("/assets/months/2025-02");
    await expect(page.getByText("서울 기준 · 2025년 2월", { exact: true })).toBeVisible();
    if (reload) {
      await page.reload();
      await expect(page.getByText("서울 기준 · 2025년 2월", { exact: true })).toBeVisible();
    }
    await page.getByRole("button", { name: "뒤로", exact: true }).click();
    await expect(page).toHaveURL(/\/assets$/);
    await expect(page.getByLabel("확인할 월")).toHaveValue("2025-02");
    await page.getByRole("link", { name: "2025년 2월 월 기록 확인" }).click();
    await expect(page).toHaveURL(/\/assets\/months\/2025-02$/);
  });
}

test("signed-out vault requires a session before exposing protected controls", async ({ page }) => {
  await page.goto("/vault");
  await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "보관함 처음 설정", exact: true })).toHaveCount(0);
  await expect(page.locator("input, textarea")).toHaveCount(0);
  expect(
    await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })),
  ).toEqual({ local: 0, session: 0 });
});

test("keyboard skip link, dark mode and enlarged narrow layout remain usable", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "본문으로 바로가기" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(
    "dark",
  );
  await page.setViewportSize({ width: 320, height: 720 });
  await page.addStyleTag({ content: "html { font-size: 200%; }" });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("link", { name: "소모품 전체 관리" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("소모품 관리");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("selected month follows the Seoul month at midnight unless another month was chosen", async ({
  page,
}) => {
  // 2026-12-31 23:59:30 Asia/Seoul
  await page.clock.install({ time: new Date("2026-12-31T14:59:30Z") });
  await page.goto("/");
  const picker = page.getByLabel("확인할 월");
  await expect(picker).toHaveValue("2026-12");
  // 2027-01-01 00:00:30 Asia/Seoul crosses the year and month boundary.
  await page.clock.runFor(60_000);
  await expect(picker).toHaveValue("2027-01");
  await expect(page.getByText("월간 기록 · 2027년 1월")).toBeVisible();
  // Another month chosen by hand stays.
  await picker.fill("2026-09");
  await page.clock.setSystemTime(new Date("2027-01-31T14:59:30Z"));
  await page.clock.runFor(60_000);
  await expect(picker).toHaveValue("2026-09");
  // Choosing the current month again follows it again, here on return to the app.
  await picker.fill("2027-02");
  await page.clock.setSystemTime(new Date("2027-02-28T15:00:30Z"));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(picker).toHaveValue("2027-03");
});

test("data router keeps the in-app history index used by back", async ({ page }) => {
  await page.goto("/");
  expect(await page.evaluate(() => (history.state as { idx?: number } | null)?.idx)).toBe(0);
  await page.getByRole("banner").getByRole("link", { name: "설정", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  expect(await page.evaluate(() => (history.state as { idx?: number } | null)?.idx)).toBe(1);
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("오늘의 살림");
});

test("only the visited sub-page is the current page in desktop navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/settings/audit");
  const nav = page.getByRole("navigation", { name: "전체 메뉴" });
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
  const section = nav.locator(".nav-item[aria-current]");
  await expect(section).toHaveAttribute("aria-current", "true");
  const background = await section.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(background).not.toBe("rgba(0, 0, 0, 0)");
});
