import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockMonths, total, verifyAll } from "./support/months";
import { mockComparison } from "./support/comparison";
import { members, uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
type Call = { method: string; args: Record<string, any> };
// This verifies React transport dispatch; native JVM/device checks establish Android security.
async function bridge(page: Page, handle: (call: Call) => unknown) {
  const calls: Call[] = [];
  const http: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) http.push(request.url());
  });
  await page.exposeFunction("syntheticNative", async (method: string, args: Call["args"]) => {
    calls.push({ method, args });
    if (method === "getSession")
      return { ok: true, value: { available: true, authenticated: true } };
    if (method === "request")
      return {
        ok: true,
        value: { status: 200, body: args.path === "/api/v1/me" ? members[0] : members },
      };
    return handle({ method, args });
  });
  await page.addInitScript(() =>
    Object.assign(window, {
      CapacitorCustomPlatform: { name: "android" },
      Capacitor: {
        PluginHeaders: [
          {
            name: "SallimBookAuth",
            methods: [
              "getSession",
              "request",
              "getAssetMonth",
              "getAssetMonthRevision",
              "listAssetMonthRevisions",
              "createAssetMonthDraft",
              "updateAssetMonthValue",
              "synchronizeAssetMonthScope",
              "confirmAssetMonth",
              "reopenAssetMonth",
              "carryPreviousAssetMonth",
              "getAssetComparison",
              "getAssetTrends",
              "getAsset",
              "getAccount",
              "listAssets",
            ]
              .map((name) => ({ name, rtype: "promise" }))
              .concat([
                { name: "addListener", rtype: "callback" },
                { name: "removeListener", rtype: "promise" },
              ]),
          },
        ],
        nativeCallback: () => "synthetic-listener",
        nativePromise: (_plugin: string, method: string, args = {}) =>
          method === "removeListener"
            ? Promise.resolve()
            : (window as any).syntheticNative(method, args),
      },
    }),
  );
  return { calls, http };
}
const ok = (body: unknown) => ({ ok: true, value: { status: 200, body } });
const fail = (code: string) => ({ ok: false, code });

test("native monthly reads and updates preserve identity and version without WebView HTTP", async ({
  page,
}) => {
  const state = await mockMonths(page);
  const native = await bridge(page, ({ method, args }) => {
    if (method === "getAssetMonth" || method === "getAssetMonthRevision")
      return ok(args.month === "2025-01" ? state.previous : state.record);
    if (method === "listAssetMonthRevisions")
      return ok({ items: [{ ...state.record }], next_cursor: null });
    if (method === "updateAssetMonthValue") {
      const row = state.record!.values.find((r) => r.asset_id === args.assetId)!;
      Object.assign(row, args.input, {
        owned_amount_krw: "4503599627370497",
        verification_state: "verified",
        version: 2,
      });
      state.record!.version++;
      state.record!.totals = total(state.record!.values);
      return ok({
        value: row,
        revision_version: state.record!.version,
        totals: state.record!.totals,
      });
    }
    return fail("INVALID_REQUEST");
  });
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "합성 공동 주택 금액 확인", exact: true }).click();
  await page.getByLabel("확인 금액 (원)", { exact: true }).fill("9007199254740993");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(page.getByText("확인한 금액과 기준일을 저장했어요.", { exact: true })).toBeVisible();
  expect(native.calls.find((c) => c.method === "updateAssetMonthValue")!.args).toMatchObject({
    month: "2025-02",
    assetId: uid(10),
    ifMatch: '"1"',
    input: {
      revision_id: uid(91),
      value_id: uid(100),
      input_amount_krw: "9007199254740993",
      as_of_date: "2025-02-28",
    },
  });
  await page.getByRole("link", { name: "1차 기록 · 작성 중", exact: true }).click();
  await expect
    .poll(() =>
      native.calls.some((c) => c.method === "getAssetMonthRevision" && c.args.revisionNo === 1),
    )
    .toBe(true);
  expect(native.http).toEqual([]);
  expect(state.reads).toEqual([]);
  expect(state.writes).toEqual([]);
});

