import { expect, test } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockCashflow } from "./support/cashflow";
import { uid } from "./support/finance";
import fixture from "../../../packages/test-fixtures/expense-plans.json" with { type: "json" };
type S = components["schemas"];
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
test("monthly plans show server totals, annual original, exclusions, unknown and zero without payment tasks", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const rows: S["PlanResponse"][] = fixture.rows.map((p, i) => {
    const v = {
      id: uid(300 + i),
      title: `합성 계획 ${i}`,
      category: "합성 분류",
      amount_mode: "fixed",
      economic_type: "expense",
      frequency: "monthly",
      interval_count: 1,
      tracking_mode: "plan_only",
      plan_kind: "recurring",
      budget_treatment: "included",
      effective_from: "2025-02-20",
      effective_until: null,
      reason: null,
      created_at: "2025-02-20T03:00:00Z",
      revoked_at: null,
      anchor_date: null,
      annual_month: null,
      subject_member_id: null,
      account_id: null,
      card_id: null,
      loan_asset_id: null,
      currency_reference: null,
      foreign_amount_reference: null,
      note: null,
      ...p,
      monthly_equivalent_krw: ["10001", "10000", "7000", "9000", null, "0"][i],
    } as S["PlanVersionResponse"];
    return {
      id: uid(400 + i),
      household_id: uid(3),
      version: 1,
      ended_on: null,
      end_reason: null,
      versions: [v],
      history: [v],
    };
  });
  await page.route("**/api/v1/expense-plans?*", (r) =>
    r.fulfill({ json: { items: rows, next_cursor: null } }),
  );
  await page.route("**/api/v1/expense-plan-summary", (r) =>
    r.fulfill({
      json: {
        ...fixture.expected,
        as_of: "2025-02-20",
        excluded_unknown_count: 0,
        unconverted_count: 0,
        categories: [],
        treatments: [],
        economic_types: [],
      },
    }),
  );
  await page.goto("/fixed-payments");
  const summary = page.getByRole("region", { name: "현재 월 지출 계획", exact: true });
  await expect(summary).toContainText("27,001원");
  await expect(summary).toContainText("20,001원");
  await expect(summary).toContainText("9,000원");
  await expect(page.getByRole("button", { name: "예정 회차 생성 열기" })).toHaveCount(0);
  const annual = page.locator(".record-list > li").filter({ hasText: "합성 계획 0" });
  await expect(annual).toContainText("120,006원");
  await expect(annual).toContainText("10,001원");
  await expect(page.locator(".record-list > li").filter({ hasText: "합성 계획 4" })).toContainText(
    "금액 미정",
  );
  await expect(page.locator(".record-list > li").filter({ hasText: "합성 계획 5" })).toContainText(
    "0원",
  );
  await page.getByLabel("계획 보기").selectOption("budget");
  await expect(page.locator(".record-list > li")).toHaveCount(1);
  await expect(page.locator(".record-list > li")).toContainText("7,000원");
  expect(state.writes).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
test("simple plan save needs no payment day and reloads the registered item", async ({ page }) => {
  await mockCashflow(page);
  let saved: Record<string, unknown> | null = null;
  await page.route("**/api/v1/expense-plans**", async (route) => {
    if (new URL(route.request().url()).pathname !== "/api/v1/expense-plans")
      return route.fallback();
    if (route.request().method() === "POST") {
      saved = route.request().postDataJSON();
      return route.fulfill({ status: 201, json: { id: uid(401), version: 1 } });
    }
    const v = {
      ...saved,
      id: uid(301),
      effective_from: "2025-02-20",
      effective_until: null,
      created_at: "2025-02-20T03:00:00Z",
      revoked_at: null,
      reason: null,
      monthly_equivalent_krw: "12345",
      anchor_date: null,
    };
    return route.fulfill({
      json: {
        items: saved
          ? [
              {
                id: uid(401),
                household_id: uid(3),
                version: 1,
                ended_on: null,
                end_reason: null,
                versions: [v],
                history: [v],
              },
            ]
          : [],
        next_cursor: null,
      },
    });
  });
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "지출 계획 추가", exact: true }).click();
  await page.getByLabel("이름", { exact: true }).fill("합성 새 월 계획");
  await page.getByLabel("계획 금액 (미정이면 비워두기)", { exact: true }).fill("12345");
  await page.getByText("결제수단·주기·관련 구성원·메모", { exact: true }).click();
  await page.getByRole("combobox", { name: "납부수단 구분", exact: true }).selectOption("card");
  await page.getByRole("combobox", { name: "납부 카드", exact: true }).selectOption(uid(50));
  await page.getByRole("button", { name: "계획 저장", exact: true }).click();
  await expect(page.getByRole("button", { name: "합성 새 월 계획", exact: true })).toBeVisible();
  expect(saved).toMatchObject({
    expected_amount_krw: "12345",
    tracking_mode: "plan_only",
    plan_kind: "recurring",
    effective_from: "2025-02-20",
  });
  expect(saved).not.toHaveProperty("anchor_date");
});

test("refresh while editing keeps the draft's original version and rejects an intervening spouse edit", async ({
  page,
}) => {
  await mockCashflow(page);
  let version = 1,
    reads = 0,
    sentVersion: string | undefined;
  await page.route("**/api/v1/expense-plans**", async (route) => {
    if (route.request().method() === "PATCH") {
      sentVersion = route.request().headers()["if-match"];
      return route.fulfill({
        status: 409,
        json: { error: { code: "VERSION_CONFLICT", message: "합성 충돌" } },
      });
    }
    reads++;
    const v = {
      title: "합성 공유 계획",
      category: "생활비",
      amount_mode: "fixed",
      economic_type: "expense",
      frequency: "monthly",
      interval_count: 1,
      tracking_mode: "plan_only",
      plan_kind: "recurring",
      budget_treatment: "included",
      expected_amount_krw: version === 1 ? "12000" : "50000",
      monthly_equivalent_krw: version === 1 ? "12000" : "50000",
      id: uid(301),
      effective_from: "2025-02-20",
      effective_until: null,
      created_at: "2025-02-20T03:00:00Z",
      revoked_at: null,
      reason: null,
      anchor_date: null,
    };
    return route.fulfill({
      json: {
        items: [
          {
            id: uid(401),
            household_id: uid(3),
            version,
            ended_on: null,
            end_reason: null,
            versions: [v],
            history: [v],
          },
        ],
        next_cursor: null,
      },
    });
  });
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "합성 공유 계획", exact: true }).click();
  await page.getByLabel("계획 금액 (미정이면 비워두기)", { exact: true }).fill("15000");
  version = 2;
  const previousReads = reads;
  await page.getByRole("button", { name: "월 계획 새로고침", exact: true }).click();
  await expect.poll(() => reads).toBeGreaterThan(previousReads);
  await expect(page.getByRole("button", { name: "월 계획 새로고침", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "계획 저장", exact: true }).click();
  await expect.poll(() => sentVersion).toBe('"1"');
  await expect(page.getByLabel("계획 금액 (미정이면 비워두기)", { exact: true })).toHaveValue(
    "15000",
  );
});
