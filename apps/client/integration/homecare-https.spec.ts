import { openDisclosure } from "../tests/support/task-ui";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import catalog from "../../../packages/test-fixtures/catalog.json" with { type: "json" };
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as {
  login: string;
  password: string;
};
type S = components["schemas"];
test.setTimeout(480_000);
test.use({ actionTimeout: 10_000, navigationTimeout: 15_000 });
const lastId = (page: Page) => new URL(page.url()).pathname.split("/").at(-1)!;
const read = <T>(page: Page, path: string): Promise<T> =>
  page.evaluate(async (path) => {
    const result = await fetch(path);
    if (!result.ok) throw new Error("Synthetic metadata read failed");
    return result.json();
  }, path);
async function appliance(page: Page, title: string, price = "") {
  await page.goto("/appliances/new");
  await page.getByLabel("가전 이름", { exact: true }).fill(title);
  await page.getByLabel("제조사", { exact: true }).fill("합성 HTTPS 제조사");
  await page.getByLabel("모델명", { exact: true }).fill("SYNTHETIC-HTTPS-AIR");
  await page.getByLabel("설치 장소").fill("합성 거실");
  await page.getByLabel("구매일", { exact: true }).fill("2025-01-01");
  if (price) await page.getByLabel("구매 금액 (원)").fill(price);
  await page.getByLabel("보증기한", { exact: true }).fill("2025-12-31");
  await page.getByRole("button", { name: "가전 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  return lastId(page);
}
async function consumable(page: Page, title: string, sku: string) {
  await page.goto("/consumables/new");
  await page.getByLabel("소모품 이름", { exact: true }).fill(title);
  await page.getByLabel("SKU·규격·모델").fill(sku);
  await page.getByLabel("재고 부족 임계 수량").fill("1");
  await page.getByRole("button", { name: "소모품 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  return lastId(page);
}
async function connect(
  page: Page,
  applianceId: string,
  consumableId: string,
  title: string,
  months: string,
) {
  await page.goto(`/appliances/${applianceId}`);
  await page.getByRole("button", { name: "호환 소모품·기기 연결" }).click();
  await page.getByLabel("연결할 소모품").selectOption(consumableId);
  await page
    .getByRole("combobox", { name: "기기별 확인 주기", exact: true })
    .selectOption("months");
  await page.getByLabel("주기 간격").fill(months);
  await page.getByRole("button", { name: "기기별 소모품 설정 저장" }).click();
  await page.getByRole("link", { name: title, exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "기기별 소모품 관리", exact: true }),
  ).toBeVisible();
  return lastId(page);
}
async function movement(
  page: Page,
  id: string,
  kind: string,
  quantity: string,
  date: string,
  reason = "",
) {
  await page.goto(`/consumables/${id}/stock/new`);
  await page.getByLabel("재고 기록 종류").selectOption(kind);
  await page
    .getByLabel(kind === "adjustment" ? "재고 조정 수량 (증가 양수·감소 음수)" : "입고·반품 수량")
    .fill(quantity);
  await page.getByLabel("재고 실제 날짜").fill(date);
  if (reason) await page.getByLabel("재고 기록 사유 (필수)").fill(reason);
  await page.getByRole("button", { name: "재고 변화 저장" }).click();
  await expect(page.getByRole("heading", { name: "재고 원본 상세", exact: true })).toBeVisible();
  return lastId(page);
}
async function replace(page: Page, id: string, date: string, override?: string) {
  await page.goto(`/appliance-consumables/${id}/replace`);
  await page.getByLabel("실제 교체일", { exact: true }).fill(date);
  if (override) await page.getByLabel("직접 지정한 다음 확인일 처리").selectOption(override);
  await page.getByLabel("실제 교체일·사용 수량과 다음 확인일 적용 방식을 확인했어요").check();
  await page.getByRole("button", { name: "실제 교체·재고 사용 저장" }).click();
  await expect(
    page.getByRole("heading", { name: "기기별 소모품 관리", exact: true }),
  ).toBeVisible();
  const link = await read<S["ApplianceConsumableResponse"]>(
    page,
    `/api/v1/appliance-consumables/${id}`,
  );
  return link.last_replacement_id!;
}
async function cancel(page: Page, path: string, replacement: boolean) {
  await page.goto(path);
  await page
    .getByRole("button", {
      name: replacement ? "교체 기록 취소 검토" : "재고 원본 취소 검토",
      exact: true,
    })
    .click();
  await page.getByLabel("재고 취소 사유").fill("합성 HTTPS 잘못 기록한 원본 취소");
  await page.getByLabel("원본 전체 수량을 취소하고 보정 이력을 남겨요").check();
  await page.getByRole("button", { name: "원본 취소·재고 보정" }).click();
  await expect(page.getByRole("heading", { name: "재고 원본 상세", exact: true })).toBeVisible();
  await expect(page.getByText("취소 보정", { exact: true })).toBeVisible();
}
async function remove(page: Page, label: string, name: string) {
  if (label === "기기 연결") await openDisclosure(page, "기기 연결 삭제 관리");
  await page.getByRole("button", { name: `오등록 ${label} 삭제 검토`, exact: true }).click();
  await page.getByLabel(`오등록 ${name}의 실제 삭제를 확인했어요`).check();
  await page.getByRole("button", { name: `오등록 ${label} 실제 삭제`, exact: true }).click();
}

test("homecare real HTTPS shared stock device cycles history dashboard and unchanged assets", async ({
  page,
}) => {
  let missingNoStore = false;
  let missingKey = false;
  page.on("response", (response) => {
    if (
      /\/api\/v1\/(appliances|consumables|appliance-consumables|homecare)(\/|\?|$)/.test(
        response.url(),
      ) &&
      response.status() >= 200 &&
      response.status() < 300 &&
      !response.headers()["cache-control"]?.includes("no-store")
    )
      missingNoStore = true;
  });
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/(stock-movements|replacements)(\/|$)/.test(new URL(request.url()).pathname) &&
      (!request.headers()["idempotency-key"] || !request.headers()["if-match"])
    )
      missingKey = true;
  });
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
  await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 가전 HTTPS");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
  ).toBeVisible();
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  await page.goto("/accounts/new");
  await page.getByLabel("금융기관", { exact: true }).fill("합성 가전 검증 기관");
  await page.getByLabel("계좌 유형", { exact: true }).selectOption("checking");
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 가전 독립 잔액");
  await page.getByLabel("소유 방식", { exact: true }).selectOption("joint");
  await page.getByLabel("가계 지분 (%)", { exact: true }).fill("100");
  await page.getByLabel("금액 입력 기준", { exact: true }).selectOption("owned");
  await page.getByLabel("보유 시작일", { exact: true }).fill("2025-01-01");
  await page.getByRole("button", { name: "계좌 등록", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 가전 독립 잔액", exact: true }),
  ).toBeVisible();
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await page.getByRole("button", { name: "합성 가전 독립 잔액 금액 확인", exact: true }).click();
  await page.getByLabel("확인 금액 (원)", { exact: true }).fill("5000000");
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click();
  await page.getByRole("button", { name: "월 확정 검토", exact: true }).click();
  await page.getByRole("button", { name: "확인하고 월 확정", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "정정 사유 남기고 다시 열기", exact: true }),
  ).toBeVisible();
  const snapshot = await read<S["MonthResponse"]>(page, "/api/v1/asset-months/2025-02");
  const a = await appliance(page, "합성 HTTPS 거실 청정기", "0"),
    b = await appliance(page, "합성 HTTPS 안방 청정기");
  expect(
    (await read<S["ApplianceResponse"]>(page, `/api/v1/appliances/${a}`)).purchase_price_krw,
  ).toBe("0");
  expect(
    (await read<S["ApplianceResponse"]>(page, `/api/v1/appliances/${b}`)).purchase_price_krw,
  ).toBeNull();
  const skuName = "합성 HTTPS 공용 필터";
  const sku = await consumable(page, skuName, "SYNTHETIC-HTTPS-SHARED");
  const linkA = await connect(page, a, sku, skuName, "1"),
    linkB = await connect(page, b, sku, skuName, "2");
  const unknown = await read<S["ApplianceConsumableResponse"]>(
    page,
    `/api/v1/appliance-consumables/${linkA}`,
  );
  expect(unknown.next_check_on).toBeNull();
  expect(unknown.replacement_due).toBeNull();
  expect(unknown.stock_quantity).toBe(0);
  // Empty setup creates metadata once, then an ordinary versioned initial-stock event.
  const setupAppliance = await appliance(page, "합성 HTTPS 첫 설정 가전");
  await page.getByRole("button", { name: "소모품 연결 이어서 설정" }).click();
  await page
    .getByRole("combobox", { name: "기기별 확인 주기", exact: true })
    .selectOption("months");
  await page.getByLabel("주기 간격", { exact: true }).fill("3");
  await page.getByRole("button", { name: "새 소모품 만들어 연결" }).click();
  await page.getByLabel("소모품 이름", { exact: true }).fill("합성 HTTPS 초기 재고 필터");
  await page.getByRole("button", { name: "소모품 등록", exact: true }).click();
  await page.getByLabel("현재 보유 총수량").fill("3");
  await page.getByRole("button", { name: "현재 보유 재고 저장" }).click();
  await expect(page.getByLabel("주기 간격", { exact: true })).toHaveValue("3");
  await page.getByRole("button", { name: "기기별 소모품 설정 저장" }).click();
  await expect(
    page.getByRole("link", { name: "합성 HTTPS 초기 재고 필터", exact: true }),
  ).toBeVisible();
  const setupLinks = await read<S["ApplianceConsumableListResponse"]>(
    page,
    `/api/v1/appliance-consumables?appliance_id=${setupAppliance}`,
  );
  const setupLink = setupLinks.items[0]!;
  const setupSku = setupLink.consumable_id;
  expect(setupLink.stock_quantity).toBe(3);
  expect(setupLink.next_check_on).toBeNull();
  await page.goto(`/consumables/${setupSku}`);
  await page.getByRole("link", { name: "입고·재고 조정 기록", exact: true }).click();
  await page.getByLabel("입고·반품 수량").fill("2");
  await page.getByRole("button", { name: "재고 변화 저장", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/consumables/${setupSku}$`));
  await expect(page.getByLabel("재고 저장 결과")).toContainText("공용 재고 3 → 5개");
  const setupEvents = await read<S["StockMovementListResponse"]>(
    page,
    `/api/v1/consumables/${setupSku}/stock-movements`,
  );
  expect(setupEvents.items).toHaveLength(2);
  expect(setupEvents.items.find((event) => event.kind === "adjustment")?.quantity_delta).toBe(3);
  expect(await read<S["MonthResponse"]>(page, "/api/v1/asset-months/2025-02")).toEqual(snapshot);
  await page.goto(`/appliances/${setupAppliance}/edit`);
  await page.getByLabel("가전 사용 종료일").fill(setupLink.as_of);
  await page
    .getByLabel("종료 후 새 교체 기록이 제한되고 오늘 관리 목록에서 제외됨을 확인했어요")
    .check();
  await page.getByRole("button", { name: "가전 수정 저장", exact: true }).click();
  await expect(
    page.getByText(`사용 종료 · ${setupLink.as_of.replaceAll("-", ".")}`, { exact: true }),
  ).toBeVisible();
  console.log("SAFE_PHASE=HOMECARE_METADATA");
  await movement(page, sku, "receipt", "1", "2025-01-01");
  await replace(page, linkA, "2025-01-01");
  const vector = catalog.vectors.find((v) => v.id === "T-20")! as any;
  const receipt = await movement(
    page,
    sku,
    "receipt",
    String(vector.inputs.movements[0].quantity_delta),
    vector.inputs.movements[0].occurred_on,
  );
  const afterReceipt = await read<S["ApplianceConsumableResponse"]>(
    page,
    `/api/v1/appliance-consumables/${linkA}`,
  );
  expect(afterReceipt.stock_quantity).toBe(vector.expected.stock_after_receipt);
  expect(afterReceipt.last_replaced_on).toBe(vector.expected.last_replaced_after_receipt);
  await replace(page, linkA, vector.inputs.movements[1].occurred_on);
  const afterReplace = await read<S["ApplianceConsumableResponse"]>(
    page,
    `/api/v1/appliance-consumables/${linkA}`,
  );
  expect(afterReplace.stock_quantity).toBe(vector.expected.final_stock);
  expect(afterReplace.last_replaced_on).toBe(vector.expected.last_replaced_after_replacement);
  expect(afterReplace.next_check_on).toBe("2025-04-02");
  await replace(page, linkB, "2025-03-03");
  expect(
    (await read<S["ApplianceConsumableResponse"]>(page, `/api/v1/appliance-consumables/${linkB}`))
      .next_check_on,
  ).toBe("2025-05-03");
  await page.goto(`/appliance-consumables/${linkA}/replace`);
  await page.getByLabel("실제 교체일", { exact: true }).fill("2025-03-04");
  const second = await page.context().newPage();
  const secondReplacement = await replace(second, linkB, "2025-03-04");
  await second.close();
  await page.getByLabel("실제 교체일·사용 수량과 다음 확인일 적용 방식을 확인했어요").check();
  await page.getByRole("button", { name: "실제 교체·재고 사용 저장" }).click();
  await expect(page.getByRole("alert")).toContainText("공용 재고가 부족해요");
  await expect(page.getByLabel("실제 교체일", { exact: true })).toHaveValue("2025-03-04");
  expect(
    (await read<S["ConsumableResponse"]>(page, `/api/v1/consumables/${sku}`)).stock_quantity,
  ).toBe(0);
  await cancel(page, `/appliance-consumables/${linkB}/replacements/${secondReplacement}`, true);
  expect(
    (await read<S["ApplianceConsumableResponse"]>(page, `/api/v1/appliance-consumables/${linkB}`))
      .next_check_on,
  ).toBe("2025-05-03");
  console.log("SAFE_PHASE=HOMECARE_SHARED_STOCK");
  await movement(page, sku, "receipt", "2", "2025-03-04");
  await page.goto(`/appliance-consumables/${linkA}`);
  await page.getByRole("button", { name: "기기별 주기·연결 수정" }).click();
  await page.getByLabel("다음 확인일 직접 지정").fill("2027-01-01");
  await page.getByRole("button", { name: "기기별 소모품 설정 저장" }).click();
  await expect(page.getByText("2027.01.01 · 직접 지정")).toBeVisible();
  await replace(page, linkA, "2025-03-05", "keep");
  expect(
    (await read<S["ApplianceConsumableResponse"]>(page, `/api/v1/appliance-consumables/${linkA}`))
      .next_check_on,
  ).toBe("2027-01-01");
  const clearReplacement = await replace(page, linkA, "2025-03-06", "clear");
  expect(
    (await read<S["ApplianceConsumableResponse"]>(page, `/api/v1/appliance-consumables/${linkA}`))
      .next_check_on,
  ).toBe("2025-04-06");
  await cancel(page, `/appliance-consumables/${linkA}/replacements/${clearReplacement}`, true);
  // Cancelling the clearing replacement restores the manual date it cleared.
  const restored = await read<S["ApplianceConsumableResponse"]>(
    page,
    `/api/v1/appliance-consumables/${linkA}`,
  );
  expect([restored.next_check_on, restored.next_check_source]).toEqual(["2027-01-01", "override"]);
  const adjustment = await movement(
    page,
    sku,
    "adjustment",
    "-1",
    "2025-03-10",
    "합성 HTTPS 실물 재고 대조",
  );
  await cancel(page, `/consumables/${sku}/stock/${adjustment}`, false);
  const returnedOut = await movement(page, sku, "return_out", "1", "2025-03-10");
  await cancel(page, `/consumables/${sku}/stock/${returnedOut}`, false);
  const returnedIn = await movement(page, sku, "return_in", "1", "2025-03-10");
  await cancel(page, `/consumables/${sku}/stock/${returnedIn}`, false);
  await page.goto(`/consumables/${sku}/stock/${receipt}`);
  await page.getByRole("button", { name: "재고 원본 취소 검토", exact: true }).click();
  await page.getByLabel("재고 취소 사유").fill("합성 HTTPS 부족 재고 취소 거부");
  await page.getByLabel("원본 전체 수량을 취소하고 보정 이력을 남겨요").check();
  await page.getByRole("button", { name: "원본 취소·재고 보정" }).click();
  await expect(page.getByRole("alert")).toContainText("공용 재고가 부족해요");
  await page.goto(`/appliances/${b}/edit`);
  await page.getByLabel("가전 사용 종료일").fill("2025-03-10");
  await page
    .getByLabel("종료 후 새 교체 기록이 제한되고 오늘 관리 목록에서 제외됨을 확인했어요")
    .check();
  await page.getByRole("button", { name: "가전 수정 저장" }).click();
  await expect(page.getByText("사용 종료 · 2025.03.10")).toBeVisible();
  await page.goto(`/consumables/${sku}/edit`);
  await page.getByLabel("재고 단위").fill("상자");
  await page.getByRole("button", { name: "소모품 수정 저장" }).click();
  await expect(page.getByRole("alert")).toContainText("단위를 바꿀 수 없어요");
  console.log("SAFE_PHASE=HOMECARE_HISTORY");
  const emptyAName = "합성 HTTPS 오등록 가전",
    emptySkuName = "합성 HTTPS 오등록 소모품";
  const emptyA = await appliance(page, emptyAName);
  const emptySku = await consumable(page, emptySkuName, "SYNTHETIC-HTTPS-EMPTY");
  await connect(page, emptyA, emptySku, emptySkuName, "1");
  await remove(page, "기기 연결", `${emptyAName} · ${emptySkuName}`);
  await expect(page).toHaveURL(new RegExp(`/consumables/${emptySku}$`));
  await remove(page, "소모품", emptySkuName);
  await expect(page).toHaveURL(/\/consumables$/);
  await page.goto(`/appliances/${emptyA}`);
  await remove(page, "가전", emptyAName);
  await expect(page).toHaveURL(/\/appliances$/);
  await page.goto(`/consumables/${sku}`);
  await remove(page, "소모품", skuName);
  await expect(page.getByRole("alert")).toContainText("재고·문서 이력");
  const beforeHome = await read<S["HomecareStatusResponse"]>(page, "/api/v1/homecare/status");
  await page.goto("/");
  await page.getByLabel("확인할 월").fill("2025-02");
  await expect(
    page.getByText(`오늘 기준 · ${beforeHome.as_of.replaceAll("-", ".")}`, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("확인한 합계 · 확인 1/1개 · 미입력 0개 · 전월값 미확인 0개"),
  ).toBeVisible();
  // The restored manual date is not due yet, so list every link to compare active and ended ones.
  await page.getByLabel("오늘 소모품 보기").selectOption("all");
  await expect(
    page.getByRole("link", { name: `합성 HTTPS 거실 청정기 · ${skuName}`, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: `합성 HTTPS 안방 청정기 · ${skuName}`, exact: true }),
  ).toHaveCount(0);
  await page.getByText("가전 보증 기한 확인", { exact: true }).click();
  await expect(
    page.getByRole("link", { name: "합성 HTTPS 거실 청정기 · 보증기간 지남", exact: true }),
  ).toBeVisible();
  const afterSnapshot = await read<S["MonthResponse"]>(page, "/api/v1/asset-months/2025-02");
  expect(afterSnapshot.revision_id).toBe(snapshot.revision_id);
  expect(afterSnapshot.version).toBe(snapshot.version);
  expect(afterSnapshot.values).toEqual(snapshot.values);
  const stock = await read<S["ConsumableResponse"]>(page, `/api/v1/consumables/${sku}`);
  const ledger = await read<S["StockMovementListResponse"]>(
    page,
    `/api/v1/consumables/${sku}/stock-movements?limit=200`,
  );
  expect(ledger.next_cursor).toBeNull();
  expect(stock.stock_quantity).toBe(2);
  expect(ledger.items.reduce((total, row) => total + row.quantity_delta, 0)).toBe(
    stock.stock_quantity,
  );
  await page.goto(`/consumables/${sku}/edit`);
  await page.getByLabel("소모품 사용 종료일").fill("2025-03-10");
  await page
    .getByLabel("종료 후 새 입고·교체가 제한되고 현재 재고와 이력은 보존됨을 확인했어요")
    .check();
  await page.getByRole("button", { name: "소모품 수정 저장" }).click();
  await expect(page.getByText("사용 종료 · 2025.03.10")).toBeVisible();
  expect(
    (await read<S["ConsumableResponse"]>(page, `/api/v1/consumables/${sku}`)).stock_quantity,
  ).toBe(2);
  expect(
    (await read<S["HomecareStatusResponse"]>(page, "/api/v1/homecare/status")).items,
  ).toHaveLength(0);
  expect(
    (await read<S["IncomeSummaryResponse"]>(page, "/api/v1/income/summary?month=2025-03")).totals
      .record_count,
  ).toBe(0);
  expect(missingKey).toBe(false);
  expect(missingNoStore).toBe(false);
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  console.log("SAFE_PHASE=HOMECARE_DASHBOARD");
});
