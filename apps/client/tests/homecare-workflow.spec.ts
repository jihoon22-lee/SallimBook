import { expect, test } from "@playwright/test";
import { mockHomecare, linkRow } from "./support/homecare";
import { mockNativeHomecare } from "./support/homecare-native";
import { uid } from "./support/finance";

for (const native of [false, true]) {
  const mode = native ? "native" : "web";
  test(`${mode}: empty household appliance setup keeps cycle through creation and stock retry`, async ({
    page,
  }) => {
    const state = await mockHomecare(page);
    state.appliances.length = state.consumables.length = state.links.length = 0;
    const bridge = native ? await mockNativeHomecare(page, state) : null;
    await page.goto("/appliances/new");
    await page.getByLabel("가전 이름", { exact: true }).fill("합성 첫 가전");
    await page.getByRole("button", { name: "가전 등록", exact: true }).click();
    await expect(page).toHaveURL(/#device-consumables$/);
    await page.getByRole("button", { name: "소모품 연결 이어서 설정" }).click();
    await page.getByLabel("기기별 확인 주기").selectOption("months");
    await page.getByLabel("주기 간격", { exact: true }).fill("3");
    await page.getByLabel("다음 확인일 직접 지정").fill("2099-01-01");
    await page.getByRole("button", { name: "새 소모품 만들어 연결" }).click();
    await page.getByLabel("소모품 이름", { exact: true }).fill("합성 첫 필터");
    await page.getByRole("button", { name: "소모품 등록", exact: true }).click();
    await page.getByLabel("현재 보유 총수량").fill("3");
    state.failure = "after";
    await page.getByRole("button", { name: "현재 보유 재고 저장" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "현재 보유 재고 저장" }).click();
    await expect(page.getByLabel("주기 간격", { exact: true })).toHaveValue("3");
    await expect(page.getByLabel("다음 확인일 직접 지정")).toHaveValue("2099-01-01");
    await expect(page.getByLabel("연결할 소모품")).toHaveValue(state.consumables[0]!.id);
    await page.getByRole("button", { name: "기기별 소모품 설정 저장" }).click();
    await expect(page.getByRole("link", { name: "합성 첫 필터", exact: true })).toBeVisible();
    expect(state.consumables[0]!.stock_quantity).toBe(3);
    expect(state.links[0]!.interval_count).toBe(3);
    const writes = state.writes.filter((w) => w.path.includes("stock-movements"));
    expect(writes).toHaveLength(2);
    expect(writes[0]!.key).toBe(writes[1]!.key);
    expect(writes[0]!.body).toMatchObject({
      kind: "adjustment",
      quantity_delta: 3,
      reason: "처음 확인한 보유 재고",
    });
    if (bridge) expect(bridge.http).toEqual([]);
  });
  test(`${mode}: initial total rebases after conflict and metadata cancel keeps cycle`, async ({
    page,
  }) => {
    const state = await mockHomecare(page);
    if (native) await mockNativeHomecare(page, state);
    await page.goto(`/appliances/${uid(100)}`);
    await page.getByRole("button", { name: "호환 소모품·기기 연결" }).click();
    await page.getByLabel("기기별 확인 주기").selectOption("days");
    await page.getByLabel("주기 간격", { exact: true }).fill("45");
    await page.getByRole("button", { name: "새 소모품 만들어 연결" }).click();
    await page.getByLabel("소모품 이름", { exact: true }).fill("취소할 합성 필터");
    await page.getByRole("button", { name: "소모품 등록 취소" }).click();
    await expect(page.getByLabel("주기 간격", { exact: true })).toHaveValue("45");
    await page.getByRole("button", { name: "새 소모품 만들어 연결" }).click();
    await page.getByLabel("소모품 이름", { exact: true }).fill("합성 충돌 필터");
    await page.getByRole("button", { name: "소모품 등록", exact: true }).click();
    await page.getByLabel("현재 보유 총수량").fill("5");
    state.conflict = "stock";
    await page.getByRole("button", { name: "현재 보유 재고 저장" }).click();
    await page.getByRole("button", { name: "현재 재고 비교" }).click();
    await page.getByRole("button", { name: "입력 유지하고 현재 재고 기준 적용" }).click();
    await expect(page.getByLabel("현재 보유 총수량")).toHaveValue("5");
    await page.getByRole("button", { name: "현재 보유 재고 저장" }).click();
    await expect(page.getByLabel("주기 간격", { exact: true })).toHaveValue("45");
    expect(state.consumables.at(-1)!.stock_quantity).toBe(5);
    expect(state.writes.at(-1)!.body.quantity_delta).toBe(4);
  });
  test(`${mode}: receipt returns to originating filtered list with authoritative 3 to 5 stock`, async ({
    page,
  }) => {
    const state = await mockHomecare(page);
    if (native) await mockNativeHomecare(page, state);
    await page.goto("/consumables?care=due#today-care");
    await page.getByRole("link", { name: "입고 기록", exact: true }).first().click();
    await page.getByLabel("입고·반품 수량").fill("2");
    await page.getByRole("button", { name: "재고 변화 저장", exact: true }).click();
    await expect(page).toHaveURL(/\/consumables\?care=due#today-care$/);
    await expect(page.getByLabel("재고 저장 결과")).toContainText("공용 재고 3 → 5개");
    await expect(page.getByLabel("오늘 소모품 보기")).toHaveValue("due");
    expect(state.links[0]!.last_replaced_on).toBe("2025-01-31");
  });
  test(`${mode}: replacement returns home preserving filter and next check`, async ({ page }) => {
    const state = await mockHomecare(page);
    if (native) await mockNativeHomecare(page, state);
    await page.goto("/?care=all");
    await page.getByRole("link", { name: "교체 기록", exact: true }).first().click();
    await page.getByLabel("실제 교체일", { exact: true }).fill("2025-03-01");
    await page.getByLabel("실제 교체일·사용 수량과 다음 확인일 적용 방식을 확인했어요").check();
    await page.getByRole("button", { name: "실제 교체·재고 사용 저장" }).click();
    await expect(page).toHaveURL(/\/\?care=all$/);
    await expect(page.getByLabel("오늘 소모품 보기")).toHaveValue("all");
    await expect(page.getByLabel("재고 저장 결과")).toContainText("공용 재고 3 → 2개");
    await expect(page.getByLabel("재고 저장 결과")).toContainText("다음 확인 2025.04.01");
  });
  test(`${mode}: saved receipt read failure retries only reads and later changes are labelled`, async ({
    page,
  }) => {
    const state = await mockHomecare(page);
    const handle = state.handle;
    let failRead = true;
    let saved = false;
    state.handle = async (...args) => {
      if (saved && args[0] === "GET" && args[1].includes("/stock-movements/") && failRead)
        return {
          status: 503,
          body: {
            error: { code: "REQUEST_FAILED", message: "synthetic", request_id: "synthetic" },
          },
        };
      const result = await handle(...args);
      if (args[0] === "POST" && args[1].endsWith("/stock-movements")) {
        saved = true;
        state.consumables[0]!.stock_quantity++;
        state.consumables[0]!.version++;
      }
      return result;
    };
    if (native) await mockNativeHomecare(page, state);
    await page.goto(`/consumables/${uid(200)}`);
    await page.getByRole("link", { name: "입고·재고 조정 기록", exact: true }).click();
    await page.getByLabel("입고·반품 수량").fill("2");
    await page.getByRole("button", { name: "재고 변화 저장", exact: true }).click();
    const outcome = page.getByLabel("재고 저장 결과");
    await expect(outcome).toContainText("저장은 완료됐어요");
    failRead = false;
    await outcome.getByRole("button", { name: "현재 기록 다시 확인" }).click();
    await expect(outcome).toContainText("현재 공용 재고 6개 · 이 기록 이후의 변경도 포함돼요.");
    expect(state.writes.filter((w) => w.path.includes("stock-movements"))).toHaveLength(1);
  });
  test(`${mode}: optional initial stock can be skipped and home remainder keeps filter and target`, async ({
    page,
  }) => {
    const state = await mockHomecare(page);
    if (native) await mockNativeHomecare(page, state);
    await page.goto("/consumables/new");
    await page.getByLabel("소모품 이름", { exact: true }).fill("합성 나중에 설정");
    await page.getByRole("button", { name: "소모품 등록", exact: true }).click();
    await page.getByRole("button", { name: "재고 설정 건너뛰고 계속" }).click();
    expect(state.consumables.at(-1)!.stock_quantity).toBe(0);
    expect(state.writes.filter((w) => w.path.includes("stock-movements"))).toHaveLength(0);
    for (let i = 0; i < 5; i++)
      state.links.push(linkRow(900 + i, { next_check_override: "2025-02-28" }));
    await page.goto("/?care=due");
    await page.getByRole("link", { name: /나머지/ }).click();
    await expect(page).toHaveURL(/\/consumables\?care=due#today-care$/);
    await expect(page.getByLabel("오늘 소모품 보기")).toHaveValue("due");
    await expect(page.locator("#today-care")).toBeFocused();
  });
}
