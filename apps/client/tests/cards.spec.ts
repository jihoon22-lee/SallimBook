import { expect, test } from "@playwright/test";
import { mockCashflow, sampleCard } from "./support/cashflow";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => { await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z")); });
test("card filters retain metadata selection and creation never sends full number expiry or security code", async ({ page }) => {
  const state = await mockCashflow(page); await page.goto("/cards"); await page.getByRole("combobox", { name: "카드 소유자 필터", exact: true }).selectOption(uid(2)); await page.getByRole("combobox", { name: "카드 유형 필터", exact: true }).selectOption("credit"); await page.reload(); await expect(page.getByRole("combobox", { name: "카드 유형 필터", exact: true })).toHaveValue("credit"); await expect(page.getByText("•••• 1111", { exact: true })).toBeVisible(); await page.getByRole("link", { name: "카드 등록", exact: true }).click();
  await page.getByRole("combobox", { name: "카드 소유자", exact: true }).selectOption(uid(5)); await page.getByLabel("카드사", { exact: true }).fill("합성 새 카드사"); await page.getByLabel("카드명", { exact: true }).fill("합성 새 상품"); await page.getByLabel("카드 별칭", { exact: true }).fill("합성 통신 카드"); await page.getByLabel("마지막 네 자리 (선택)", { exact: true }).fill("2222"); await page.getByRole("combobox", { name: "카드 결제계좌", exact: true }).selectOption(uid(30)); await page.getByRole("button", { name: "카드 등록 저장", exact: true }).click(); await expect(page.getByRole("heading", { name: "합성 통신 카드", exact: true })).toBeVisible();
  expect(state.writes[0]!.body).toMatchObject({ owner_member_id: uid(5), issuer_name: "합성 새 카드사", last_four: "2222", settlement_account_id: uid(30) }); for (const forbidden of ["pan", "card_number", "expiry", "cvc", "cvv", "ciphertext"]) expect(Object.hasOwn(state.writes[0]!.body, forbidden)).toBe(false); await expect(page.locator('input[autocomplete="cc-number"],input[autocomplete="cc-exp"],input[autocomplete="cc-csc"]')).toHaveCount(0);
});
test("card version conflict preserves changed alias and retains the spouse's unrelated memo", async ({ page }) => {
  const state = await mockCashflow(page); state.conflict = true; await page.goto(`/cards/${uid(50)}/edit`); await page.getByLabel("카드 별칭", { exact: true }).fill("합성 변경 별칭"); await page.getByRole("button", { name: "카드 변경 저장", exact: true }).click(); await expect(page.getByRole("alert")).toBeVisible(); await expect(page.getByLabel("카드 별칭", { exact: true })).toHaveValue("합성 변경 별칭"); await page.getByRole("button", { name: "현재 카드와 비교", exact: true }).click(); await page.getByRole("button", { name: "비교한 카드 변경 유지", exact: true }).click(); await expect(page.getByRole("textbox", { name: "카드 메모", exact: true })).toHaveValue("배우자 합성 카드 메모"); await page.getByRole("button", { name: "카드 변경 저장", exact: true }).click(); await expect(page.getByRole("heading", { name: "합성 변경 별칭", exact: true })).toBeVisible();
  expect(state.writes.map((write) => write.version)).toEqual(['"1"', '"2"']); expect(state.writes.at(-1)!.body).toEqual({ alias: "합성 변경 별칭", closure_ack: false }); expect(state.cards[0]!.note).toBe("배우자 합성 카드 메모");
});
test("referenced card deletion is rejected while an unreferenced mistaken card can be deleted explicitly", async ({ page }) => {
  const state = await mockCashflow(page); await page.goto(`/cards/${uid(50)}`); await page.getByRole("button", { name: "오등록 삭제 검토", exact: true }).click(); await expect(page.getByRole("button", { name: "오등록 카드 삭제", exact: true })).toBeDisabled(); await page.getByLabel("잘못 등록한 카드이며 실제 삭제할 것을 확인했어요.", { exact: true }).check(); await page.getByRole("button", { name: "오등록 카드 삭제", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("연결된 기록이 있는 카드는 삭제할 수 없어요"); expect(state.cards).toHaveLength(1);
  state.cards.push({ ...sampleCard, id: uid(55), alias: "합성 오등록" }); await page.goto(`/cards/${uid(55)}`); await page.getByRole("button", { name: "오등록 삭제 검토", exact: true }).click(); await page.getByLabel("잘못 등록한 카드이며 실제 삭제할 것을 확인했어요.", { exact: true }).check(); await page.getByRole("button", { name: "오등록 카드 삭제", exact: true }).click(); await expect(page).toHaveURL(/\/cards$/); expect(state.cards.map((row) => row.id)).toEqual([uid(50)]);
});
test("card closure shows every linked page and changing date clears acknowledgement before saving", async ({ page }) => {
  const state = await mockCashflow(page); state.linksRequired = true; state.linksMore = true; await page.goto(`/cards/${uid(50)}`); await page.getByRole("button", { name: "카드 사용 종료", exact: true }).click(); const review = page.getByRole("region", { name: "사용 종료 영향 확인", exact: true }); await expect(review).toContainText("현재·미래 규칙 2개"); await expect(page.getByRole("button", { name: "카드 사용 종료 저장", exact: true })).toBeDisabled(); await review.getByText("연결 규칙 모두 보기", { exact: true }).click(); await expect(review.getByRole("link", { name: "합성 미래 연간 구독", exact: true })).toBeVisible(); await expect(review).toContainText("카드 승인 계획"); await expect(review).toContainText("전체 카드 명세나 계좌 출금 합계는 제공하지 않아요");
  await review.getByRole("checkbox").check(); await page.getByLabel("카드 종료일", { exact: true }).fill("2025-02-19"); await expect(review).toContainText("2025.02.19 기준"); await expect(review.getByRole("checkbox")).not.toBeChecked(); await review.getByRole("checkbox").check(); await page.getByRole("button", { name: "카드 사용 종료 저장", exact: true }).click(); await expect(page.getByRole("button", { name: "카드 사용 종료", exact: true })).toHaveCount(0);
  expect(state.writes.at(-1)!.body).toEqual({ ended_on: "2025-02-19", closure_ack: true, usage_digest: "1".padStart(64, "0") }); expect(state.linksQueries.some((query) => query.has("rule_cursor"))).toBe(true);
});
test("changed payment linkage rejects old closure proof and preserves date for re-review", async ({ page }) => {
  const state = await mockCashflow(page); state.linksRequired = true; await page.goto(`/cards/${uid(50)}`); await page.getByRole("button", { name: "카드 사용 종료", exact: true }).click(); const review = page.getByRole("region", { name: "사용 종료 영향 확인", exact: true }); await review.getByRole("checkbox").check(); state.linksVersion++;
  await page.getByRole("button", { name: "카드 사용 종료 저장", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("연결된 계획이 변경됐어요"); await expect(page.getByLabel("카드 종료일", { exact: true })).toHaveValue("2025-02-20"); await expect(review.getByRole("checkbox")).not.toBeChecked(); await review.getByRole("checkbox").check(); await page.getByRole("button", { name: "카드 사용 종료 저장", exact: true }).click(); await expect(page.getByRole("button", { name: "카드 사용 종료", exact: true })).toHaveCount(0); expect(state.writes.map((write) => write.body.usage_digest)).toEqual(["1".padStart(64, "0"), "2".padStart(64, "0")]);
});
test("mixed payment-link revisions are never combined into an approvable list", async ({ page }) => {
  const state = await mockCashflow(page); state.linksRequired = true; state.linksMore = true; state.linksRace = true; await page.goto(`/cards/${uid(50)}`); await page.getByRole("button", { name: "카드 사용 종료", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("연결된 계획이 변경됐어요"); await expect(page.getByRole("button", { name: "카드 사용 종료 저장", exact: true })).toBeDisabled(); expect(state.writes).toHaveLength(0); await page.getByRole("button", { name: "종료 영향 다시 확인", exact: true }).click(); await expect(page.getByRole("region", { name: "사용 종료 영향 확인", exact: true }).getByRole("checkbox")).toBeVisible();
});
for (const flow of ["edit", "archive"] as const) {
  test(`card ${flow} blocks future and before-start dates while allowing today`, async ({ page }) => {
    const state = await mockCashflow(page);
    state.cards[0]!.started_on = "2025-02-20";
    await page.goto(`/cards/${uid(50)}${flow === "edit" ? "/edit" : ""}`);
    if (flow === "archive") await page.getByRole("button", { name: "카드 사용 종료", exact: true }).click();
    const input = page.getByLabel(flow === "edit" ? "카드 사용 종료일" : "카드 종료일", { exact: true });
    const save = page.getByRole("button", { name: flow === "edit" ? "카드 변경 저장" : "카드 사용 종료 저장", exact: true });
    await expect(input).toHaveAttribute("max", "2025-02-20");
    await input.fill("2025-02-21");
    await expect(page.getByRole("alert")).toHaveText("카드 사용 종료일은 서울 기준 오늘을 넘을 수 없어요.");
    await expect(save).toBeDisabled();
    await input.evaluate((element) => element.closest("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(state.writes).toHaveLength(0);
    expect(state.linksQueries.some((query) => query.get("as_of_date") === "2025-02-21")).toBe(false);
    await input.fill("2025-02-19");
    await expect(page.getByRole("alert")).toHaveText("카드 사용 종료일은 사용 시작일과 같거나 늦어야 해요.");
    await expect(save).toBeDisabled();
    await input.fill("2025-02-20");
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.getByRole("heading", { name: "합성 구독 카드", exact: true })).toBeVisible();
    expect(state.writes).toHaveLength(1);
    expect(state.writes[0]!.body).toMatchObject({ ended_on: "2025-02-20", closure_ack: false });
  });
}

test("card date normalization switches at Seoul midnight and keeps optional end dates", async ({ page }) => {
  await mockCashflow(page); await page.goto("/cards");
  for (const [moment, allowed] of [["2025-02-20T14:59:59Z", false], ["2025-02-20T15:00:00Z", true]] as const) {
    await page.clock.setFixedTime(new Date(moment));
    const result = await page.evaluate(async (owner) => {
      const source = "/src/features/cards/model.ts";
      const { cardDraft, cardInput } = await import(source);
      const draft = { ...cardDraft(), owner, issuer: "합성 카드사", product: "합성 카드" };
      return { next: cardInput({ ...draft, ended: "2025-02-21" }) !== null, blank: cardInput(draft)?.ended_on,
        invalid: cardInput({ ...draft, ended: "2025-02-30" }) };
    }, uid(2));
    expect(result).toEqual({ next: allowed, blank: null, invalid: null });
  }
  await page.goto(`/cards/${uid(50)}/edit`);
  await expect(page.getByLabel("카드 사용 종료일", { exact: true })).toHaveAttribute("max", "2025-02-21");
});

test("server card date error explains both inclusive start and Seoul today bounds", async ({ page }) => {
  await mockCashflow(page);
  await page.route(`**/api/v1/cards/${uid(50)}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ error: { code: "INVALID_CARD_DATES", message: "UNTRUSTED_SYNTHETIC_MESSAGE", request_id: "synthetic" } }) });
  });
  await page.goto(`/cards/${uid(50)}/edit`);
  await page.getByLabel("카드 별칭", { exact: true }).fill("합성 변경");
  await page.getByRole("button", { name: "카드 변경 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("카드 사용 종료일은 사용 시작일과 같거나 늦어야 하며, 서울 기준 오늘을 넘을 수 없어요.");
  await expect(page.getByLabel("카드 별칭", { exact: true })).toHaveValue("합성 변경");
});
