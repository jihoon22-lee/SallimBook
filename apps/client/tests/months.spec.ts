import { expect, test } from "@playwright/test";
import fixtures from "../../../packages/test-fixtures/catalog.json" with { type: "json" };
import {
  carriedNote,
  carryCandidates,
  formatKrw,
  monthEnd,
  ownedPreview,
  parseKrw,
  previousMonth,
  valueInput,
} from "../src/features/assets/months/model";
import type { MonthRecord, MonthValue } from "../src/features/assets/months/model";
import { mockMonths, total, verifyAll } from "./support/months";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });

test("shared fixture money, HALF_UP and calendar examples remain exact", () => {
  for (const row of fixtures.edge_cases.household_share_rounding)
    expect(ownedPreview(row.amount_krw, row.share, row.basis as "whole" | "owned")).toBe(
      row.owned_krw,
    );
  expect(parseKrw("9007199254740993")).toBe("9007199254740993");
  expect(parseKrw("99999999999999999999")).toBe("99999999999999999999");
  for (const amount of ["", "-1", "1.1", "1e3", "1,000", "100000000000000000000"])
    expect(parseKrw(amount)).toBeNull();
  expect(ownedPreview("99999999999999999999", "1", "whole")).toBe("99999999999999999999");
  expect(ownedPreview("1", "0.499999999999999999", "whole")).toBe("0");
  expect(formatKrw(null)).toBe("미입력");
  expect(formatKrw("0")).toBe("0원");
  expect(formatKrw("9007199254740993")).toBe("9,007,199,254,740,993원");
  expect(monthEnd("2024-02")).toBe("2024-02-29");
  expect(monthEnd("2100-02")).toBe("2100-02-28");
  expect(previousMonth("0001-01")).toBeNull();
  expect(previousMonth("2025-01")).toBe("2024-12");
});

test("missing, carried and explicit zero are distinct and unchanged requires a new date", async ({
  page,
}) => {
  const state = await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  await expect(page.getByText("불러온 값 · 미확인", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "월 확정 검토", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "합성 공동 주택 금액 확인", exact: true }).click();
  await page.getByLabel("입력 방식", { exact: true }).selectOption("unchanged");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(page.getByText("확인한 금액과 기준일을 저장했어요.", { exact: true })).toBeVisible();
  expect(state.writes[0]?.body.unchanged).toBe(true);
  expect(Object.hasOwn(state.writes[0]!.body, "input_amount_krw")).toBe(false);
  await page.getByRole("button", { name: "합성 종료 대출 금액 확인", exact: true }).click();
  await page.getByLabel("확인 금액 (원)", { exact: true }).fill("0");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(page.getByRole("button", { name: "월 확정 검토", exact: true })).toBeEnabled();
  expect(state.writes.at(-1)?.body.input_amount_krw).toBe("0");
  await page.getByRole("button", { name: "합성 종료 대출 금액 확인", exact: true }).click();
  await page.getByLabel("입력 방식", { exact: true }).selectOption("missing");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(page.getByRole("button", { name: "월 확정 검토", exact: true })).toBeDisabled();
  expect(state.writes.at(-1)?.body.input_amount_krw).toBeNull();
  expect(state.writes.at(-1)?.body.as_of_date).toBeNull();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("server totals and shared T-01 data are displayed without reapplying ownership or inventing growth", async ({
  page,
}) => {
  const state = await mockMonths(page);
  const vector = fixtures.vectors.find((value) => value.id === "T-01")!;
  const inputs = vector.inputs as { assets_krw: string; liabilities_krw: string };
  const expected = vector.expected as { net_assets_krw: string };
  state.record!.values[0]!.owned_amount_krw = inputs.assets_krw;
  state.record!.values[2]!.owned_amount_krw = inputs.liabilities_krw;
  verifyAll(state.record!);
  state.previous = null;
  await page.goto("/assets/months/2025-02");
  const summary = page.getByRole("region", { name: "이번 기록의 합계", exact: true });
  await expect(summary).toContainText(formatKrw(expected.net_assets_krw));
  await page.getByRole("button", { name: "월 확정 검토", exact: true }).click();
  await expect(
    page.getByText("전월 확정본이 없어 비교할 수 없어요.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("0%", { exact: true })).toHaveCount(0);
});

test("draft ambiguous response uses the same idempotency key on explicit retry without blind writes", async ({
  page,
}) => {
  const state = await mockMonths(page);
  state.record = null;
  state.writeFailure = "after";
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("결과를 확인하지 못했어요");
  expect(state.writes).toHaveLength(1);
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "이 기록에 포함된 자산·부채", exact: true }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(2);
  expect(Boolean(state.writes[0]?.key) && state.writes[0]?.key === state.writes[1]?.key).toBe(true);
  expect(
    state.record!.values.filter((row) => row.verification_state === "carried_unconfirmed"),
  ).toHaveLength(2);
  expect(state.record!.values.every((row) => row.as_of_date === null)).toBe(true);
});

test("a changed draft payload gets a new key and never converts missing to zero", async ({
  page,
}) => {
  const state = await mockMonths(page);
  state.record = null;
  state.writeFailure = "before";
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByLabel("전월 마지막 확정본의 금액 불러오기", { exact: true }).uncheck();
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "이 기록에 포함된 자산·부채", exact: true }),
  ).toBeVisible();
  expect(state.writes[0]?.key !== state.writes[1]?.key).toBe(true);
  expect(
    state.record!.values.every(
      (row) => row.input_amount_krw === null && row.verification_state === "missing",
    ),
  ).toBe(true);
});

