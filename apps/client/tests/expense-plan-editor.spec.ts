import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockCashflow } from "./support/cashflow";
import { uid } from "./support/finance";
type S = components["schemas"];

function plan(id: number, patch: Partial<S["PlanVersionResponse"]> = {}): S["PlanResponse"] {
  const terms: S["PlanVersionResponse"] = {
    id: uid(id + 100),
    title: `합성 계획 ${id}`,
    category: "합성 분류",
    amount_mode: "fixed",
    expected_amount_krw: "12000",
    monthly_equivalent_krw: "12000",
    economic_type: "expense",
    frequency: "monthly",
    interval_count: 1,
    tracking_mode: "plan_only",
    plan_kind: "recurring",
    budget_treatment: "included",
    effective_from: "2025-02-01",
    effective_until: null,
    reason: null,
    created_at: "2025-02-01T03:00:00Z",
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
    ...patch,
  };
  return {
    id: uid(id),
    household_id: uid(3),
    version: 1,
    ended_on: null,
    end_reason: null,
    versions: [terms],
    history: [terms],
  };
}

type Write = { method: string; path: string; body: unknown; key?: string; version?: string };
/** Plan reads return `rows`; writes are recorded and answered like the server would. */
async function mockPlans(page: Page, rows: S["PlanResponse"][]) {
  const writes: Write[] = [];
  await page.route("**/api/v1/expense-plans**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!path.startsWith("/api/v1/expense-plans")) return route.fallback();
    if (request.method() === "GET")
      return route.fulfill({ json: { items: rows, next_cursor: null } });
    writes.push({
      method: request.method(),
      path,
      body: request.postDataJSON(),
      key: request.headers()["idempotency-key"],
      version: request.headers()["if-match"],
    });
    if (request.method() === "DELETE") return route.fulfill({ status: 204 });
    if (request.method() === "POST" && path === "/api/v1/expense-plans") {
      const body = request.postDataJSON() as S["PlanCreate"];
      const created = plan(450, { ...body, monthly_equivalent_krw: body.expected_amount_krw });
      rows.push(created);
      return route.fulfill({ status: 201, json: { id: created.id, version: 1 } });
    }
    return route.fulfill({ json: { id: rows[0]!.id, version: 2 } });
  });
  return writes;
}

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});

