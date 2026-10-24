import { expect, test, type Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockCashflow, ruleRow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
type Row = components["schemas"]["PaymentSwitchRow"];
function row(id: number): Row {
  return {
    id: uid(id),
    title: `합성 변경 ${id}`,
    version: 1,
    periods: ruleRow(id, { account_id: uid(30), card_id: null }).versions,
    unchanged_period_count: 1,
    update_occurrence_count: 3,
    preserved_past_count: 2,
    preserved_paid_count: 1,
    preserved_manual_count: 1,
    blocked_reason: null,
    preview_digest: String(id).padStart(64, "0"),
  };
}
async function setup(page: Page, native = false) {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
  const state = await mockCashflow(page);
  state.linksRequired = true;
  const model = {
    rows: [row(60), row(61)],
    conflict: true,
    abort: false,
    gate: null as Promise<void> | null,
    writes: [] as { id: string; body: any; headers: Record<string, string> }[],
    previews: 0,
  };
  const original = state.handle;
  const handler: typeof state.handle = async (method, path, query, body, headers) => {
    if (!path.startsWith("/api/v1/payment-switch"))
      return original(method, path, query, body, headers);
    if (path.endsWith("/preview")) {
      model.previews++;
      return { status: 200, body: { items: model.rows, next_cursor: null } };
    }
    const id = path.split("/").at(-1)!;
    model.writes.push({ id, body, headers });
    if (model.gate) await model.gate;
    if (model.abort) {
      model.abort = false;
      return { status: 0, abort: true, body: null };
    }
    if (model.conflict && id === uid(61)) {
      model.conflict = false;
      model.rows = model.rows.map((r) =>
        r.id === id ? { ...r, version: 2, preview_digest: "b".repeat(64) } : r,
      );
      return { status: 409, body: { error: { code: "PAYMENT_LINKS_CHANGED" } } };
    }
    model.rows = model.rows.filter((r) => r.id !== id);
    return { status: 200, body: { id, version: 2 } };
  };
  state.handle = handler;
  await page.route("**/api/v1/payment-switch/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const response = await handler(
      req.method(),
      url.pathname,
      url.searchParams,
      req.postDataJSON(),
      req.headers(),
    );
    if (response!.abort) return route.abort("failed");
    return route.fulfill({ status: response!.status, json: response!.body });
  });
  const bridge = native ? await mockNativeCashflow(page, state) : null;
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "계좌 사용 종료하기", exact: true }).click();
  await page.getByRole("button", { name: "연결 규칙 결제수단 바꾸기" }).click();
  const panel = page.getByRole("region", { name: "결제수단 일괄 변경", exact: true });
  return { model, bridge, panel };
}
async function choose(page: Page) {
  await page.getByRole("combobox", { name: "납부수단 구분", exact: true }).selectOption("card");
  await page.getByRole("combobox", { name: "납부 카드", exact: true }).selectOption(uid(50));
  await page.getByRole("button", { name: "변경 미리보기", exact: true }).click();
}
for (const native of [false, true])
  test(`${native ? "native" : "web"} saves selected rules and rechecks only conflicts`, async ({
    page,
  }) => {
    const { model, panel, bridge } = await setup(page, native);
    await choose(page);
    await expect(panel).toContainText("수동 예외 보존 1개");
    await expect(panel).toContainText("금융기관·서비스");
    await panel.getByRole("checkbox", { name: "합성 변경 60", exact: true }).check();
    await panel.getByRole("checkbox", { name: "합성 변경 61", exact: true }).check();
    await panel.getByRole("button", { name: "선택한 규칙 변경", exact: true }).click();
    await expect(panel.getByText("변경 완료", { exact: true })).toHaveCount(1);
    await expect(panel.getByRole("button", { name: "실패·충돌 항목만 다시 검토" })).toBeEnabled();
    await panel.getByRole("button", { name: "실패·충돌 항목만 다시 검토" }).click();
    await expect(panel.getByRole("checkbox", { name: "합성 변경 60", exact: true })).toBeDisabled();
    await panel.getByRole("checkbox", { name: "합성 변경 61", exact: true }).check();
    await panel.getByRole("button", { name: "선택한 규칙 변경", exact: true }).click();
    await expect(panel.getByText("변경 완료", { exact: true })).toHaveCount(2);
    expect(model.writes.map((r) => r.id)).toEqual([uid(60), uid(61), uid(61)]);
    expect(model.writes[2]!.body.preview_digest).toBe("b".repeat(64));
    expect(model.writes[2]!.headers["if-match"]).toBe('"2"');
    await expect(
      page.getByRole("button", { name: "계좌 사용 종료 확인", exact: true }),
    ).toBeDisabled();
    if (bridge) {
      expect(bridge.http).toEqual([]);
      expect(bridge.calls.filter((r) => r.method === "applyPaymentSwitch")).toHaveLength(3);
    }
  });