test("cancelled draft response preserves its operation key while the server may have committed", async ({
  page,
}) => {
  const state = await mockMonths(page);
  state.record = null;
  state.writeDelay = 400;
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  await page.getByRole("button", { name: "요청 대기 중단", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("서버에 반영됐을 수");
  state.writeDelay = 0;
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "이 기록에 포함된 자산·부채", exact: true }),
  ).toBeVisible();
  expect(state.writes[0]?.key === state.writes[1]?.key).toBe(true);
});

test("row conflict keeps typed amount and requires comparing the latest observation", async ({
  page,
}) => {
  const state = await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "합성 공동 주택 금액 확인", exact: true }).click();
  await page.getByLabel("확인 금액 (원)", { exact: true }).fill("999");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-20");
  Object.assign(state.record!.values[0]!, {
    input_amount_krw: "2000",
    owned_amount_krw: "1000",
    as_of_date: "2025-02-21",
    verification_state: "verified",
    version: 2,
  });
  state.record!.version++;
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("작성한 내용은 유지");
  await expect(page.getByLabel("확인 금액 (원)", { exact: true })).toHaveValue("999");
  await page.getByRole("button", { name: "최신 월 기록과 비교", exact: true }).click();
  await expect(page.getByRole("cell", { name: "2,000원", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "비교한 내 입력 유지", exact: true }).click();
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(page.getByText("확인한 금액과 기준일을 저장했어요.", { exact: true })).toBeVisible();
  expect(state.writes.map((write) => write.version)).toEqual(['"1"', '"2"']);
  expect(state.record!.values[0]!.input_amount_krw).toBe("999");
});

for (const conflict of ["value", "revision"] as const)
  test(`${conflict} identity replacement cannot accept an old version-1 draft`, async ({
    page,
  }) => {
    const state = await mockMonths(page);
    await page.goto("/assets/months/2025-02");
    await page.getByRole("button", { name: "합성 공동 주택 금액 확인", exact: true }).click();
    await page.getByLabel("확인 금액 (원)", { exact: true }).fill("9007199254740993");
    await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
    state.record!.values[0]!.id = uid(880);
    state.record!.values[0]!.amount_basis = "owned";
    state.record!.values[0]!.household_share = "0.75";
    if (conflict === "revision") {
      state.record!.revision_id = uid(881);
      state.record!.revision_no = 2;
      state.record!.state = "reopened";
    }
    await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByLabel("확인 금액 (원)", { exact: true })).toHaveValue(
      "9007199254740993",
    );
    await page.getByRole("button", { name: "최신 월 기록과 비교", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "비교한 내 입력 유지", exact: true }),
    ).toBeDisabled();
    await page
      .getByLabel(
        "이름·지분·금액 기준 등 변경된 범위를 확인했어요. 내 금액이 최신 기준에도 맞아요.",
        { exact: true },
      )
      .check();
    await page.getByRole("button", { name: "비교한 내 입력 유지", exact: true }).click();
    await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
    await expect(
      page.getByText("확인한 금액과 기준일을 저장했어요.", { exact: true }),
    ).toBeVisible();
    expect(state.writes[1]?.body.value_id).toBe(uid(880));
    expect(state.writes[1]?.body.revision_id).toBe(state.record!.revision_id);
    expect(state.writes[1]?.body.input_amount_krw).toBe("9007199254740993");
    expect(state.writes.map((item) => item.version)).toEqual(['"1"', '"1"']);
  });