test("native draft ambiguous result retries the same operation key", async ({ page }) => {
  const state = await mockMonths(page);
  let created = false;
  let failure = true;
  const native = await bridge(page, ({ method }) => {
    if (method === "getAssetMonth")
      return created
        ? ok(state.record)
        : { ok: true, value: { status: 404, body: { error: { code: "MONTH_NOT_FOUND" } } } };
    if (method === "listAssetMonthRevisions") return ok({ items: [], next_cursor: null });
    if (method === "createAssetMonthDraft") {
      created = true;
      if (failure) {
        failure = false;
        return fail("NETWORK_UNAVAILABLE");
      }
      return ok({ month: "2025-02", revision_id: uid(91), revision_no: 1, version: 1 });
    }
    return fail("INVALID_REQUEST");
  });
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(page.locator(".month-value-card")).toHaveCount(3);
  const writes = native.calls.filter((c) => c.method === "createAssetMonthDraft");
  expect(writes).toHaveLength(2);
  expect(writes[0]!.args.idempotencyKey).toBeTruthy();
  expect(writes[0]!.args).toEqual(writes[1]!.args);
  expect(native.http).toEqual([]);
});

test("native comparison, trends, home and account use generated query shapes", async ({ page }) => {
  const state = await mockComparison(page);
  await page.clock.setFixedTime(new Date("2025-02-20T00:00:00Z"));
  const native = await bridge(page, ({ method, args }) => {
    if (method === "getAssetComparison") return ok(state.response(new URLSearchParams(args.query)));
    if (method === "getAssetTrends")
      return ok(state.trendResponse(new URLSearchParams(args.query)));
    if (method === "getAccount") return ok(state.finance.accounts[0]);
    return fail("INVALID_REQUEST");
  });
  await page.goto("/assets/compare?from=2025-01&to=2025-02");
  await expect(page.getByText("+1,340원", { exact: true })).toBeVisible();
  await expect(page.locator("circle.chart-point")).toHaveCount(3);
  expect(native.calls.find((c) => c.method === "getAssetComparison")!.args).toMatchObject({
    query: { from: "2025-01", to: "2025-02", limit: 200 },
  });
  await page.getByRole("link", { name: "홈", exact: true }).first().click();
  await expect(page.getByText("+1,340원", { exact: true })).toBeVisible();
  await page.goto(`/accounts/${uid(30)}`);
  await expect(page.getByText("120원", { exact: true }).first()).toBeVisible();
  expect(
    native.calls.some(
      (c) => c.method === "getAssetComparison" && c.args.query.asset_id === uid(11),
    ),
  ).toBe(true);
  expect(native.http).toEqual([]);
  expect(state.queries).toEqual([]);
});

for (const code of ["APP_LOCKED", "SESSION_EXPIRED", "NETWORK_UNAVAILABLE"])
  test(`native comparison ${code} never falls back to web`, async ({ page }) => {
    await mockComparison(page);
    const native = await bridge(page, () => fail(code));
    await page.goto("/assets/compare?from=2025-01&to=2025-02");
    if (code === "APP_LOCKED")
      await expect(page.getByRole("status")).toContainText("앱이 잠겨 있어요");
    else if (code === "SESSION_EXPIRED")
      await expect(
        page.getByRole("heading", { name: "로그인이 필요해요", exact: true }),
      ).toBeVisible();
    else await expect(page.getByRole("alert").first()).toBeVisible();
    expect(native.calls.some((c) => c.method === "getAssetComparison")).toBe(true);
    expect(native.http).toEqual([]);
    await expect(page.locator(".comparison-item")).toHaveCount(0);
  });

