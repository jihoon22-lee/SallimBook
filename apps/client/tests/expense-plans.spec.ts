import { expect, test } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockCashflow, planRow, ruleRow } from "./support/cashflow";
import { uid } from "./support/finance";
import fixture from "../../../packages/test-fixtures/expense-plans.json" with { type: "json" };
type S = components["schemas"];
function refreshPlan(version = 1): S["PlanResponse"] {
  const base = ruleRow(401);
  const terms: S["PlanVersionResponse"] = {
    ...base.versions[0]!,
    title: "합성 새로고침 계획",
    expected_amount_krw: version === 1 ? "12000" : "50000",
    monthly_equivalent_krw: version === 1 ? "12000" : "50000",
    tracking_mode: "plan_only",
    plan_kind: "recurring",
    budget_treatment: "included",
    annual_month: null,
    subject_member_id: null,
    revoked_at: null,
    anchor_date: null,
  };
  return { ...base, version, versions: [terms], history: [terms] };
}

for (const mode of ["edit", "new"] as const) {
  for (const failure of ["list-network", "summary-503"] as const) {
    test(`${mode} draft survives ${failure} refresh failure and recovery`, async ({ page }) => {
      await mockCashflow(page);
      let fail = false;
      let version = 1;
      let saved: Record<string, unknown> | undefined;
      let sentVersion: string | undefined;
      let releaseRetry!: () => void;
      const retryGate = new Promise<void>((resolve) => {
        releaseRetry = resolve;
      });
      let holdRetry = false;
      await page.route("**/api/v1/expense-plans**", async (route) => {
        if (route.request().method() === "PATCH") {
          sentVersion = route.request().headers()["if-match"];
          return route.fulfill({
            status: 409,
            json: { error: { code: "VERSION_CONFLICT", message: "합성 충돌" } },
          });
        }
        if (route.request().method() === "POST") {
          saved = route.request().postDataJSON();
          return route.fulfill({ status: 201, json: refreshPlan() });
        }
        if (fail && failure === "list-network") return route.abort("failed");
        if (holdRetry) await retryGate;
        const row = refreshPlan(version);
        if (saved) {
          row.versions[0] = { ...row.versions[0]!, ...saved };
          row.history = row.versions;
        }
        return route.fulfill({ json: { items: [row], next_cursor: null } });
      });
      await page.route("**/api/v1/expense-plan-summary", (route) =>
        fail && failure === "summary-503"
          ? route.fulfill({
              status: 503,
              json: { error: { code: "REQUEST_FAILED", message: "합성 조회 실패" } },
            })
          : route.fallback(),
      );
      await page.goto("/fixed-payments");
      await page
        .getByRole("button", {
          name: mode === "edit" ? "합성 새로고침 계획" : "지출 계획 추가",
          exact: true,
        })
        .click();
      const editor = page.getByRole("region", { name: "지출 계획 편집", exact: true });
      await editor.getByLabel("이름", { exact: true }).fill("합성 보존할 계획");
      const amount = editor.getByLabel("계획 금액 (미정이면 비워두기)", { exact: true });
      await amount.fill("15000");
      await editor.getByText("결제수단·주기·관련 구성원·메모", { exact: true }).click();
      const note = editor.getByRole("textbox", { name: "메모", exact: true });
      await note.fill("합성 미저장 메모");
      const refresh = page.getByRole("button", { name: "월 계획 새로고침", exact: true });
      fail = true;
      await refresh.click();
      await expect(page.getByRole("alert")).toBeVisible();
      await expect(refresh).toBeEnabled();
      await expect(editor).toBeVisible();
      await expect(amount).toHaveValue("15000");
      await expect(note).toHaveValue("합성 미저장 메모");
      await page.getByRole("button", { name: "뒤로", exact: true }).click();
      await expect(page.getByRole("alertdialog")).toBeVisible();
      await page.getByRole("button", { name: "계속 입력하기", exact: true }).click();
      fail = false;
      version = 2;
      holdRetry = true;
      await refresh.click();
      await expect(refresh).toBeDisabled();
      await expect(amount).toHaveValue("15000");
      await note.fill("합성 재시도 중에도 보존할 메모");
      releaseRetry();
      await expect(refresh).toBeEnabled();
      await expect(page.getByRole("alert")).toHaveCount(0);
      await expect(amount).toHaveValue("15000");
      await expect(note).toHaveValue("합성 재시도 중에도 보존할 메모");
      await editor.getByRole("button", { name: "계획 저장", exact: true }).click();
      if (mode === "edit") {
        await expect(page.getByRole("alert")).toContainText("다른 곳에서 기록이 변경됐어요");
        expect(sentVersion).toBe('"1"');
        await expect(amount).toHaveValue("15000");
        await expect(note).toHaveValue("합성 재시도 중에도 보존할 메모");
      } else {
        await expect(
          page.getByRole("button", { name: "합성 보존할 계획", exact: true }),
        ).toBeVisible();
        expect(saved).toMatchObject({
          title: "합성 보존할 계획",
          expected_amount_krw: "15000",
          note: "합성 재시도 중에도 보존할 메모",
        });
      }
    });
  }
}
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
test("session expiry during refresh still removes the protected plan editor", async ({ page }) => {
  await mockCashflow(page);
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "지출 계획 추가", exact: true }).click();
  await page.getByLabel("이름", { exact: true }).fill("합성 비공개 초안");
  await page.route("**/api/v1/expense-plans?*", (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: "UNAUTHENTICATED", message: "합성 만료" } },
    }),
  );
  await page.getByRole("button", { name: "월 계획 새로고침", exact: true }).click();
  await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "지출 계획 편집", exact: true })).toHaveCount(0);
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
  const annual = page.locator(".expense-ledger tbody tr").filter({ hasText: "합성 계획 0" });
  await expect(annual).toContainText("120,006원");
  await expect(annual).toContainText("10,001원");
  await expect(
    page.locator(".expense-ledger tbody tr").filter({ hasText: "합성 계획 4" }),
  ).toContainText("금액 미정");
  await expect(
    page.locator(".expense-ledger tbody tr").filter({ hasText: "합성 계획 5" }),
  ).toContainText("0원");
  await page.getByLabel("계획 보기").selectOption("budget");
  await expect(page.locator(".expense-ledger tbody tr")).toHaveCount(1);
  await expect(page.locator(".expense-ledger tbody tr")).toContainText("7,000원");
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