test("confirmation requires date and scope acknowledgements and persists a single request identity", async ({
  page,
}) => {
  const state = await mockMonths(page);
  verifyAll(state.record!, "2025-02-20");
  state.record!.values[0]!.household_share = "0.75";
  state.scopeAckRequired = true;
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "월 확정 검토", exact: true }).click();
  await expect(page.getByRole("button", { name: "확인하고 월 확정", exact: true })).toBeDisabled();
  await expect(page.getByText("가계 지분 변경:", { exact: false })).toBeVisible();
  await page.getByLabel("월말과 다른 기준일을 확인했어요.", { exact: true }).check();
  await page.getByLabel("전월과 달라진 포함 항목·가계 지분을 확인했어요.", { exact: true }).check();
  state.writeFailure = "after";
  await page.getByRole("button", { name: "확인하고 월 확정", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  expect(state.writes).toHaveLength(1);
  await page.getByRole("button", { name: "확인하고 월 확정", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "정정 사유 남기고 다시 열기", exact: true }),
  ).toBeVisible();
  expect(state.writes[0]?.key === state.writes[1]?.key).toBe(true);
  expect(state.writes[1]?.body).toEqual({
    revision_id: uid(91),
    acknowledge_non_month_end_dates: true,
    acknowledge_scope_change: true,
  });
});

test("reopening preserves historical scope and reason, and prior revisions are read-only", async ({
  page,
}) => {
  const state = await mockMonths(page);
  verifyAll(state.record!);
  state.record!.state = "confirmed";
  state.record!.confirmed_at = "2025-02-28T12:00:00Z";
  state.finance.assets[0]!.household_share = "1";
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "정정 사유 남기고 다시 열기", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "사유를 남기고 정정 시작", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("정정 사유", { exact: true }).fill("합성 평가액 확인 오류 정정");
  state.writeFailure = "after";
  await page.getByRole("button", { name: "사유를 남기고 정정 시작", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("정정 사유", { exact: true })).toHaveValue(
    "합성 평가액 확인 오류 정정",
  );
  await page.getByRole("button", { name: "사유를 남기고 정정 시작", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "과거 범위를 유지하는 정정본", exact: true }),
  ).toBeVisible();
  expect(state.writes[0]?.key === state.writes[1]?.key).toBe(true);
  expect(state.revisions).toHaveLength(1);
  expect(state.record!.values[0]!.household_share).toBe("0.5");
  await page.getByRole("button", { name: "합성 공동 주택 금액 확인", exact: true }).click();
  await page.getByLabel("확인 금액 (원)", { exact: true }).fill("3000");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await expect(page.getByText("확인한 금액과 기준일을 저장했어요.", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "1차 기록 · 확정", exact: true }).click();
  await expect(page.getByRole("heading", { name: "1차 기록 조회", exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "합성 공동 주택 금액 확인", exact: true }),
  ).toHaveCount(0);
  expect(state.revisions[0]!.values[0]!.input_amount_krw).toBe("1001");
  expect(state.record!.values[0]!.input_amount_krw).toBe("3000");
  await page.getByRole("link", { name: "현재 월 기록으로 돌아가기", exact: true }).click();
  await expect(
    page.getByText("정정 사유: 합성 평가액 확인 오류 정정", { exact: true }).first(),
  ).toBeVisible();
});