test("native scope synchronization, confirmation and reopening retain versions and idempotency", async ({
  page,
}) => {
  const state = await mockMonths(page);
  verifyAll(state.record!);
  state.record!.scope_stale = true;
  const native = await bridge(page, ({ method, args }) => {
    if (method === "getAssetMonth")
      return ok(args.month === "2025-01" ? state.previous : state.record);
    if (method === "listAssetMonthRevisions") return ok({ items: [], next_cursor: null });
    if (method === "listAssets") return ok({ items: state.finance.assets, next_cursor: null });
    if (["synchronizeAssetMonthScope", "confirmAssetMonth", "reopenAssetMonth"].includes(method)) {
      state.record!.version++;
      if (method === "synchronizeAssetMonthScope") state.record!.scope_stale = false;
      if (method === "confirmAssetMonth") state.record!.state = "confirmed";
      if (method === "reopenAssetMonth")
        Object.assign(state.record!, {
          state: "reopened",
          revision_id: uid(333),
          revision_no: 2,
          version: 1,
          reopened_reason: args.input.reason,
        });
      return ok({
        month: "2025-02",
        revision_id: state.record!.revision_id,
        revision_no: state.record!.revision_no,
        version: state.record!.version,
      });
    }
    return fail("INVALID_REQUEST");
  });
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "현재 자산 범위 반영 검토", exact: true }).click();
  await page
    .getByLabel("변경될 범위와 미확인으로 돌아갈 항목을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "확인한 현재 자산 범위 반영", exact: true }).click();
  await page.getByRole("button", { name: "월 확정 검토", exact: true }).click();
  await page.getByRole("button", { name: "확인하고 월 확정", exact: true }).click();
  await page.getByRole("button", { name: "정정 사유 남기고 다시 열기", exact: true }).click();
  await page.getByLabel("정정 사유", { exact: true }).fill("합성 기준일 재검토");
  await page.getByRole("button", { name: "사유를 남기고 정정 시작", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "과거 범위를 유지하는 정정본", exact: true }),
  ).toBeVisible();
  const writes = native.calls.filter((c) =>
    ["synchronizeAssetMonthScope", "confirmAssetMonth", "reopenAssetMonth"].includes(c.method),
  );
  expect(writes.map((c) => c.args.ifMatch)).toEqual(['"1"', '"2"', '"3"']);
  expect(writes.every((c) => c.args.input.revision_id === uid(91))).toBe(true);
  expect(writes[1]!.args.idempotencyKey).toBeTruthy();
  expect(writes[2]!.args.idempotencyKey).toBeTruthy();
  expect(writes[1]!.args.idempotencyKey).not.toBe(writes[2]!.args.idempotencyKey);
  expect(native.http).toEqual([]);
});

test("native cancellation discards a late response and preserves retry identity", async ({
  page,
}) => {
  const state = await mockMonths(page);
  let created = false;
  let finish: (() => void) | undefined;
  const native = await bridge(page, async ({ method }) => {
    if (method === "getAssetMonth")
      return created
        ? ok(state.record)
        : { ok: true, value: { status: 404, body: { error: { code: "MONTH_NOT_FOUND" } } } };
    if (method === "listAssetMonthRevisions") return ok({ items: [], next_cursor: null });
    if (method === "createAssetMonthDraft") {
      if (!created) {
        created = true;
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
      }
      return ok({ month: "2025-02", revision_id: uid(91), revision_no: 1, version: 1 });
    }
    return fail("INVALID_REQUEST");
  });
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect.poll(() => !!finish).toBe(true);
  await page.getByRole("button", { name: "요청 대기 중단", exact: true }).click();
  finish!();
  await expect(page.getByRole("alert")).toContainText("서버에 반영됐을 수");
  await expect(page.locator(".month-value-card")).toHaveCount(0);
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(page.locator(".month-value-card")).toHaveCount(3);
  const writes = native.calls.filter((c) => c.method === "createAssetMonthDraft");
  expect(writes).toHaveLength(2);
  expect(writes[0]!.args.idempotencyKey).toBeTruthy();
  expect(writes[0]!.args).toEqual(writes[1]!.args);
  expect(native.http).toEqual([]);
});