test("cancelling a changed plan asks first and a closed editor leaves no dead back step", async ({
  page,
}) => {
  await mockCashflow(page);
  await mockPlans(page, [plan(401)]);
  await page.goto("/fixed-payments");
  const editor = page.getByRole("region", { name: "지출 계획 편집", exact: true });
  await page.getByRole("button", { name: "합성 계획 401", exact: true }).click();
  await expect(editor).toBeVisible();
  await editor.getByRole("button", { name: "입력 취소", exact: true }).click();
  await expect(editor).toHaveCount(0);
  expect(new URL(page.url()).searchParams.has("plan")).toBe(false);
  // Closing went back to the list entry, so Back now leaves the screen instead of staying.
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/living");

  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "합성 계획 401", exact: true }).click();
  const amount = editor.getByLabel("계획 금액 (미정이면 비워두기)", { exact: true });
  await amount.fill("15000");
  await editor.getByRole("button", { name: "입력 취소", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.getByRole("button", { name: "계속 입력하기", exact: true }).click();
  await expect(amount).toHaveValue("15000");
  await editor.getByRole("button", { name: "입력 취소", exact: true }).click();
  await page.getByRole("button", { name: "입력 버리고 나가기", exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByRole("table", { name: "월 지출 계획 표" })).toBeVisible();
});

test("plan search and view survive a visit to the linked card", async ({ page }) => {
  await mockCashflow(page);
  await mockPlans(page, [
    plan(401, { title: "합성 카드 계획", card_id: uid(50) }),
    plan(402, { title: "합성 카드 예산", card_id: uid(50), plan_kind: "budget" }),
    plan(403, { title: "합성 계좌 계획" }),
  ]);
  await page.goto("/fixed-payments");
  const rows = page.locator(".expense-ledger tbody tr");
  await expect(rows).toHaveCount(3);
  await page.getByLabel("계획 검색", { exact: true }).fill("합성 카드");
  await page.getByLabel("계획 보기").selectOption("fixed");
  await expect(rows).toHaveCount(1);
  await rows.getByRole("link", { name: "합성 구독 카드", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(`/cards/${uid(50)}`);
  await page.goBack();
  await expect(page.getByLabel("계획 검색", { exact: true })).toHaveValue("합성 카드");
  await expect(page.getByLabel("계획 보기")).toHaveValue("fixed");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("합성 카드 계획");
});

test("ending a plan uses its own visible date and deleting needs an explicit check", async ({
  page,
}) => {
  await mockCashflow(page);
  const writes = await mockPlans(page, [plan(401)]);
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "합성 계획 401", exact: true }).click();
  const editor = page.getByRole("region", { name: "지출 계획 편집", exact: true });
  await editor.getByText("계획 종료·삭제", { exact: true }).click();
  const remove = editor.getByRole("button", { name: "계획 삭제하기", exact: true });
  await expect(remove).toBeDisabled();
  await editor.getByLabel("잘못 등록한 계획의 삭제를 확인했어요", { exact: true }).check();
  await expect(remove).toBeEnabled();
  await editor.getByLabel("종료일", { exact: true }).fill("2025-03-31");
  await expect(editor).toContainText("2025-03-31부터 월 계획 합계에서 빠져요.");
  await editor.getByRole("button", { name: "계획 종료하기", exact: true }).click();
  await expect(editor).toHaveCount(0);
  expect(writes).toEqual([
    expect.objectContaining({
      method: "POST",
      path: `/api/v1/expense-plans/${uid(401)}/end`,
      body: { effective_on: "2025-03-31", reason: "월 계획 종료" },
      version: '"1"',
    }),
  ]);
});

test("a scheduled plan prepares its due dates after saving and retries with the same key", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const writes = await mockPlans(page, []);
  state.failure = "before";
  state.failurePath = "/api/v1/obligations/generate";
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "지출 계획 추가", exact: true }).click();
  const editor = page.getByRole("region", { name: "지출 계획 편집", exact: true });
  await editor.getByLabel("이름", { exact: true }).fill("합성 통신비");
  await editor.getByLabel("계획 금액 (미정이면 비워두기)", { exact: true }).fill("55000");
  await editor.getByText("적용일·납부 일정 관리", { exact: true }).click();
  await editor.getByLabel("관리방식").selectOption("scheduled");
  await editor.getByLabel("납부 기준일", { exact: true }).fill("2025-02-25");
  await editor.getByRole("button", { name: "계획 저장", exact: true }).click();
  await expect(editor.getByRole("heading", { name: "납부 일정 준비", exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toBeVisible();
  expect(writes.filter((w) => w.method === "POST")).toHaveLength(1);
  await editor.getByRole("button", { name: "납부 일정 다시 준비", exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByRole("button", { name: "합성 통신비", exact: true })).toBeVisible();
  const prepared = state.writes.filter((w) => w.path === "/api/v1/obligations/generate");
  expect(prepared).toHaveLength(2);
  expect(prepared[0]!.key).toMatch(/^prepare:/);
  expect(prepared[1]!.key).toBe(prepared[0]!.key);
  expect(prepared[0]!.body).toEqual({
    rule_id: uid(450),
    start_date: "2025-02-20",
    end_date: "2026-01-31",
  });
  expect(writes.filter((w) => w.method === "POST")).toHaveLength(1);
});

test("categories are suggested and a foreign reference needs both code and amount", async ({
  page,
}) => {
  await mockCashflow(page);
  const writes = await mockPlans(page, [plan(401, { category: "합성 반려동물" })]);
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "지출 계획 추가", exact: true }).click();
  const editor = page.getByRole("region", { name: "지출 계획 편집", exact: true });
  const category = editor.getByLabel("분류", { exact: true });
  const options = await category.evaluate((input) =>
    [...((input as HTMLInputElement).list?.options ?? [])].map((option) => option.value),
  );
  expect(options).toEqual(expect.arrayContaining(["합성 반려동물", "구독", "통신비"]));
  await editor.getByLabel("이름", { exact: true }).fill("합성 해외 구독");
  await editor.getByText("결제수단·주기·관련 구성원·메모", { exact: true }).click();
  await editor.getByLabel("외화 결제 통화 (선택, 예: USD)", { exact: true }).fill("usd");
  await editor.getByRole("button", { name: "계획 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "외화 참고는 통화 코드(예: USD)와 금액을 함께 입력해 주세요.",
  );
  expect(writes).toHaveLength(0);
  await editor.getByLabel("외화 참고 금액 (선택)", { exact: true }).fill("20.5");
  await editor.getByRole("button", { name: "계획 저장", exact: true }).click();
  await expect(editor).toHaveCount(0);
  expect(writes[0]!.body).toMatchObject({
    currency_reference: "USD",
    foreign_amount_reference: "20.5",
    expected_amount_krw: null,
  });
});

test("the monthly plan summary shows spending, loans and savings transfers apart", async ({
  page,
}) => {
  await mockCashflow(page);
  await mockPlans(page, [plan(401)]);
  await page.route("**/api/v1/expense-plan-summary", (route) =>
    route.fulfill({
      json: {
        as_of: "2025-02-20",
        fixed_known_krw: "1300000",
        budget_known_krw: "500000",
        combined_known_krw: "1800000",
        excluded_known_krw: "0",
        included_unknown_count: 1,
        excluded_unknown_count: 0,
        unconverted_count: 0,
        plan_count: 4,
        categories: [
          { key: "생활비", known_krw: "500000", unknown_count: 0, unconverted_count: 0, count: 1 },
        ],
        treatments: [],
        economic_types: [
          { key: "expense", known_krw: "800000", unknown_count: 1, unconverted_count: 0, count: 2 },
          { key: "loan", known_krw: "700000", unknown_count: 0, unconverted_count: 0, count: 1 },
          {
            key: "asset_transfer",
            known_krw: "300000",
            unknown_count: 0,
            unconverted_count: 0,
            count: 1,
          },
        ],
      },
    }),
  );
  await page.goto("/fixed-payments");
  const summary = page.getByRole("region", { name: "현재 월 지출 계획", exact: true });
  await expect(summary.locator('[data-economic="expense"]')).toHaveText(
    "소비성 비용800,000원 · 미정 1개",
  );
  await expect(summary.locator('[data-economic="loan"]')).toHaveText("대출 원리금700,000원");
  await expect(summary.locator('[data-economic="asset_transfer"]')).toHaveText(
    "연금 납입 등 자산 이동300,000원",
  );
  await expect(summary).toContainText("월 계획 합계 1,800,000원");
  await summary.getByText("분류별 소계 1개", { exact: true }).click();
  await expect(summary.getByRole("listitem")).toHaveText(["생활비 1개500,000원"]);
});