test("explicit scope synchronization clears amounts when whole and owned bases differ", async ({
  page,
}) => {
  const state = await mockMonths(page);
  state.record!.scope_stale = true;
  state.finance.assets[0]!.amount_basis = "owned";
  await page.goto("/assets/months/2025-02");
  await expect(page.getByRole("button", { name: "월 확정 검토", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "현재 자산 범위 반영 검토", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "확인한 현재 자산 범위 반영", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("변경될 범위와 미확인으로 돌아갈 항목을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "확인한 현재 자산 범위 반영", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "현재 자산 범위 반영 전 확인", exact: true }),
  ).toHaveCount(0);
  expect(state.record!.values[0]!.input_amount_krw).toBeNull();
  expect(state.record!.values[0]!.verification_state).toBe("missing");
  expect(state.writes[0]?.operation).toBe("sync-scope");
  expect(state.writes[0]?.body.revision_id).toBe(uid(91));
  expect(state.record!.values[0]!.origin).toBe("manual");
  expect(state.record!.values[0]!.origin_revision_id).toBeNull();
  await expect(page.getByText("직접 확인을 마쳤어요", { exact: false })).toHaveCount(0);
});

test("carried notes follow the verification state, including legacy cleared carried rows", () => {
  const row = (
    verification_state: MonthValue["verification_state"],
    origin: MonthValue["origin"],
  ) => ({ verification_state, origin }) as MonthValue;
  expect(carriedNote(row("missing", "carried"))).toBeNull();
  expect(carriedNote(row("carried_unconfirmed", "carried"))).toContain(
    "이번 달 실제 값과 기준일을 확인해 주세요",
  );
  expect(carriedNote(row("verified", "carried"))).toContain("직접 확인을 마쳤어요");
  expect(carriedNote(row("verified", "manual"))).toBeNull();
});

test("pagination refuses mixed revisions then loads one complete snapshot on explicit retry", async ({
  page,
}) => {
  const state = await mockMonths(page);
  state.pageSize = 1;
  state.mutateBetweenPages = true;
  await page.goto("/assets/months/2025-02");
  await expect(page.getByRole("alert")).toContainText("조회 도중 기록이 바뀌었어요");
  await expect(page.locator(".month-value-card")).toHaveCount(0);
  await page.getByRole("button", { name: "월 기록 다시 확인", exact: true }).click();
  await expect(page.locator(".month-value-card")).toHaveCount(3);
  expect(state.writes).toHaveLength(0);
});

test("invalid dates and invalid months fail client validation", async ({ page }) => {
  const state = await mockMonths(page);
  const row = state.record!.values[0]!;
  for (const date of ["2025-02-30", "2025-03-01", "9999-02-01"])
    expect(
      valueInput(uid(91), row, { mode: "amount", amount: "0", asOf: date, reason: "" }, "2025-02"),
    ).toBeNull();
  await page.goto("/assets/months/2025-13");
  await expect(
    page.getByRole("heading", { name: "월을 확인해 주세요", exact: true }),
  ).toBeVisible();
  expect(state.reads).toHaveLength(0);
});

test("a future month offers no draft and a server future-month rejection is explained", async ({
  page,
}) => {
  const state = await mockMonths(page);
  state.record = null;
  await page.clock.setFixedTime(new Date("2025-01-31T14:59:00Z"));
  await page.goto("/assets/months/2025-02");
  await expect(
    page.getByRole("heading", { name: "아직 시작하지 않은 달이에요", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "월 작성본 만들기", exact: true })).toHaveCount(0);
  await page.clock.setFixedTime(new Date("2025-01-31T15:00:00Z"));
  await page.route("**/api/v1/asset-months/2025-02/draft", (route) =>
    route.fulfill({
      status: 422,
      json: { error: { code: "MONTH_IN_FUTURE", message: "synthetic", request_id: uid(99) } },
    }),
  );
  await page.reload();
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("아직 시작하지 않은 달은 기록할 수 없어요");
  expect(state.writes).toHaveLength(0);
});

test("carry candidates mirror the server rule for untouched missing rows", () => {
  const untouched = {
    verification_state: "missing",
    origin: "manual",
    origin_revision_id: null,
    as_of_date: null,
    change_reason: null,
    input_amount_krw: null,
  };
  const prior = {
    state: "confirmed",
    values: [
      ["a", "whole", "100"],
      ["b", "whole", "200"],
      ["c", "whole", "300"],
      ["d", "whole", "400"],
      ["e", "owned", null],
    ].map(([asset_id, amount_basis, input_amount_krw]) => ({
      asset_id,
      amount_basis,
      input_amount_krw,
    })),
  } as unknown as MonthRecord;
  const record = {
    values: [
      { ...untouched, asset_id: "a", amount_basis: "whole" },
      { ...untouched, asset_id: "b", amount_basis: "whole", change_reason: "합성 확인 불가" },
      { ...untouched, asset_id: "c", amount_basis: "owned" },
      {
        ...untouched,
        asset_id: "d",
        amount_basis: "whole",
        verification_state: "verified",
        input_amount_krw: "450",
        as_of_date: "2026-02-28",
      },
      { ...untouched, asset_id: "e", amount_basis: "owned" },
      { ...untouched, asset_id: "f", amount_basis: "whole" },
    ],
  } as unknown as MonthRecord;
  expect(
    carryCandidates(record, prior).map(({ row, source }) => [
      row.asset_id,
      source.input_amount_krw,
    ]),
  ).toEqual([["a", "100"]]);
  expect(carryCandidates(record, { ...prior, state: "reopened" })).toEqual([]);
  expect(carryCandidates(record, null)).toEqual([]);
});

test("starting a month after an unconfirmed previous month needs an explicit acknowledgment", async ({
  page,
}) => {
  const state = await mockMonths(page);
  state.record = null;
  Object.assign(state.previous!, {
    state: "draft",
    confirmed_at: null,
    confirmed_by_member_id: null,
  });
  await page.goto("/assets/months/2025-02");
  await expect(
    page.getByRole("heading", { name: "전월 기록이 아직 확정되지 않았어요", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "전월 먼저 확정하기", exact: true })).toHaveAttribute(
    "href",
    "/assets/months/2025-01",
  );
  const create = page.getByRole("button", { name: "월 작성본 만들기", exact: true });
  await expect(create).toBeDisabled();
  await page.getByLabel("전월 확정값 없이 시작하는 것을 확인했어요.", { exact: true }).check();
  await create.click();
  await expect(
    page.getByRole("button", { name: "전월 확정값 불러오기 검토", exact: true }),
  ).toBeVisible();
  expect(state.writes.map((write) => write.operation)).toEqual(["draft"]);
  expect(
    state.record!.values.every((row) => row.input_amount_krw === null && row.origin === "manual"),
  ).toBe(true);
});

test("carry-previous fills only untouched missing rows and reuses its key after an ambiguous failure", async ({
  page,
}) => {
  const state = await mockMonths(page);
  for (const row of state.record!.values)
    Object.assign(row, {
      input_amount_krw: null,
      owned_amount_krw: null,
      verification_state: "missing",
      origin: "manual",
      origin_revision_id: null,
    });
  state.record!.values[2]!.change_reason = "합성 확인 불가";
  state.record!.totals = total(state.record!.values);
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "전월 확정값 불러오기 검토", exact: true }).click();
  const panel = page.getByRole("region", { name: "전월 확정값 불러오기", exact: true });
  await expect(panel.getByRole("listitem")).toHaveText([/^합성 공동 주택: 1,001원/]);
  state.writeFailure = "after";
  await panel.getByRole("button", { name: "전월 확정값 불러오기", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("결과를 확인하지 못했어요");
  await panel.getByRole("button", { name: "전월 확정값 불러오기", exact: true }).click();
  await expect(
    page.getByText("이전 기록에서 불러온 금액이에요. 이번 달 실제 값과 기준일을 확인해 주세요.", {
      exact: true,
    }),
  ).toHaveCount(1);
  const carries = state.writes.filter((write) => write.operation === "carry-previous");
  expect(carries).toHaveLength(2);
  expect(carries[0]!.key).toBeTruthy();
  expect(carries[1]!.key).toBe(carries[0]!.key);
  expect(carries[0]!.version).toBe('"1"');
  expect(state.record!.values[0]).toMatchObject({
    input_amount_krw: "1001",
    verification_state: "carried_unconfirmed",
    origin: "carried",
    origin_revision_id: uid(90),
  });
  expect(state.record!.values[2]).toMatchObject({
    input_amount_krw: null,
    change_reason: "합성 확인 불가",
  });
});
