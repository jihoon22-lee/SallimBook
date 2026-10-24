import { expect, test } from "@playwright/test";
import { mockMonths } from "./support/months";
import { mockComparison } from "./support/comparison";
import { mockAudit } from "./support/audit";
import { compareAmounts } from "../src/features/assets/amountSort";
import { formatFileSize } from "../src/shared/format";
test.use({ trace: "off", screenshot: "off", video: "off" });

test("exact server amounts sort without float rounding and missing never becomes zero", () => {
  expect(
    ["9007199254740993", "9007199254740994", null, "0"].sort((a, b) => compareAmounts(a, b)),
  ).toEqual(["9007199254740994", "9007199254740993", "0", null]);
  expect(["-21", "20", null, "0"].sort((a, b) => compareAmounts(a, b, true))).toEqual([
    "-21",
    "20",
    "0",
    null,
  ]);
  expect(formatFileSize(0)).toBe("0바이트");
  expect(formatFileSize(1536)).toBe("1.5 KiB");
  expect(formatFileSize(20 * 1024 * 1024)).toBe("20 MiB");
});

test("month rows sort server owned values, retain missing and zero, and open one editor", async ({
  page,
}, info) => {
  const state = await mockMonths(page);
  const rows = state.record!.values;
  rows[0]!.owned_amount_krw = "501";
  rows[1]!.input_amount_krw = "0";
  rows[1]!.owned_amount_krw = "0";
  rows[1]!.verification_state = "verified";
  await page.goto("/assets/months/2025-02");
  await page.getByLabel("월 기록 정렬", { exact: true }).selectOption("amount");
  const records = page.locator(".month-value-card");
  await expect(records).toHaveCount(3);
  await expect(records.nth(0)).toContainText(rows[0]!.name);
  await expect(records.nth(1)).toContainText("0원");
  await expect(records.nth(2)).toContainText("미입력");
  const table = page.getByRole("region", { name: "월 기록 금액 표", exact: true });
  if (info.project.name === "desktop") {
    await expect(table).toBeVisible();
    await expect(table.locator("td.owned-amount").first()).toHaveCSS("text-align", "right");
    await expect(table.locator("td.owned-amount").first()).toContainText("501원");
    await expect(table.locator("td.owned-amount").first()).not.toContainText("1,001원");
    await records.first().getByText("이 기록의 소유·지분·보유기간", { exact: true }).click();
    await expect(records.first()).toContainText("입력 금액 1,001원");
  } else await expect(table).toHaveCount(0);
  await records
    .first()
    .getByRole("button", { name: `${rows[0]!.name} 금액 확인`, exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: `${rows[0]!.name} 금액 확인`, exact: true }),
  ).toBeVisible();
  const amount = page.getByLabel("확인 금액 (원)", { exact: true });
  await amount.fill("777");
  await page.setViewportSize(
    info.project.name === "desktop" ? { width: 390, height: 844 } : { width: 1280, height: 800 },
  );
  await expect(amount).toHaveValue("777");
  await page.getByRole("button", { name: "입력 취소", exact: true }).click();
  expect(state.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("comparison groups scope and share effects while sorting magnitude within groups", async ({
  page,
}, info) => {
  const state = await mockComparison(page);
  state.pageSize = 2;
  // Server fixtures compute +50 for debt decrease and -30 for asset decrease.
  state.after[1]!.owned_amount_krw = "70";
  state.after[2]!.owned_amount_krw = "50";
  await page.goto("/assets/compare?to=2025-02&from=2025-01");
  await page.getByLabel("항목별 변화 정렬", { exact: true }).selectOption("effect");
  const rows = page.locator(".comparison-item");
  await expect(rows).toHaveCount(5);
  await expect(rows.nth(0)).toContainText("합성 대출");
  await expect(rows.nth(0)).toContainText("+50원");
  await expect(rows.nth(1)).toContainText("-30원");
  await expect(rows.nth(2)).toContainText("지분 변경");
  await expect(rows.nth(3)).toContainText("범위 추가");
  await expect(rows.nth(4)).toContainText("범위 제외");
  if (info.project.name === "desktop") {
    const table = page.getByRole("region", { name: "항목별 자산 비교 표", exact: true });
    await expect(table).toBeVisible();
    const bounds = await table.boundingBox();
    expect(bounds!.height).toBeLessThan(750);
    await expect(rows.first().locator("td").last()).toHaveCSS("text-align", "right");
  }
  expect(state.queries.some((q) => q.has("cursor"))).toBe(true);
  await page.getByLabel("항목별 변화 정렬", { exact: true }).selectOption("name");
  await expect(rows.first()).toContainText("합성 대출");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("current month entry is independent of selected history and branding is present", async ({
  page,
}) => {
  await mockMonths(page);
  await page.clock.setFixedTime(new Date("2025-02-20T00:00:00Z"));
  await page.goto("/assets");
  await page.getByLabel("확인할 월", { exact: true }).fill("2024-12");
  await expect(page.getByRole("link", { name: "이번 달 기록하기", exact: true })).toHaveAttribute(
    "href",
    "/assets/months/2025-02",
  );
  await expect(
    page.getByRole("link", { name: "2024년 12월 월 기록 확인", exact: true }),
  ).toHaveAttribute("href", "/assets/months/2024-12");
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", "/favicon.svg");
  expect(await (await page.request.get("/favicon.svg")).text()).toContain("#22675f");
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute("content", "#22675f");
});

for (const failure of [false, true])
  test(`installed native app version has explicit failure and retry (${failure})`, async ({
    page,
  }) => {
    const state = await mockAudit(page, true);
    state.appInfoFailure = failure;
    await page.goto("/settings");
    if (failure) {
      await expect(page.getByRole("alert")).toContainText("Android 앱 버전을 확인하지 못했어요");
      state.appInfoFailure = false;
      await page.getByRole("button", { name: "앱 버전 다시 확인", exact: true }).click();
    }
    await expect(page.getByText("Android 앱 버전 0.9.8 · 빌드 42", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "가계 구성원 관리", exact: true })).toHaveAttribute(
      "href",
      "/settings/auth",
    );
    await expect(page.getByRole("link", { name: "초대받은 계정 등록", exact: true })).toHaveCount(
      0,
    );
    expect(state.http).toEqual([]);
  });