test("compact ledger shows payment names without opening items and searches across metadata pages", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const rows = Array.from({ length: 49 }, (_, i) => {
    const row = refreshPlan();
    row.id = uid(600 + i);
    row.versions[0] = {
      ...row.versions[0]!,
      title: `합성 월 계획 ${i + 1}`,
      category: "생활비",
      currency_reference: null,
      foreign_amount_reference: null,
      card_id: i % 2 === 0 ? uid(50) : null,
      account_id: i % 2 === 1 ? uid(30) : null,
    };
    row.history = row.versions;
    return row;
  });
  let cardReads = 0;
  await page.route("**/api/v1/cards?*", (route) => {
    cardReads++;
    const cursor = new URL(route.request().url()).searchParams.get("cursor");
    return route.fulfill({
      json: cursor
        ? { items: state.cards, next_cursor: null }
        : { items: [], next_cursor: "second" },
    });
  });
  await page.route("**/api/v1/expense-plans?*", (route) =>
    route.fulfill({ json: { items: rows, next_cursor: null } }),
  );
  await page.goto("/fixed-payments");
  const table = page.getByRole("table", { name: "월 지출 계획 표" });
  await expect(table.getByRole("row")).toHaveCount(50);
  await expect(table.getByRole("link", { name: "합성 구독 카드", exact: true })).toHaveCount(25);
  await expect(table.getByRole("link", { name: "합성 개인 금융 자산", exact: true })).toHaveCount(
    24,
  );
  await expect(table.getByText("납부 카드 보기", { exact: true })).toHaveCount(0);
  expect(cardReads).toBeLessThanOrEqual(4); // StrictMode may read twice; never 49 per-row requests.
  const height = await table
    .locator("tbody tr")
    .first()
    .evaluate((el) => el.getBoundingClientRect().height);
  expect(height).toBeLessThanOrEqual(106);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await table.scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath("compact-ledger.png"), fullPage: false });
  await page.getByLabel("계획 검색", { exact: true }).fill("합성 구독 카드");
  await expect(table.locator("tbody tr")).toHaveCount(25);
  expect(state.writes).toHaveLength(0);
});

