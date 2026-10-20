import { openDisclosure } from "./support/task-ui";
import { expect, test } from "@playwright/test";
import catalog from "../../../packages/test-fixtures/catalog.json" with { type: "json" };
import { mockHomecare, applianceRow, consumableRow, linkRow } from "./support/homecare";
import { uid } from "./support/finance";
const vectors = catalog.vectors;
const appliance = `/appliances/${uid(100)}`,
  stock = `/consumables/${uid(200)}`,
  device = `/appliance-consumables/${uid(300)}`;
const saveReplacement = async (page: import("@playwright/test").Page) => {
  await page.getByLabel("실제 교체일·사용 수량과 다음 확인일 적용 방식을 확인했어요").check();
  await page.getByRole("button", { name: "실제 교체·재고 사용 저장", exact: true }).click();
};
test("appliance creation preserves missing versus zero and warranty metadata without asset writes", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  await page.goto("/appliances/new");
  await page.getByLabel("가전 이름", { exact: true }).fill("합성 구매 제품");
  await page.getByLabel("제조사", { exact: true }).fill("합성 회사");
  await page.getByLabel("설치 장소").fill("작은방");
  await page.getByLabel("구매일", { exact: true }).fill("2025-01-01");
  await page.getByLabel("구매 금액 (원)").fill("0");
  await page.getByLabel("보증기한", { exact: true }).fill("2099-01-01");
  await page.getByRole("button", { name: "가전 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 구매 제품" })).toBeVisible();
  await expect(page.getByText("2099.01.01 · 보증기간 안")).toBeVisible();
  const write = state.writes.at(-1)!;
  expect(write.body.purchase_price_krw).toBe("0");
  expect(Object.keys(write.body)).not.toContain("asset_id");
  expect(state.cashflow.finance.creates).toHaveLength(0);
});
test("appliance conflict retains edited location and current note then ending preserves its linked history", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.conflict = "appliances";
  await page.goto(`${appliance}/edit`);
  await page.getByLabel("설치 장소").fill("합성 서재");
  await page.getByRole("button", { name: "가전 수정 저장" }).click();
  await expect(page.getByLabel("설치 장소")).toHaveValue("합성 서재");
  await page.getByRole("button", { name: "현재 가전·소모품 내용 비교" }).click();
  await page.getByRole("button", { name: "비교한 수정 유지" }).click();
  await expect(page.getByLabel("관리·수리 메모")).toHaveValue("배우자가 작성한 합성 메모");
  await page.getByRole("button", { name: "가전 수정 저장" }).click();
  expect(state.writes.at(-1)!.body).toEqual({ location: "합성 서재" });
  await page.goto(`${appliance}/edit`);
  await page.getByLabel("가전 사용 종료일").fill("2025-03-01");
  await expect(page.getByRole("button", { name: "가전 수정 저장" })).toBeDisabled();
  await page
    .getByLabel("종료 후 새 교체 기록이 제한되고 오늘 관리 목록에서 제외됨을 확인했어요")
    .check();
  await page.getByRole("button", { name: "가전 수정 저장" }).click();
  await expect(page.getByText("사용 종료 · 2025.03.01")).toBeVisible();
  expect(state.links).toHaveLength(2);
  expect(state.replacements).toHaveLength(1);
  await page.goto("/appliances?status=ended");
  await expect(page.getByRole("link", { name: "합성 거실 청정기", exact: true })).toBeVisible();
});
test("SKU duplicate can be corrected without creating a second shared stock and empty price stays unknown", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  await page.goto("/consumables/new");
  await page.getByLabel("소모품 이름", { exact: true }).fill("합성 새 필터");
  await page.getByLabel("SKU·규격·모델").fill("SYNTHETIC-FILTER");
  await page.getByRole("button", { name: "소모품 등록", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("이미 등록한 규격");
  await page.getByLabel("SKU·규격·모델").fill("SYNTHETIC-NEW");
  await page.getByLabel("재고 부족 임계 수량").fill("2");
  await page.getByRole("button", { name: "소모품 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 새 필터" })).toBeVisible();
  expect(state.consumables.at(-1)!.stock_quantity).toBe(0);
  expect(state.writes.at(-1)!.body).not.toHaveProperty("stock_quantity");
  await page.goto(`${appliance}/edit`);
  await page.getByLabel("관리·수리 메모").fill("합성 수정");
  await page.getByRole("button", { name: "가전 수정 저장" }).click();
  expect(state.appliances[0]!.purchase_price_krw).toBeNull();
});
test("metadata uncertain create requires checking list before another attempt", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.failure = "after";
  await page.goto("/appliances/new");
  await page.getByLabel("가전 이름", { exact: true }).fill("합성 응답 유실 제품");
  await page.getByRole("button", { name: "가전 등록", exact: true }).click();
  await expect(page.getByText("등록됐을 수 있어요.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "가전 등록", exact: true })).toBeDisabled();
  expect(state.appliances.filter((a) => a.name === "합성 응답 유실 제품")).toHaveLength(1);
  await page.getByRole("link", { name: "현재 목록", exact: true }).click();
  await expect(page.getByRole("link", { name: "합성 응답 유실 제품", exact: true })).toBeVisible();
});
test("consumable conflict merges threshold only while unit with existing stock history is rejected", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.conflict = "consumables";
  await page.goto(`${stock}/edit`);
  await page.getByLabel("재고 부족 임계 수량").fill("4");
  await page.getByRole("button", { name: "소모품 수정 저장" }).click();
  await page.getByRole("button", { name: "현재 가전·소모품 내용 비교" }).click();
  await page.getByRole("button", { name: "비교한 수정 유지" }).click();
  await page.getByRole("button", { name: "소모품 수정 저장" }).click();
  expect(state.writes.at(-1)!.body).toEqual({ low_stock_threshold: 4 });
  await page.goto(`${stock}/edit`);
  await page.getByLabel("재고 단위").fill("상자");
  await page.getByRole("button", { name: "소모품 수정 저장" }).click();
  await expect(page.getByRole("alert")).toContainText("단위를 바꿀 수 없어요");
  expect(state.consumables[0]!.unit).toBe("개");
});
test("paged compatible choices create a separate device cycle on one shared SKU", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.appliances.push(applianceRow(102, { name: "합성 세 번째 기기" }));
  state.consumables.unshift(
    consumableRow(199, { name: "합성 다른 소모품", sku_or_model: "SYNTHETIC-OTHER" }),
  );
  state.pageSize = 1;
  await page.goto(`/appliances/${uid(102)}`);
  await page.getByRole("button", { name: "호환 소모품·기기 연결" }).click();
  await expect(page.getByLabel("연결할 소모품").locator("option")).toHaveCount(3);
  await page.getByLabel("연결할 소모품").selectOption(uid(200));
  await page
    .getByRole("combobox", { name: "기기별 확인 주기", exact: true })
    .selectOption("months");
  await page.getByLabel("주기 간격").fill("3");
  await page.getByLabel("교체당 사용 수량", { exact: true }).fill("2");
  await page.getByRole("button", { name: "기기별 소모품 설정 저장" }).click();
  await openDisclosure(page, "기기별 주기와 재고 상세");
  await expect(page.getByText("교체 기준일 미확인", { exact: true })).toBeVisible();
  expect(state.links.at(-1)!).toMatchObject({
    consumable_id: uid(200),
    interval_count: 3,
    quantity_per_replacement: 2,
  });
  expect(state.consumables.find((s) => s.id === uid(200))!.stock_quantity).toBe(3);
  expect(state.reads.some((r) => r.path === "/api/v1/consumables" && r.query.has("cursor"))).toBe(
    true,
  );
});
test("existing device connection can stop and resume without duplicating pair or deleting history", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  await page.goto(device);
  await page.getByRole("button", { name: "기기별 주기·연결 수정" }).click();
  await page.getByLabel("이 기기에서 소모품 연결 사용").uncheck();
  await page.getByRole("button", { name: "기기별 소모품 설정 저장" }).click();
  await expect(page.getByText(/오늘 기준.*연결 중지/)).toBeVisible();
  await expect(page.getByRole("link", { name: "교체 기록", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "기기별 주기·연결 수정" }).click();
  await page.getByLabel("이 기기에서 소모품 연결 사용").check();
  await page.getByRole("button", { name: "기기별 소모품 설정 저장" }).click();
  await expect(page.getByRole("link", { name: "교체 기록", exact: true })).toBeVisible();
  expect(state.links).toHaveLength(2);
  expect(state.replacements).toHaveLength(1);
});
test("clearing a device override is explicit and conflict retains only edited interval", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.links[0]!.next_check_override = "2027-01-01";
  state.conflict = "appliance-consumables";
  await page.goto(device);
  await page.getByRole("button", { name: "기기별 주기·연결 수정" }).click();
  await page.getByLabel("주기 간격").fill("2");
  await page.getByRole("button", { name: "기기별 소모품 설정 저장" }).click();
  await page.getByRole("button", { name: "현재 가전·소모품 내용 비교" }).click();
  await page.getByRole("button", { name: "비교한 수정 유지" }).click();
  await page.getByLabel("다음 확인일 직접 지정").fill("");
  await expect(page.getByRole("button", { name: "기기별 소모품 설정 저장" })).toBeDisabled();
  await page.getByLabel("직접 지정한 다음 확인일을 해제하고 교체 기록 기준을 적용해요").check();
  await page.getByRole("button", { name: "기기별 소모품 설정 저장" }).click();
  await expect(page.getByText("2025.03.31 · 교체 기록 기준")).toBeVisible();
  expect(state.writes.at(-1)!.body).toEqual({ interval_count: 2, next_check_override: null });
  expect(state.links[0]!.note).toBe("배우자가 작성한 합성 메모");
});
test("T20 receipt does not replace and one actual replacement consumes one shared unit", async ({
  page,
}) => {
  const t20 = vectors.find((v) => v.id === "T-20")! as any;
  const state = await mockHomecare(page);
  state.consumables[0]!.stock_quantity = t20.inputs.initial_stock;
  state.replacements[0]!.replaced_on = t20.inputs.last_replaced_on;
  await page.goto(`${stock}/stock/new`);
  await page.getByLabel("입고·반품 수량").fill(String(t20.inputs.movements[0].quantity_delta));
  await page.getByLabel("재고 실제 날짜").fill(t20.inputs.movements[0].occurred_on);
  await page.getByRole("button", { name: "재고 변화 저장" }).click();
  await expect(page.getByText("+3 개", { exact: false })).toBeVisible();
  expect(state.consumables[0]!.stock_quantity).toBe(t20.expected.stock_after_receipt);
  expect(state.linkView(state.links[0]!).last_replaced_on).toBe(
    t20.expected.last_replaced_after_receipt,
  );
  await page.goto(`${device}/replace`);
  await page.getByLabel("실제 교체일", { exact: true }).fill(t20.inputs.movements[1].occurred_on);
  await saveReplacement(page);
  await expect(page.getByText("2025.03.02", { exact: true })).toBeVisible();
  expect(state.consumables[0]!.stock_quantity).toBe(t20.expected.final_stock);
  expect(state.linkView(state.links[0]!).last_replaced_on).toBe(
    t20.expected.last_replaced_after_replacement,
  );
  expect(state.writes.at(-1)!.version).toBe('"8"');
  expect(state.writes.at(-1)!.body.link_version).toBe(3);
});
test("stock adjustment requires signed delta and reason while receipt unit price zero remains explicit", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  await page.goto(`${stock}/stock/new`);
  await page.getByLabel("재고 기록 종류").selectOption("adjustment");
  await page.getByLabel("재고 조정 수량 (증가 양수·감소 음수)").fill("-2");
  await expect(page.getByRole("button", { name: "재고 변화 저장" })).toBeDisabled();
  await page.getByLabel("재고 기록 사유 (필수)").fill("합성 실물 재고 확인");
  await page.getByLabel("단위당 참고 가격 (원)").fill("0");
  await page.getByRole("button", { name: "재고 변화 저장" }).click();
  await expect(page.getByText("재고 조정 · -2 개")).toBeVisible();
  expect(state.writes.at(-1)!.body).toMatchObject({
    quantity_delta: -2,
    reason: "합성 실물 재고 확인",
    unit_cost_krw: "0",
  });
  expect(state.consumables[0]!.stock_quantity).toBe(1);
  expect(state.replacements).toHaveLength(1);
});
test("stock mutation response loss retries the same immutable operation exactly once", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.failure = "after";
  await page.goto(`${stock}/stock/new`);
  await page.getByLabel("입고·반품 수량").fill("3");
  await page.getByRole("button", { name: "재고 변화 저장" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  const key = state.writes.at(-1)!.key;
  await page.getByRole("button", { name: "재고 변화 저장" }).click();
  await expect(page.getByRole("heading", { name: "합성 공용 필터 재고 원본" })).toBeVisible();
  expect(state.writes.at(-1)!.key).toBe(key);
  expect(state.consumables[0]!.stock_quantity).toBe(6);
  expect(state.movements).toHaveLength(3);
  expect(
    state.reads.filter((r) => r.path === `/api/v1/consumables/${uid(200)}`).length,
  ).toBeGreaterThan(1);
});
test("replacement requires explicit override choice and missed cycles never multiply consumption", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.links[0]!.next_check_override = "2025-02-01";
  await page.goto(`${device}/replace`);
  await page.getByLabel("실제 교체일", { exact: true }).fill("2025-03-02");
  await page.getByLabel("실제 교체일·사용 수량과 다음 확인일 적용 방식을 확인했어요").check();
  await expect(page.getByRole("button", { name: "실제 교체·재고 사용 저장" })).toBeDisabled();
  await page.getByLabel("직접 지정한 다음 확인일 처리").selectOption("keep");
  await saveReplacement(page);
  await expect(page.getByText("2025.02.01 · 직접 지정")).toBeVisible();
  expect(state.consumables[0]!.stock_quantity).toBe(2);
  await page.goto(`${device}/replace`);
  await page.getByLabel("직접 지정한 다음 확인일 처리").selectOption("clear");
  await page.getByLabel("실제 교체일", { exact: true }).fill("2025-03-03");
  await saveReplacement(page);
  await expect(page.getByText("2025.04.03 · 교체 기록 기준")).toBeVisible();
  expect(state.consumables[0]!.stock_quantity).toBe(1);
  expect(state.writes.at(-1)!.body.clear_next_check_override).toBe(true);
  expect(state.movements.filter((m) => m.kind === "replacement")).toHaveLength(3);
});
test("replacement link conflict keeps typed date and amount and requires reviewing both current versions", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.conflict = "link";
  await page.goto(`${device}/replace`);
  await page.getByLabel("실제 교체일", { exact: true }).fill("2025-03-02");
  await page.getByLabel("실제 사용 수량").fill("2");
  await saveReplacement(page);
  await expect(page.getByLabel("실제 사용 수량")).toHaveValue("2");
  await page.getByRole("button", { name: "현재 공용 재고·기기 설정 비교" }).click();
  await page.getByRole("button", { name: "교체 입력 유지하고 현재 상태 적용" }).click();
  await expect(
    page.getByLabel("실제 교체일·사용 수량과 다음 확인일 적용 방식을 확인했어요"),
  ).not.toBeChecked();
  await saveReplacement(page);
  await expect(page.getByText("2025.03.02", { exact: true })).toBeVisible();
  expect(state.writes.at(-1)!.body.link_version).toBe(4);
  expect(state.writes.at(-1)!.version).toBe('"7"');
  expect(state.consumables[0]!.stock_quantity).toBe(1);
});
test("T21 stale second device cannot spend the last shared unit and retains draft", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.consumables[0]!.stock_quantity = 1;
  await page.goto(`/appliance-consumables/${uid(301)}/replace`);
  await page.getByLabel("실제 교체일", { exact: true }).fill("2025-03-02");
  await state.handle(
    "POST",
    `/api/v1/appliance-consumables/${uid(300)}/replacements`,
    new URLSearchParams(),
    { replaced_on: "2025-03-02", quantity: 1, link_version: 3, clear_next_check_override: false },
    { "if-match": '"7"', "idempotency-key": "synthetic-first-device" },
  );
  await saveReplacement(page);
  await expect(page.getByRole("alert")).toContainText("공용 재고가 부족해요");
  await expect(page.getByLabel("실제 교체일", { exact: true })).toHaveValue("2025-03-02");
  expect(state.consumables[0]!.stock_quantity).toBe(0);
  expect(state.replacements.filter((r) => r.replaced_on === "2025-03-02")).toHaveLength(1);
  await page.getByRole("button", { name: "현재 공용 재고·기기 설정 비교" }).click();
  await expect(page.getByText("교체 수량 부족 · 구매 필요", { exact: true })).toBeVisible();
});
test("replacement cancellation preserves original and restores latest uncancelled schedule", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  await page.goto(`${device}/replace`);
  await page.getByLabel("실제 교체일", { exact: true }).fill("2025-03-02");
  await saveReplacement(page);
  const created = state.replacements.at(-1)!;
  await page.goto(`${device}/replacements/${created.id}`);
  await page.getByRole("button", { name: "교체 기록 취소 검토", exact: true }).click();
  await page.getByLabel("재고 취소 사유").fill("합성 교체일 오기 확인");
  await page.getByLabel("원본 전체 수량을 취소하고 보정 이력을 남겨요").check();
  await page.getByRole("button", { name: "원본 취소·재고 보정" }).click();
  await expect(page.getByText("취소 보정 · +1 개")).toBeVisible();
  expect(created.cancelled_by_movement_id).toBeTruthy();
  expect(state.consumables[0]!.stock_quantity).toBe(3);
  await page.goto(device);
  await expect(page.getByText("2025.02.28 · 교체 기록 기준")).toBeVisible();
  await expect(page.getByRole("link", { name: /2025.03.02.*취소됨/ })).toBeVisible();
});
test("receipt cancellation is versioned and insufficient stock compares current without erasing reason", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  await page.goto(`${stock}/stock/${uid(400)}`);
  await page.getByRole("button", { name: "재고 원본 취소 검토", exact: true }).click();
  await page.getByLabel("재고 취소 사유").fill("합성 구매 취소 확인");
  await page.getByLabel("원본 전체 수량을 취소하고 보정 이력을 남겨요").check();
  await page.getByRole("button", { name: "원본 취소·재고 보정" }).click();
  await expect(page.getByRole("alert")).toContainText("공용 재고가 부족해요");
  await expect(page.getByLabel("재고 취소 사유")).toHaveValue("합성 구매 취소 확인");
  expect(state.movements[0]!.reversed_by).toBeNull();
  await page.getByRole("button", { name: "취소 전 현재 재고·원본 비교" }).click();
  await page.getByRole("button", { name: "작성한 사유 유지하고 현재 상태 적용" }).click();
  await expect(page.getByLabel("원본 전체 수량을 취소하고 보정 이력을 남겨요")).not.toBeChecked();
});
test("today status uses every cursor and rejects pages crossing the Seoul date", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.pageSize = 1;
  state.statusRace = true;
  await page.goto("/consumables");
  await expect(page.getByRole("alert")).toContainText("변경");
  const region = page.getByRole("region", { name: "살펴볼 소모품" });
  await expect(region.getByRole("link", { name: /합성.*청정기/ })).toHaveCount(0);
  await region.getByRole("button", { name: "현재 기록 다시 확인" }).click();
  await expect(region.getByText("오늘 기준 · 2026.10.18", { exact: true })).toBeVisible();
  await expect(region.getByRole("link", { name: /합성.*청정기/ })).toHaveCount(2);
  expect(
    state.reads.some((r) => r.path === "/api/v1/homecare/status" && r.query.has("cursor")),
  ).toBe(true);
});
test("T24 dashboard keeps today status independent of selected asset month and uses server totals", async ({
  page,
}) => {
  const t24 = vectors.find((v) => v.id === "T-24")! as any;
  const state = await mockHomecare(page);
  state.asOf = t24.expected.consumables_as_of;
  state.links[0]!.next_check_override = t24.inputs.next_check_on;
  state.consumables[0]!.stock_quantity = t24.inputs.stock;
  await page.goto("/");
  await page.getByLabel("확인할 월").fill(t24.inputs.selected_asset_month);
  await expect(page.getByText("오늘 기준 · 2026.10.17", { exact: true })).toBeVisible();
  await expect(
    page.getByText("임시 합계 · 확인 1/3개 · 미입력 1개 · 전월값 미확인 1개"),
  ).toBeVisible();
  await expect(page.getByText("5,000,000원", { exact: true })).toBeVisible();
  await expect(page.getByText("1,000,000원", { exact: true })).toBeVisible();
  expect(
    state.reads
      .filter((r) => r.path === "/api/v1/homecare/status")
      .every((r) => !r.query.has("month") && !r.query.has("as_of")),
  ).toBe(true);
  expect(
    state.reads.some(
      (r) => r.path === "/api/v1/asset-comparison" && r.query.get("to") === "2025-01",
    ),
  ).toBe(true);
  const h2 = await page.getByRole("heading", { level: 2 }).allTextContents();
  expect(h2.slice(0, 2)).toEqual(["자산의 변화", "살펴볼 소모품"]);
  await expect(page.getByRole("link", { name: /SYNTHETIC-CLAIM-1200/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
test("foreign homecare direct paths show no metadata or edit controls", async ({ page }) => {
  await mockHomecare(page);
  await page.goto(`/appliances/${uid(999)}`);
  await expect(page.getByRole("alert")).toContainText("볼 권한");
  await expect(page.getByRole("link", { name: "가전 정보 수정·사용 종료" })).toHaveCount(0);
  await page.goto(`/appliance-consumables/${uid(999)}/replace`);
  await expect(page.getByRole("alert")).toContainText("볼 권한");
  await expect(page.getByRole("button", { name: "실제 교체·재고 사용 저장" })).toHaveCount(0);
});
test("unreferenced appliance and SKU deletion checks current version and removes only reviewed record", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.appliances.push(applianceRow(105, { name: "합성 오등록 가전" }));
  state.consumables.push(
    consumableRow(205, {
      name: "합성 오등록 소모품",
      sku_or_model: "SYNTHETIC-DELETE",
      stock_quantity: 0,
    }),
  );
  state.conflict = "appliances";
  await page.goto(`/appliances/${uid(105)}`);
  await page.getByRole("button", { name: "오등록 가전 삭제 검토", exact: true }).click();
  await page.getByLabel("오등록 합성 오등록 가전의 실제 삭제를 확인했어요").check();
  await page.getByRole("button", { name: "오등록 가전 실제 삭제" }).click();
  await page.getByRole("button", { name: "삭제 전 현재 내용 비교" }).click();
  await page.getByRole("button", { name: "현재 내용 확인 후 삭제 다시 검토" }).click();
  await expect(
    page.getByLabel("오등록 합성 오등록 가전의 실제 삭제를 확인했어요"),
  ).not.toBeChecked();
  await page.getByLabel("오등록 합성 오등록 가전의 실제 삭제를 확인했어요").check();
  await page.getByRole("button", { name: "오등록 가전 실제 삭제" }).click();
  await expect(page).toHaveURL(/\/appliances$/);
  expect(state.appliances.some((r) => r.id === uid(105))).toBe(false);
  expect(state.writes.at(-1)!.version).toBe('"2"');
  await page.goto(`/consumables/${uid(205)}`);
  await page.getByRole("button", { name: "오등록 소모품 삭제 검토", exact: true }).click();
  await page.getByLabel("오등록 합성 오등록 소모품의 실제 삭제를 확인했어요").check();
  await page.getByRole("button", { name: "오등록 소모품 실제 삭제" }).click();
  await expect(page).toHaveURL(/\/consumables$/);
  expect(state.consumables.some((r) => r.id === uid(205))).toBe(false);
});
test("history and document references block deletion while unused compatibility may be removed", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.appliances.push(applianceRow(105, { name: "합성 문서 가전" }));
  state.documented.add(uid(105));
  await page.goto(`/appliances/${uid(105)}`);
  await page.getByRole("button", { name: "오등록 가전 삭제 검토", exact: true }).click();
  await page.getByLabel("오등록 합성 문서 가전의 실제 삭제를 확인했어요").check();
  await page.getByRole("button", { name: "오등록 가전 실제 삭제" }).click();
  await expect(page.getByRole("alert")).toContainText("문서 이력이 있는 가전");
  await page.goto(stock);
  await page.getByRole("button", { name: "오등록 소모품 삭제 검토", exact: true }).click();
  await page.getByLabel("오등록 합성 공용 필터의 실제 삭제를 확인했어요").check();
  await page.getByRole("button", { name: "오등록 소모품 실제 삭제" }).click();
  await expect(page.getByRole("alert")).toContainText("재고·문서 이력");
  await page.goto(device);
  await openDisclosure(page, "기기 연결 삭제 관리");
  await page.getByRole("button", { name: "오등록 기기 연결 삭제 검토", exact: true }).click();
  await page
    .getByLabel("오등록 합성 거실 청정기 · 합성 공용 필터의 실제 삭제를 확인했어요")
    .check();
  await page.getByRole("button", { name: "오등록 기기 연결 실제 삭제" }).click();
  await expect(page.getByRole("alert")).toContainText("교체 이력이 있는 기기 연결");
  await page.goto(`/appliance-consumables/${uid(301)}`);
  await openDisclosure(page, "기기 연결 삭제 관리");
  await page.getByRole("button", { name: "오등록 기기 연결 삭제 검토", exact: true }).click();
  await page
    .getByLabel("오등록 합성 안방 청정기 · 합성 공용 필터의 실제 삭제를 확인했어요")
    .check();
  await page.getByRole("button", { name: "오등록 기기 연결 실제 삭제" }).click();
  await expect(page).toHaveURL(new RegExp(`/consumables/${uid(200)}$`));
  expect(state.links).toHaveLength(1);
  expect(state.replacements).toHaveLength(1);
});
test("appliance list and home warranty notices display server status without guessing from purchase dates", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.appliances[0]!.warranty_until = "2025-12-31";
  state.appliances[1]!.warranty_until = "2099-01-01";
  state.links[0]!.next_check_override = "2026-10-17";
  state.links[1]!.quantity_per_replacement = 4;
  state.pageSize = 1;
  await page.goto("/appliances");
  const first = page
    .locator("article.card")
    .filter({ has: page.getByRole("link", { name: "합성 거실 청정기", exact: true }) });
  await expect(first).toContainText(
    "오늘 소모품: 교체 확인 1개 · 구매 필요 0개 · 기준일 미확인 0개",
  );
  await page.getByRole("button", { name: "기록 더 보기", exact: true }).click();
  const second = page
    .locator("article.card")
    .filter({ has: page.getByRole("link", { name: "합성 안방 청정기", exact: true }) });
  await expect(second).toContainText("구매 필요 1개");
  await page.goto("/");
  await page.getByText("가전 보증 기한 확인", { exact: true }).click();
  await expect(
    page.getByRole("link", { name: "합성 거실 청정기 · 보증기간 지남", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "합성 안방 청정기 · 보증기간 안", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("2099.01.01", { exact: true })).toBeVisible();
  expect(
    state.reads.filter((r) => r.path === "/api/v1/appliances" && r.query.has("cursor")).length,
  ).toBeGreaterThan(0);
});
test("home today card ranks due, purchase, soon, low stock and unknown links and keeps the first four", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  const far = "2026-12-01";
  state.appliances = [
    "합성 가습기",
    "합성 공기청정기",
    "합성 냉장고",
    "합성 세탁기",
    "합성 정수기",
    "합성 제습기",
    "합성 오븐",
  ].map((name, i) => applianceRow(110 + i, { name }));
  state.consumables = [
    consumableRow(200),
    consumableRow(201, {
      name: "합성 예비 필터",
      sku_or_model: "SYNTHETIC-SPARE",
      stock_quantity: 1,
      low_stock_threshold: 1,
    }),
  ];
  state.replacements = [];
  state.links = [
    linkRow(310, { appliance_id: uid(115), next_check_override: "2026-10-17" }),
    linkRow(311, { appliance_id: uid(110), next_check_override: far }),
    linkRow(312, { appliance_id: uid(113), next_check_override: "2026-10-24" }),
    linkRow(313, { appliance_id: uid(111), consumable_id: uid(201), next_check_override: far }),
    linkRow(314, { appliance_id: uid(114), quantity_per_replacement: 4, next_check_override: far }),
    linkRow(315, { appliance_id: uid(112), interval_unit: "manual", interval_count: null }),
    linkRow(316, { appliance_id: uid(111), next_check_override: "2026-10-01" }),
    linkRow(317, { appliance_id: uid(116), next_check_override: "2026-10-25" }),
  ];
  await page.goto("/");
  const region = page.getByRole("region", { name: "살펴볼 소모품" });
  await expect(region.locator(".care-count")).toHaveText("확인할 소모품 6개");
  await expect(region.locator(".care-row h3")).toHaveText([
    "합성 공기청정기 · 합성 공용 필터",
    "합성 제습기 · 합성 공용 필터",
    "합성 정수기 · 합성 공용 필터",
    "합성 세탁기 · 합성 공용 필터",
  ]);
  const soon = region.locator(".care-row").nth(3).locator(".care-status");
  await expect(soon).toHaveText("곧 교체 · 교체할 재고 있음");
  await expect(soon).toHaveAttribute("data-attention", "soon");
  await expect(region.getByRole("link", { name: "나머지 2개 확인할 소모품 보기" })).toBeVisible();
  await region.getByLabel("오늘 소모품 보기").selectOption("soon");
  await expect(region.locator(".care-row h3")).toHaveText(["합성 세탁기 · 합성 공용 필터"]);
});
test("home warranty card shows the soonest active expiries before the most recent expired one", async ({
  page,
}) => {
  const state = await mockHomecare(page);
  state.links = [];
  state.replacements = [];
  state.appliances = [
    applianceRow(120, { name: "합성 김치냉장고", warranty_until: "2025-12-31" }),
    applianceRow(121, { name: "합성 건조기", warranty_until: "2026-10-16" }),
    applianceRow(122, { name: "합성 식기세척기", warranty_until: "2027-03-01" }),
    applianceRow(123, { name: "합성 로봇청소기", warranty_until: "2026-11-01" }),
    applianceRow(124, { name: "합성 안마의자", warranty_until: null }),
  ];
  await page.goto("/");
  await page.getByText("가전 보증 기한 확인", { exact: true }).click();
  const card = page.locator("details.home-warranties");
  await expect(card.locator("li a")).toHaveText([
    "합성 로봇청소기 · 보증기간 안",
    "합성 식기세척기 · 보증기간 안",
    "합성 건조기 · 보증기간 지남",
  ]);
  await expect(
    card.getByText("이외 2개 가전의 기한은 가전 목록에서 확인해 주세요.", { exact: true }),
  ).toBeVisible();
});
test("replacement cancellation review explains when a cleared manual date returns", async ({
  page,
}) => {
  await mockHomecare(page);
  await page.goto(`${device}/replacements/${uid(500)}`);
  await page.getByRole("button", { name: "교체 기록 취소 검토", exact: true }).click();
  await expect(
    page.getByText(
      "이 교체 때 해제한 직접 지정일은 그 뒤 기기 설정을 바꾸지 않았다면 다시 적용해요.",
      { exact: false },
    ),
  ).toBeVisible();
});
