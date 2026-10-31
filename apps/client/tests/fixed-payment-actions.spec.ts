import { expect, test } from "@playwright/test";
import { uid } from "./support/finance";
import { mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";

test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
for (const nativeMode of [false, true]) {
  test(`${nativeMode ? "native" : "web"} rule save prepares twelve months and retries only preparation`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    const native = nativeMode ? await mockNativeCashflow(page, state) : null;
    state.failure = "after";
    state.failurePath = "/api/v1/obligations/generate";
    await page.goto("/fixed-payments/rules/new");
    await page.getByLabel("규칙 이름", { exact: true }).fill("합성 예정 준비");
    await page.getByLabel("원화 예정금액 (원)", { exact: true }).fill("100");
    await page.getByLabel("주기 기준일", { exact: true }).fill("2025-01-31");
    await page.getByLabel("적용 시작일", { exact: true }).fill("2025-01-01");
    await page.getByRole("button", { name: "납부 규칙 저장", exact: true }).click();
    await expect(
      page.getByText("규칙은 저장됐어요. 예정 회차 준비 결과를 확인해 주세요.", { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("규칙 이름", { exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "예정 회차 준비 다시 확인", exact: true }).click();
    await expect(page.getByRole("heading", { name: "납부 규칙 상세", exact: true })).toBeVisible();
    const creates = state.writes.filter((r) => r.path === "/api/v1/recurring-rules");
    const prepares = state.writes.filter((r) => r.path === "/api/v1/obligations/generate");
    expect(creates).toHaveLength(1);
    expect(prepares).toHaveLength(2);
    expect(prepares[1]).toEqual(prepares[0]);
    expect(prepares[0]!.body).toEqual({
      start_date: "2025-02-01",
      end_date: "2026-01-31",
      rule_id: state.rules.at(-1)!.id,
    });
    await expect(
      page.getByRole("status").filter({ hasText: "2025.02.01 ~ 2026.01.31" }),
    ).toBeVisible();
    if (native) expect(native.http).toEqual([]);
  });
}

for (const nativeMode of [false, true]) {
  test(`${nativeMode ? "native" : "web"} batch payment starts unselected and retries only an uncertain row`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    const transfer = {
      ...state.obligations[0]!,
      id: uid(73),
      title: "합성 연금 납입",
      economic_type: "asset_transfer" as const,
      expected_amount_krw: "100000",
      difference_krw: "-100000",
    };
    const exception = {
      ...state.obligations[0]!,
      id: uid(74),
      title: "합성 수동 예외",
      manual_override: true,
    };
    state.obligations.push(transfer, exception);
    state.rememberObligation(transfer, "create");
    state.rememberObligation(exception, "create");
    const native = nativeMode ? await mockNativeCashflow(page, state) : null;
    state.failure = "after";
    state.failurePath = `/api/v1/obligations/${transfer.id}/settlements`;
    await page.goto("/fixed-payments?view=payments");
    expect(state.writes).toHaveLength(0);
    await page.getByRole("button", { name: "여러 회차 납부 입력 열기", exact: true }).click();
    const panel = page.getByRole("region", { name: "선택 납부 입력", exact: true });
    await expect(panel.getByRole("checkbox")).toHaveCount(3);
    await expect(panel.getByRole("checkbox").first()).not.toBeChecked();
    await expect(panel.getByLabel("함께 기록할 실제 납부일", { exact: true })).toHaveValue("");
    await expect(
      panel.getByRole("button", { name: "선택한 실제 납부 저장", exact: true }),
    ).toBeDisabled();
    await panel.getByRole("checkbox", { name: new RegExp(state.obligations[0]!.title) }).check();
    await panel.getByRole("checkbox", { name: /합성 연금 납입/ }).check();
    await panel.getByLabel("함께 기록할 실제 납부일", { exact: true }).fill("2025-02-19");
    await expect(panel).toContainText(
      "실제 납부 합계 133,000원 · 소비 33,000원 · 자산 이동 100,000원",
    );
    await panel
      .getByRole("checkbox", {
        name: "선택한 회차를 위 날짜에 예정액과 같은 금액으로 실제 납부했어요.",
        exact: true,
      })
      .check();
    await panel.getByRole("button", { name: "선택한 실제 납부 저장", exact: true }).click();
    await expect(panel).toContainText("1 / 2건 저장 확인");
    await expect(
      panel.getByRole("button", { name: "미확인 회차만 다시 확인", exact: true }),
    ).toBeEnabled();
    expect(state.payments).toHaveLength(2);
    await panel.getByRole("button", { name: "미확인 회차만 다시 확인", exact: true }).click();
    await expect(panel).toContainText("2 / 2건 저장 확인");
    expect(state.payments).toHaveLength(2);
    expect(state.writes).toHaveLength(3);
    expect(state.writes[0]!.key).not.toBe(state.writes[1]!.key);
    expect(state.writes[1]).toEqual(state.writes[2]);
    expect(state.writes.map((r) => r.body.occurred_on)).toEqual(Array(3).fill("2025-02-19"));
    await panel.getByRole("button", { name: "결과 확인 후 닫기", exact: true }).click();
    await expect(panel).toHaveCount(0);
    if (native) expect(native.http).toEqual([]);
  });
}

test("batch conflict keeps the saved result and requires individual review", async ({ page }) => {
  const state = await mockCashflow(page);
  const extra = {
    ...state.obligations[0]!,
    id: uid(73),
    title: "합성 충돌 회차",
  };
  state.obligations.push(extra);
  state.rememberObligation(extra, "create");
  state.conflict = true;
  state.conflictPath = `/api/v1/obligations/${extra.id}/settlements`;
  await page.goto("/fixed-payments?view=payments");
  await page.getByRole("button", { name: "여러 회차 납부 입력 열기", exact: true }).click();
  const panel = page.getByRole("region", { name: "선택 납부 입력", exact: true });
  await panel.getByRole("checkbox", { name: new RegExp(state.obligations[0]!.title) }).check();
  await panel.getByRole("checkbox", { name: /합성 충돌 회차/ }).check();
  await panel.getByLabel("함께 기록할 실제 납부일", { exact: true }).fill("2025-02-19");
  await panel
    .getByRole("checkbox", {
      name: "선택한 회차를 위 날짜에 예정액과 같은 금액으로 실제 납부했어요.",
      exact: true,
    })
    .check();
  await panel.getByRole("button", { name: "선택한 실제 납부 저장", exact: true }).click();
  await expect(panel).toContainText("1 / 2건 저장 확인");
  await expect(panel).toContainText("개별 확인 필요");
  await expect(
    panel.getByRole("button", { name: "미확인 회차만 다시 확인", exact: true }),
  ).toBeDisabled();
  await expect(
    panel.getByRole("link", { name: "현재 회차와 납부 내역 확인", exact: true }),
  ).toHaveAttribute("href", `/fixed-payments/${extra.id}`);
  expect(state.payments).toHaveLength(1);
});

for (const nativeMode of [false, true]) {
  test(`${nativeMode ? "native" : "web"} individual payment suggests amount but requires date before save and next`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    const native = nativeMode ? await mockNativeCashflow(page, state) : null;
    await page.goto(`/fixed-payments/${uid(70)}?task=settle`);
    await expect(page.getByLabel("실제 납부금액 (원)", { exact: true })).toHaveValue("33000");
    await expect(page.getByLabel("실제 납부일", { exact: true })).toHaveValue("");
    await page.getByRole("button", { name: "저장하고 다음 미기록 회차", exact: true }).click();
    expect(state.writes).toHaveLength(0);
    await page.getByRole("button", { name: "오늘 실제 납부", exact: true }).click();
    await page.getByRole("button", { name: "저장하고 다음 미기록 회차", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/fixed-payments/${uid(71)}\\?task=settle$`));
    await expect(
      page.getByText("이전 회차의 실제 납부를 저장했어요. 다음 회차를 확인해 주세요.", {
        exact: true,
      }),
    ).toBeVisible();
    expect(state.writes).toHaveLength(1);
    expect(state.writes[0]!.body).toMatchObject({ amount_krw: "33000", occurred_on: "2025-02-20" });
    await expect(page.getByLabel("실제 원금 상환액 (원)", { exact: true })).toHaveValue("");
    await expect(page.getByLabel("실제 납부일", { exact: true })).toHaveValue("");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    if (native) expect(native.http).toEqual([]);
  });
}

test("next lookup failure retries a read without resubmitting a saved payment", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  let failNext = true;
  await page.route(/\/api\/v1\/obligations\?/, async (route) => {
    if (failNext) {
      failNext = false;
      await route.abort("failed");
    } else await route.fallback();
  });
  await page.goto(`/fixed-payments/${uid(70)}?task=settle`);
  await page.getByRole("button", { name: "오늘 실제 납부", exact: true }).click();
  await page.getByRole("button", { name: "저장하고 다음 미기록 회차", exact: true }).click();
  const next = page.getByRole("region", { name: "다음 회차 확인", exact: true });
  await expect(
    next.getByRole("button", { name: "다음 회차만 다시 확인", exact: true }),
  ).toBeVisible();
  expect(state.payments).toHaveLength(1);
  await expect(page.getByRole("button", { name: "실제 납부 저장", exact: true })).toHaveCount(0);
  await next.getByRole("button", { name: "다음 회차만 다시 확인", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/fixed-payments/${uid(71)}\\?task=settle$`));
  expect(state.writes).toHaveLength(1);
});

test("future planned date is never silently used as actual date and partial payment has no suggestion", async ({
  page,
}) => {
  const state = await mockCashflow(page);
  const row = state.obligations[0]!;
  row.scheduled_date = "2025-02-28";
  row.actual_amount_krw = "10000";
  row.status = "partial";
  await page.goto(`/fixed-payments/${row.id}?task=settle`);
  await expect(page.getByLabel("실제 납부금액 (원)", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("실제 납부일", { exact: true })).toHaveValue("");
  await expect(page.getByRole("button", { name: "예정일에 실제 납부", exact: true })).toHaveCount(
    0,
  );
  expect(state.writes).toHaveLength(0);
});

for (const width of [320, 390, 1280]) {
  test(`payment list puts records before management at ${width}px in dark mode`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.emulateMedia({ colorScheme: "dark" });
    const state = await mockCashflow(page);
    await page.goto("/fixed-payments?view=payments");
    const record = page.getByRole("link", { name: state.obligations[0]!.title, exact: true });
    await expect(record).toBeVisible();
    const management = page.getByRole("link", { name: "규칙과 적용기간 관리", exact: true });
    expect((await record.boundingBox())!.y).toBeLessThan((await management.boundingBox())!.y);
    await expect(
      page.getByRole("link", { name: "납부 기록", exact: true }).first(),
    ).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.getByRole("button", { name: "여러 회차 납부 입력 열기", exact: true }).click();
    const panel = page.getByRole("region", { name: "선택 납부 입력", exact: true });
    await expect(panel).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}