test("a future payment-method change shows on the plan list and on both card pages", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  state.cards.push({ ...state.cards[0]!, id: uid(51), alias: "합성 새 카드", last_four: "2222" });
  const plan = planRow(420, {
    title: "합성 수단 변경 계획",
    card_id: uid(50),
    effective_from: "2025-01-01",
    effective_until: "2025-03-01",
  });
  plan.versions.push({
    ...plan.versions[0]!,
    id: uid(521),
    card_id: uid(51),
    effective_from: "2025-03-01",
    effective_until: null,
  });
  plan.history = plan.versions;
  state.ruleInsuranceLinks.set(plan.id, {
    rule_id: plan.id,
    link: {
      id: uid(522),
      policy_id: uid(80),
      product_name: "합성 실손",
      insurer: "합성 보험사",
      policy_status: "active",
      active: true,
      ended_at: null,
    },
  });
  await page.route("**/api/v1/expense-plans?*", (route) =>
    route.fulfill({ json: { items: [plan], next_cursor: null } }),
  );
  await page.goto("/fixed-payments");
  const row = page
    .getByRole("table", { name: "월 지출 계획 표" })
    .getByRole("row")
    .filter({ hasText: "합성 수단 변경 계획" });
  await expect(row.getByRole("link", { name: "합성 구독 카드", exact: true })).toBeVisible();
  await expect(row).toContainText("변경 예정: 2025.03.01부터 합성 새 카드");
  await row.getByRole("button", { name: "합성 수단 변경 계획", exact: true }).click();
  const editor = page.getByRole("region", { name: "지출 계획 편집", exact: true });
  await expect(editor).toContainText("보험료로 연결된 계약:");
  await expect(
    editor.getByRole("link", { name: "합성 실손 · 합성 보험사", exact: true }),
  ).toHaveAttribute("href", `/insurance/policies/${uid(80)}`);
  // The card it leaves names the next card; the card it moves to reads as "this card".
  await page.goto(`/cards/${uid(50)}`);
  await expect(page.getByRole("region", { name: "연결된 월 계획", exact: true })).toContainText(
    "변경 예정: 2025.03.01부터 합성 새 카드",
  );
  await page.goto(`/cards/${uid(51)}`);
  await expect(page.getByRole("region", { name: "연결된 월 계획", exact: true })).toContainText(
    "변경 예정: 2025.03.01부터 이 카드",
  );
  expect(state.writes).toHaveLength(0);
});
test("payment metadata failure keeps plans visible and recovers names without opening a card", async ({
  page,
}) => {
  await mockCashflow(page);
  const row = refreshPlan();
  row.versions[0]!.card_id = uid(50);
  await page.route("**/api/v1/expense-plans?*", (route) =>
    route.fulfill({ json: { items: [row], next_cursor: null } }),
  );
  let fail = true;
  await page.route("**/api/v1/cards?*", (route) =>
    fail ? route.abort("failed") : route.fallback(),
  );
  await page.goto("/fixed-payments");
  await expect(page.getByRole("button", { name: "합성 새로고침 계획", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "연결 카드 확인 필요", exact: true })).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "납부수단 다시 불러오기", exact: true }).click();
  await expect(page.getByRole("link", { name: "합성 구독 카드", exact: true })).toBeVisible();
});
