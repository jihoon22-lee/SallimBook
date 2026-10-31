import { test, expect } from "@playwright/test";
import { mockComparison } from "./support/comparison";
import { uid } from "./support/finance";
import {
  chartCoordinates,
  deltaSign,
  latestConfirmedMonth,
  monthsBefore,
  percentLabel,
  signedKrw,
} from "../src/features/assets/comparison/model";
import type { TrendPoint } from "../src/features/assets/comparison/model";
test.use({ trace: "off", screenshot: "off", video: "off" });
const path = "/assets/compare?to=2025-02&from=2025-01";

test("exact large amounts map to pixels without money conversion or gap interpolation", () => {
  const point = (amount: string | null) => ({ confirmed_amount_krw: amount }) as TrendPoint;
  const graph = chartCoordinates([
    point("9007199254740993"),
    point("9007199254740994"),
    point(null),
    point("9007199254740995"),
  ])!;
  expect(graph.rows.map((p) => p.y)).toEqual([185, 105, null, 25]);
  expect(graph.segments.map((s) => s.length)).toEqual([2, 1]);
  expect(signedKrw("9007199254740993")).toBe("+9,007,199,254,740,993원");
  expect(signedKrw("-20")).toBe("-20원");
  expect(percentLabel(null)).toBe("계산하지 않음");
  expect(percentLabel("0.00")).toBe("0.00%");
  expect(monthsBefore("0001-02", 119)).toBe("0001-01");
});
test("server totals, changed scope, share and debt effects are distinguished", async ({ page }) => {
  const state = await mockComparison(page);
  state.pageSize = 2;
  await page.goto(path);
  const summary = page.getByRole("region", { name: "월간 자산 변화", exact: true });
  await expect(summary).toContainText("2,040원");
  await expect(summary).toContainText("700원");
  await expect(summary).toContainText("+1,340원");
  await expect(summary).toContainText("+40원");
  await expect(summary).toContainText("+191.43%");
  await expect(summary).toContainText("추가 1개 · 제외 1개 · 지분 변경 1개");
  await expect(summary).toContainText("서로 다른 기준일이 섞여 있어요");
  const loan = page
    .locator(".comparison-item")
    .filter({ has: page.getByRole("heading", { name: "합성 대출" }) });
  await expect(loan).toContainText("-20원");
  await expect(loan).toContainText("+20원");
  await expect(
    page.getByText("이전에 보유한 항목이 새 비교 대상에 포함됨", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("확인 월 전에 보유가 종료된 항목", { exact: true })).toBeVisible();
  expect(state.queries.some((q) => q.has("cursor"))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
for (const [mode, text] of [
  ["no_previous_month", "첫 기록을 0원 대비 증가로 표시하지 않아요"],
  ["current_missing", "자산이 0원으로 줄어든 것으로 계산하지 않아요"],
  ["unconfirmed", "두 월을 확정하기 전에는 증감을 계산하지 않아요"],
] as const) {
  test(`${mode} suppresses invented deltas and percentages`, async ({ page }) => {
    const state = await mockComparison(page);
    state.mode = mode;
    await page.goto(path);
    const summary = page.getByRole("region", { name: "월간 자산 변화", exact: true });
    await expect(summary).toContainText(text);
    await expect(summary).toContainText("계산하지 않음");
    await expect(summary).not.toContainText("+1,340원");
    if (mode === "unconfirmed") {
      const table = page.getByRole("region", { name: "월별 추이 금액 표" });
      await expect(table.getByRole("row").filter({ hasText: "2025년 2월" })).toContainText(
        "미확정 참고값",
      );
      await expect(page.locator("circle.chart-point")).toHaveCount(2);
    }
  });
}
for (const negative of [false, true])
  test(`nonpositive prior net keeps delta but explains undefined rate (${negative})`, async ({
    page,
  }) => {
    const state = await mockComparison(page);
    state.zeroPrevious = !negative;
    state.negativePrevious = negative;
    await page.goto(path);
    const summary = page.getByRole("region", { name: "월간 자산 변화", exact: true });
    await expect(summary).toContainText(negative ? "이전 순자산이 음수" : "이전 순자산이 0원");
    await expect(summary).toContainText(negative ? "+2,740원" : "+2,040원");
    await expect(summary).toContainText("계산하지 않음");
  });

test("filters persist in the address and apply to both comparison and trend", async ({ page }) => {
  const state = await mockComparison(page);
  await page.goto(path);
  await page.getByLabel("비교 소유자 필터", { exact: true }).selectOption(uid(5));
  await page.getByLabel("비교 분류 필터", { exact: true }).selectOption("financial");
  await expect.poll(() => state.trendQueries.at(-1)?.get("owner_member_id")).toBe(uid(5));
  await expect.poll(() => state.trendQueries.at(-1)?.get("category")).toBe("financial");
  await expect(page).toHaveURL(/owner=.*category=financial/);
  await page.reload();
  await expect(page.getByLabel("비교 소유자 필터", { exact: true })).toHaveValue(uid(5));
  await expect(page.getByLabel("비교 분류 필터", { exact: true })).toHaveValue("financial");
  await page.getByRole("button", { name: "비교 필터 초기화", exact: true }).click();
  await expect(page).toHaveURL(/compare\?to=2025-02$/);
  await expect.poll(() => state.trendQueries.at(-1)?.has("owner_member_id")).toBe(false);
});
test("invalid dates never issue a comparison request", async ({ page }) => {
  const state = await mockComparison(page);
  await page.goto("/assets/compare?to=2025-02&from=2025-03");
  await expect(page.getByRole("alert")).toContainText("이전 비교월은 확인할 월보다 앞서야");
  expect(state.queries).toHaveLength(0);
});
test("a revision change between pages rejects the combined result until explicit reload", async ({
  page,
}) => {
  const state = await mockComparison(page);
  state.pageSize = 2;
  state.pageRace = true;
  await page.goto(path);
  await expect(page.getByRole("alert")).toContainText("조회 도중 월 기록이 변경됐어요");
  await expect(page.getByRole("heading", { name: "항목별 변화", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "비교 다시 불러오기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "항목별 변화", exact: true })).toBeVisible();
});
test("chart leaves absent months blank and offers exact accessible values", async ({ page }) => {
  await mockComparison(page);
  await page.goto(path);
  const table = page.getByRole("region", { name: "월별 추이 금액 표" });
  await expect(table).toBeVisible();
  await expect(page.locator("polyline.chart-line")).toHaveCount(1);
  await expect(page.locator("circle.chart-point")).toHaveCount(3);
  const absent = table.getByRole("row").filter({ hasText: "2024년 12월" });
  await expect(absent).toContainText("월 기록 없음");
  await expect(absent).toContainText("—");
  await expect(absent).not.toContainText("0원");
  await page
    .getByLabel("차트에서 확인할 월", { exact: true })
    .selectOption({ label: "2024년 12월 · 월 기록 없음" });
  await expect(page.locator(".chart-inspector")).toContainText("금액 없음");
  await page.getByRole("button", { name: "2025년 2월 2,040원", exact: true }).focus();
  await expect(page.locator(".chart-inspector")).toContainText("2,040원");
});
test("comparison and trend revision disagreement requires a joint refresh", async ({ page }) => {
  const state = await mockComparison(page);
  state.trendRace = true;
  await page.goto(path);
  await expect(page.getByRole("alert")).toContainText(" 조회 도중".trim());
  await expect(page.getByRole("region", { name: "월별 추이 금액 표" })).toHaveCount(0);
  const reads = state.queries.length;
  state.trendRace = false;
  await page.getByRole("button", { name: "비교와 추이 함께 다시 확인", exact: true }).click();
  await expect(page.getByRole("region", { name: "월별 추이 금액 표" })).toBeVisible();
  expect(state.queries.length).toBeGreaterThan(reads);
});
test("asset and account details use the same asset monthly record", async ({ page }) => {
  const state = await mockComparison(page);
  await page.clock.setFixedTime(new Date("2025-02-20T00:00:00Z"));
  for (const url of [`/assets/${uid(11)}`, `/accounts/${uid(30)}`]) {
    await page.goto(url);
    const section = page.getByRole("region", { name: "이 자산의 월 기록", exact: true });
    await expect(section).toContainText("항목 보유금액 변화: +20원");
    await expect(section).toContainText("100원");
    await expect(section).toContainText("120원");
    await expect.poll(() => state.trendQueries.at(-1)?.get("asset_id")).toBe(uid(11));
    expect(state.queries.at(-1)?.get("asset_id")).toBe(uid(11));
  }
});
test("home shows full totals before today's consumables even when requesting only one item", async ({
  page,
}) => {
  const state = await mockComparison(page);
  await page.clock.setFixedTime(new Date("2025-02-20T00:00:00Z"));
  await page.goto("/");
  await page.getByText("월별 자산 변화·기록 관리", { exact: true }).click();
  const summary = page.getByRole("region", { name: "자산의 변화", exact: true });
  await expect(summary).toContainText("+1,340원");
  expect(state.queries.at(-1)?.get("limit")).toBe("1");
  const headings = await page.getByRole("heading", { level: 2 }).allTextContents();
  expect(headings[0]).toBe("수입·지출");
  expect(headings).toContain("우리 집 보유 현황");
});

for (const mode of ["available", "unconfirmed"] as const)
  test(`selected excluded observation keeps date warnings in comparison and asset details (${mode})`, async ({
    page,
  }) => {
    const state = await mockComparison(page);
    state.mode = mode;
    await page.clock.setFixedTime(new Date("2025-02-20T00:00:00Z"));
    await page.route("**/api/v1/asset-comparison?*", async (route) => {
      const data = state.response(new URL(route.request().url()).searchParams);
      for (const period of [data.previous!, data.current])
        period.totals = {
          assets_krw: "0",
          liabilities_krw: "0",
          net_assets_krw: "0",
          item_count: 0,
          verified_count: 0,
          missing_count: 0,
          carried_count: 0,
          provisional: false,
        };
      data.previous!.dates = {
        non_month_end_asset_ids: [],
        missing_date_asset_ids: [uid(11)],
        mixed_dates: false,
      };
      data.current.dates = {
        non_month_end_asset_ids: [uid(11)],
        missing_date_asset_ids: [],
        mixed_dates: false,
      };
      data.total_delta_krw = data.common_scope_delta_krw = mode === "available" ? "0" : null;
      data.change_percent = null;
      data.change_percent_unavailable_reason =
        mode === "available" ? "zero_previous_total" : "unconfirmed";
      data.items = data.items.map((item) => ({
        ...item,
        before: {
          ...item.before!,
          inclusion_status: "excluded",
          as_of_date: null,
          input_amount_krw: null,
          owned_amount_krw: null,
          verification_state: "missing",
        },
        after: { ...item.after!, inclusion_status: "excluded", as_of_date: "2025-02-20" },
        before_in_scope: false,
        after_in_scope: false,
        membership: "excluded",
        same_scope: false,
        scope_reason: "excluded_from_total",
        amount_delta_krw: null,
        net_assets_effect_krw: mode === "available" ? "0" : null,
      }));
      await route.fulfill({ json: data });
    });
    for (const url of [
      `${path}&asset_id=${uid(11)}`,
      `/assets/${uid(11)}`,
      `/accounts/${uid(30)}`,
    ]) {
      await page.goto(url);
      const warning = page.locator(".date-warning");
      await expect(warning).toContainText("2025년 1월: 월말이 아닌 항목 0개 · 기준일 미입력 1개");
      await expect(warning).toContainText("2025년 2월: 월말이 아닌 항목 1개 · 기준일 미입력 0개");
      await expect(warning).not.toContainText("서로 다른 기준일이 섞여 있어요");
      if (url.startsWith("/assets/compare"))
        await page.getByText("두 월 기록 비교", { exact: true }).first().click();
      await expect(page.getByText("합계 제외", { exact: true }).first()).toBeVisible();
    }
  });

test("delta signs come from server decimal strings without numeric conversion", () => {
  expect(["-1", "-0.01", "-99999999999999999999"].map(deltaSign)).toEqual([
    "negative",
    "negative",
    "negative",
  ]);
  expect(["0", "0.00", "-0.00"].map(deltaSign)).toEqual(["zero", "zero", "zero"]);
  expect(["1", "191.43", "99999999999999999999"].map(deltaSign)).toEqual([
    "positive",
    "positive",
    "positive",
  ]);
  expect([null, "1e3", "1,000", ""].map(deltaSign)).toEqual([
    "unavailable",
    "unavailable",
    "unavailable",
    "unavailable",
  ]);
});

test("net asset decreases are marked negative on home and comparison screens", async ({ page }) => {
  const state = await mockComparison(page);
  await page.clock.setFixedTime(new Date("2025-02-20T00:00:00Z"));
  // Net assets 700원 → 40원.
  state.after[0]!.owned_amount_krw = "0";
  state.after[3]!.owned_amount_krw = "0";
  await page.goto("/");
  await page.getByText("월별 자산 변화·기록 관리", { exact: true }).click();
  const hero = page.locator(".asset-hero-change .money-delta");
  await expect(hero).toHaveText("-660원");
  await expect(hero).toHaveAttribute("data-sign", "negative");
  await expect(hero).toHaveCSS("color", "rgb(163, 53, 63)");
  await page.goto(path);
  await expect(
    page.locator('.money-delta[data-sign="negative"]').filter({ hasText: "-660원" }),
  ).toHaveCount(1);
  // The joint home's net-asset effect.
  await expect(
    page.locator('.money-delta[data-sign="negative"]').filter({ hasText: "-500원" }),
  ).toHaveCount(1);
  // An asset increase and a liability decrease.
  await expect(
    page.locator('.money-delta[data-sign="positive"]').filter({ hasText: "+20원" }),
  ).toHaveCount(2);
  // A liability's own amount change is not colored.
  await expect(page.locator(".money-delta").filter({ hasText: "-20원" })).toHaveCount(0);
  await expect(
    page
      .getByRole("region", { name: "월별 추이 금액 표" })
      .getByRole("columnheader", { name: "관찰 금액", exact: true }),
  ).toBeVisible();
});

test("latest confirmed month needs two consecutive confirmed months", () => {
  const point = (month: string, state: TrendPoint["state"]) => ({ month, state }) as TrendPoint;
  expect(
    latestConfirmedMonth([
      point("2024-11", "confirmed"),
      point("2024-12", "confirmed"),
      point("2025-01", "confirmed"),
      point("2025-02", "reopened"),
      point("2025-03", "draft"),
    ]),
  ).toBe("2025-01");
  // Across a year boundary.
  expect(latestConfirmedMonth([point("2024-12", "confirmed"), point("2025-01", "confirmed")])).toBe(
    "2025-01",
  );
  expect(
    latestConfirmedMonth([
      point("2024-10", "confirmed"),
      point("2024-11", "missing"),
      point("2024-12", "confirmed"),
    ]),
  ).toBeNull();
  expect(latestConfirmedMonth([point("2025-01", "confirmed")])).toBeNull();
  expect(latestConfirmedMonth([])).toBeNull();
});

test("home switches between this month and the latest confirmed comparison", async ({ page }) => {
  const state = await mockComparison(page);
  await page.clock.setFixedTime(new Date("2025-03-05T03:00:00Z"));
  await page.goto("/");
  await page.getByText("월별 자산 변화·기록 관리", { exact: true }).click();
  const summary = page.getByRole("region", { name: "자산의 변화", exact: true });
  const views = summary.getByRole("group", { name: "자산 변화 보기" });
  await expect(views.getByRole("button", { name: "이번 달", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect.poll(() => state.queries.at(-1)?.get("to")).toBe("2025-03");
  await views.getByRole("button", { name: "최근 확정 비교", exact: true }).click();
  await expect
    .poll(() => [state.trendQueries.at(-1)?.get("from"), state.trendQueries.at(-1)?.get("to")])
    .toEqual(["2023-04", "2025-03"]);
  await expect.poll(() => state.queries.at(-1)?.get("to")).toBe("2025-02");
  await expect(
    summary.getByText("2025년 1월 → 2025년 2월 확정 기록 비교", { exact: true }),
  ).toBeVisible();
  await expect(summary).toContainText("+1,340원");
  await expect(summary.getByRole("link", { name: "월간 비교 자세히 보기" })).toHaveAttribute(
    "href",
    "/assets/compare?to=2025-02",
  );
  await views.getByRole("button", { name: "이번 달", exact: true }).click();
  await expect.poll(() => state.queries.at(-1)?.get("to")).toBe("2025-03");
  // 2025-02 is being corrected, so the range has no two consecutive confirmed months.
  state.mode = "unconfirmed";
  await views.getByRole("button", { name: "최근 확정 비교", exact: true }).click();
  await expect(
    summary.getByText("최근 24개월 안에 연속으로 확정한 두 달이 없어요", { exact: false }),
  ).toBeVisible();
  await page.reload();
  await page.getByText("월별 자산 변화·기록 관리", { exact: true }).click();
  await expect(views.getByRole("button", { name: "이번 달", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("home record action starts or continues the month and asks for an asset first", async ({
  page,
}) => {
  const state = await mockComparison(page);
  await page.clock.setFixedTime(new Date("2025-03-05T03:00:00Z"));
  state.mode = "current_missing";
  await page.goto("/");
  await page.getByText("월별 자산 변화·기록 관리", { exact: true }).click();
  const summary = page.getByRole("region", { name: "자산의 변화", exact: true });
  const start = summary.getByRole("link", { name: "이번 달 기록 시작", exact: true });
  await expect(start).toHaveAttribute("href", "/assets/months/2025-03");
  await expect(start).toHaveClass(/button-link/);
  await expect(
    summary.locator("details").getByRole("link", { name: /기록|자산 관리/ }),
  ).toHaveCount(0);
  state.mode = "unconfirmed";
  await page.reload();
  await page.getByText("월별 자산 변화·기록 관리", { exact: true }).click();
  await expect(
    summary.getByRole("link", { name: "이번 달 기록 이어서 확인", exact: true }),
  ).toBeVisible();
  await expect(summary.locator(".asset-hero-change strong")).toHaveText("확정 후 비교");
  await expect(summary.getByRole("group", { name: "자산 변화 보기" })).toHaveAccessibleDescription(
    /확정된 비교는 '최근 확정 비교'에서 볼 수 있어요/,
  );
  state.mode = "current_missing";
  state.finance.assets.length = 0;
  await page.reload();
  await page.getByText("월별 자산 변화·기록 관리", { exact: true }).click();
  await expect(summary.getByRole("link", { name: "자산 등록", exact: true })).toHaveAttribute(
    "href",
    "/assets/new",
  );
  await expect(summary.getByRole("link", { name: /기록 시작/ })).toHaveCount(0);
  // A month that has not started yet.
  await page.getByLabel("확인할 월").fill("2025-04");
  await expect(summary.getByRole("link", { name: /기록 시작|기록 이어서|자산 등록/ })).toHaveCount(
    0,
  );
});