test("native carry-previous keeps the revision version and one key across an ambiguous retry", async ({
  page,
}) => {
  const state = await mockMonths(page);
  let failure = true;
  for (const row of state.record!.values)
    Object.assign(row, {
      input_amount_krw: null,
      owned_amount_krw: null,
      verification_state: "missing",
      origin: "manual",
      origin_revision_id: null,
    });
  state.record!.totals = total(state.record!.values);
  const confirmed = {
    month: "2025-01",
    revision_id: uid(90),
    revision_no: 1,
    version: 1,
    state: "confirmed",
    previous_revision_id: null,
    reopened_reason: null,
    confirmed_at: "2025-01-31T12:00:00Z",
    created_at: "2025-01-01T00:00:00Z",
  };
  const native = await bridge(page, ({ method, args }) => {
    if (method === "getAssetMonth") return ok(state.record);
    if (method === "getAssetMonthRevision") return ok(state.previous);
    if (method === "listAssetMonthRevisions")
      return ok({ items: args.month === "2025-01" ? [confirmed] : [], next_cursor: null });
    if (method === "carryPreviousAssetMonth") {
      if (failure) {
        failure = false;
        return fail("NETWORK_UNAVAILABLE");
      }
      Object.assign(state.record!.values[0]!, {
        input_amount_krw: "1001",
        owned_amount_krw: "501",
        verification_state: "carried_unconfirmed",
        origin: "carried",
        origin_revision_id: uid(90),
        version: 2,
      });
      state.record!.version++;
      state.record!.totals = total(state.record!.values);
      return ok({
        month: "2025-02",
        revision_id: uid(91),
        revision_no: 1,
        version: state.record!.version,
      });
    }
    return fail("INVALID_REQUEST");
  });
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "전월 확정값 불러오기 검토", exact: true }).click();
  const carry = page.getByRole("button", { name: "전월 확정값 불러오기", exact: true });
  await carry.click();
  await expect(page.getByRole("alert")).toBeVisible();
  await carry.click();
  await expect(
    page.getByText("이전 기록에서 불러온 금액이에요. 이번 달 실제 값과 기준일을 확인해 주세요.", {
      exact: true,
    }),
  ).toBeVisible();
  const writes = native.calls.filter((c) => c.method === "carryPreviousAssetMonth");
  expect(writes).toHaveLength(2);
  expect(writes[1]!.args).toEqual(writes[0]!.args);
  expect(writes[0]!.args).toMatchObject({
    month: "2025-02",
    ifMatch: '"1"',
    input: { revision_id: uid(91) },
  });
  expect(writes[0]!.args.idempotencyKey).toBeTruthy();
  expect(native.http).toEqual([]);
});

test("native batch confirmation and save-next preserve versions and unchanged values", async ({
  page,
}) => {
  const state = await mockMonths(page);
  const source = state.record!.values[0]!;
  state.record!.values = [
    source,
    { ...source, id: uid(510), asset_id: uid(610), name: "합성 다음 자산" },
    { ...source, id: uid(511), asset_id: uid(611), name: "합성 마지막 자산" },
  ];
  const native = await bridge(page, ({ method, args }) => {
    if (method === "getAssetMonth") return ok(state.record);
    if (method === "listAssetMonthRevisions") return ok({ items: [], next_cursor: null });
    if (method === "updateAssetMonthValue") {
      const row = state.record!.values.find((row) => row.asset_id === args.assetId)!;
      expect(args.ifMatch).toBe(`"${row.version}"`);
      expect(args.input.revision_id).toBe(state.record!.revision_id);
      expect(args.input.value_id).toBe(row.id);
      if (!args.input.unchanged) row.input_amount_krw = args.input.input_amount_krw;
      row.verification_state = "verified";
      row.as_of_date = args.input.as_of_date;
      row.version++;
      state.record!.version++;
      state.record!.totals = total(state.record!.values);
      return ok({
        value: row,
        revision_version: state.record!.version,
        totals: state.record!.totals,
      });
    }
    return fail("INVALID_REQUEST");
  });
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "선택한 항목 변동 없음 확인", exact: true }).click();
  const panel = page.getByRole("region", { name: "선택한 항목 변동 없음", exact: true });
  await panel.getByLabel("합성 공동 주택 선택", { exact: true }).check();
  await panel.getByLabel("공통 실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await panel
    .getByLabel("선택한 금액이 기준일에도 같음을 직접 확인했어요.", { exact: true })
    .check();
  await panel.getByRole("button", { name: "선택한 금액 확인 저장", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("1 / 1개 저장 완료");
  const batch = native.calls.find((call) => call.method === "updateAssetMonthValue")!;
  expect(batch.args.input).toMatchObject({ unchanged: true, as_of_date: "2025-02-28" });
  expect(batch.args.input).not.toHaveProperty("input_amount_krw");
  await panel.getByRole("button", { name: "결과 확인하고 닫기" }).click();
  await page.getByRole("button", { name: "미확인 항목 확인하기", exact: true }).click();
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "저장 후 다음 미확인 항목", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 마지막 자산 금액 확인", exact: true }),
  ).toBeVisible();
  expect(native.calls.filter((call) => call.method === "updateAssetMonthValue")).toHaveLength(2);
  expect(native.http).toEqual([]);
  expect(state.writes).toEqual([]);
});