test("invalid date, same source and blocked rows cannot save; changing target discards the preview", async ({
  page,
}) => {
  const { model, panel } = await setup(page);
  await panel.getByRole("button", { name: "변경 미리보기" }).click();
  await expect(panel.getByRole("alert")).toContainText("다른 납부 계좌 또는 카드");
  await page.getByRole("combobox", { name: "납부수단 구분", exact: true }).selectOption("account");
  await page.getByRole("combobox", { name: "납부 계좌", exact: true }).selectOption(uid(30));
  await panel.getByRole("button", { name: "변경 미리보기" }).click();
  expect(model.previews).toBe(0);
  await page.getByLabel("변경 적용일", { exact: true }).fill("");
  await panel.getByRole("button", { name: "변경 미리보기" }).click();
  await expect(panel.getByRole("alert")).toContainText("올바른 적용일");
  await page.getByLabel("변경 적용일", { exact: true }).fill("2025-02-20");
  model.rows[0]!.blocked_reason = "INITIAL_PERIOD_START";
  await choose(page);
  await expect(panel.getByRole("checkbox", { name: "합성 변경 60", exact: true })).toBeDisabled();
  await expect(panel).toContainText("첫 규칙 시작일 다음 날부터");
  await page.getByLabel("변경 적용일", { exact: true }).fill("2025-02-21");
  await expect(panel.getByRole("checkbox")).toHaveCount(0);
  expect(model.writes).toHaveLength(0);
});
test("ambiguous network failure retries the same key and request", async ({ page }) => {
  const { model, panel } = await setup(page);
  model.abort = true;
  await choose(page);
  await panel.getByRole("checkbox", { name: "합성 변경 60", exact: true }).check();
  await panel.getByRole("button", { name: "선택한 규칙 변경", exact: true }).click();
  await panel.getByRole("button", { name: "같은 요청 다시 확인" }).click();
  await expect(panel.getByText("변경 완료", { exact: true })).toHaveCount(1);
  expect(model.writes).toHaveLength(2);
  expect(model.writes[0]!.body).toEqual(model.writes[1]!.body);
  expect(model.writes[0]!.headers["idempotency-key"]).toBe(
    model.writes[1]!.headers["idempotency-key"],
  );
});
test("pending batch disables closure and leaving the panel stops further rows", async ({
  page,
}) => {
  const { model, panel } = await setup(page);
  let release!: () => void;
  model.gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await choose(page);
  await page
    .getByRole("region", { name: "사용 종료 영향 확인", exact: true })
    .getByRole("checkbox")
    .first()
    .check();
  for (const id of [60, 61])
    await panel.getByRole("checkbox", { name: `합성 변경 ${id}`, exact: true }).check();
  await panel.getByRole("button", { name: "선택한 규칙 변경", exact: true }).click();
  await expect.poll(() => model.writes.length).toBe(1);
  await expect(
    page.getByRole("button", { name: "계좌 사용 종료 확인", exact: true }),
  ).toBeDisabled();
  await page.getByRole("link", { name: "홈", exact: true }).first().click();
  await page.getByRole("button", { name: "입력 버리고 나가기", exact: true }).click();
  release();
  await expect(page).toHaveURL(/\/$/);
  expect(model.writes).toHaveLength(1);
});
test("small dark viewport keeps preview readable without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.emulateMedia({ colorScheme: "dark" });
  const { panel } = await setup(page);
  await choose(page);
  await page.addStyleTag({ content: "html { font-size: 20px; }" });
  await panel.getByText("현재·미래 적용 기간 1개 확인", { exact: true }).first().click();
  await expect(panel).toContainText("현재 규칙");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
