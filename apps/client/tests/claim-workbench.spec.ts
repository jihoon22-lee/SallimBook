import { expect, test } from "@playwright/test";
import { claimRow, mockInsuranceEvents, payoutRow } from "./support/insurance-events";
import { mockNativeInsurance } from "./support/insurance-native";
import { uid } from "./support/finance";
import { openDisclosure } from "./support/task-ui";

test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});
for (const nativeMode of [false, true]) {
  test(`${nativeMode ? "native" : "web"} all-page claim workbench finds documents across cases and preserves date receipt and family filters`, async ({
    page,
  }) => {
    const state = await mockInsuranceEvents(page);
    const native = nativeMode ? await mockNativeInsurance(page, state) : null;
    state.pageSize = 1;
    state.core.cases[1]!.patient_member_id = uid(5);
    state.claims = [
      { ...claimRow(1200), submitted_on: "2025-02-01", claim_state: "closed" },
      {
        ...claimRow(1201),
        submitted_on: "2025-02-10",
        claim_state: "documents_required",
        requested_krw: "999999",
        decided_krw: "888888",
        received_krw: "600000",
        returned_krw: "50000",
        net_received_krw: "550000",
      },
      {
        ...claimRow(1202),
        case_id: uid(95),
        submitted_on: null,
        claim_state: "documents_required",
      },
    ];
    await page.goto("/insurance/claims");
    const results = page.getByRole("region", { name: "청구 작업 결과" });
    await expect(results.getByRole("listitem")).toHaveCount(3);
    await expect(results.getByRole("listitem").first()).toContainText("SYNTHETIC-CLAIM-1201");
    await expect(results).toContainText("실제 수령 600,000원 · 반환 50,000원 · 순수령 550,000원");
    await expect(results).toContainText("진료 시작 2025.02.01");
    await openDisclosure(page, "청구 찾기");
    await page
      .getByRole("combobox", { name: "청구 상태 필터", exact: true })
      .selectOption("documents_required");
    await page.getByRole("button", { name: "필터 닫기", exact: true }).click();
    await expect(results.getByRole("listitem")).toHaveCount(2);
    await openDisclosure(page, "청구 찾기");
    await page.getByRole("combobox", { name: "청구 환자 필터", exact: true }).selectOption(uid(5));
    await page.getByRole("combobox", { name: "실제 수령 여부", exact: true }).selectOption("none");
    await page.getByRole("button", { name: "필터 닫기", exact: true }).click();
    await expect(results.getByRole("listitem")).toHaveCount(1);
    await results.getByRole("link", { name: /SYNTHETIC-CLAIM-1202/ }).click();
    await page.goBack();
    await expect(page).toHaveURL(/patient=.*receipt=none/);
    await expect(results.getByRole("listitem")).toHaveCount(1);
    await openDisclosure(page, "청구 찾기");
    await page.getByRole("button", { name: "청구 조건 초기화", exact: true }).click();
    await page
      .getByRole("combobox", { name: "실제 수령 여부", exact: true })
      .selectOption("received");
    await page.getByLabel("접수 시작일", { exact: true }).fill("2025-02-05");
    await page.getByLabel("접수 종료일", { exact: true }).fill("2025-02-12");
    await page.getByRole("button", { name: "필터 닫기", exact: true }).click();
    await expect(results.getByRole("listitem")).toHaveCount(1);
    await expect(results).toContainText("SYNTHETIC-CLAIM-1201");
    await expect(page).toHaveURL(/receipt=received.*from=2025-02-05.*until=2025-02-12/);
    await page.reload();
    await expect(results.getByRole("listitem")).toHaveCount(1);
    expect(state.writes).toHaveLength(0);
    if (native) expect(native.http).toEqual([]);
  });

  for (const mode of ["normal", "conflict", "lost"] as const) {
    test(`${nativeMode ? "native" : "web"} existing split receipt ${mode} links only one allocation without creating cash`, async ({
      page,
    }) => {
      const state = await mockInsuranceEvents(page);
      const native = nativeMode ? await mockNativeInsurance(page, state) : null;
      state.pageSize = 1;
      state.claims = [claimRow(1200), claimRow(1201)];
      const original = payoutRow(1100, "800000");
      original.allocations[0]!.amount_krw = "600000";
      original.allocations[0]!.claim_id = uid(1201);
      original.allocations.push({
        ...original.allocations[0]!,
        id: uid(2101),
        case_id: uid(95),
        claim_id: null,
        amount_krw: "200000",
      });
      original.allocation_count = 2;
      state.payouts = [original];
      const before = structuredClone(original);
      await page.goto(`/insurance/claims/${uid(1200)}`);
      await page.getByRole("button", { name: "같은 사건의 기존 수령 찾기", exact: true }).click();
      const source = page.getByRole("region", { name: "기존 수령 연결", exact: true });
      await expect(source.getByRole("listitem")).toHaveCount(1);
      await expect(source).toContainText("이 사건 배분 600,000원");
      await expect(source).toContainText("입금 원본 800,000원");
      await source.getByRole("button", { name: "이 배분을 청구에 연결 검토", exact: true }).click();
      const review = page.getByRole("region", { name: "기존 배분 연결 검토" });
      await expect(review).toBeFocused();
      expect(state.writes).toHaveLength(0);
      await page
        .getByRole("textbox", { name: "배분 연결 정정 사유", exact: true })
        .fill("합성 기존 입금의 청구 확인");
      await page.getByLabel("기존 연결과 변경할 청구를 확인했어요.", { exact: true }).check();
      const save = page.getByRole("button", { name: "같은 입금의 청구 연결 저장", exact: true });
      if (mode === "conflict") state.conflict = true;
      if (mode === "lost") state.failure = "after";
      await save.click();
      if (mode === "conflict") {
        await page.getByRole("button", { name: "현재 배분 연결 비교", exact: true }).click();
        await page.getByRole("button", { name: "비교한 배분 연결 유지", exact: true }).click();
        await expect(
          page.getByRole("textbox", { name: "배분 연결 정정 사유", exact: true }),
        ).toHaveValue("합성 기존 입금의 청구 확인");
        await expect(
          page.getByLabel("기존 연결과 변경할 청구를 확인했어요.", { exact: true }),
        ).not.toBeChecked();
        await page.getByLabel("기존 연결과 변경할 청구를 확인했어요.", { exact: true }).check();
        await save.click();
      } else if (mode === "lost") {
        await expect(review.getByRole("alert")).toBeVisible();
        await save.click();
      }
      await expect(review).toHaveCount(0);
      await expect(
        page.getByText("이 청구의 실제 수령 600,000원 · 반환 0원 · 순수령 600,000원"),
      ).toBeVisible();
      expect(state.payouts).toHaveLength(1);
      expect(original.cash).toEqual(before.cash);
      expect(original.allocations[1]).toEqual(before.allocations[1]);
      expect(original.allocations[0]).toMatchObject({
        claim_id: uid(1200),
        amount_krw: "600000",
        case_id: uid(90),
      });
      expect(state.writes.every((w) => w.path.includes("payout-allocations"))).toBe(true);
      if (mode === "lost") expect(state.writes[0]!.key).toBe(state.writes[1]!.key);
      if (mode === "conflict") expect(state.writes.map((w) => w.version)).toEqual(['"1"', '"2"']);
      if (native) expect(native.http).toEqual([]);
    });
  }
}

test("claim evidence shows exact selected total and context without assigning a requested amount", async ({
  page,
}) => {
  const state = await mockInsuranceEvents(page);
  await page.goto(`/insurance/claims/new?case=${uid(90)}&policy=${uid(80)}`);
  await expect(
    page.getByRole("combobox", { name: "청구 사건", exact: true }).locator("option:checked"),
  ).toContainText("진료 시작 2025.02.01");
  await page.getByRole("checkbox", { name: /SYNTHETIC-RECEIPT-1000/ }).check();
  await page.getByRole("checkbox", { name: /SYNTHETIC-RECEIPT-1001/ }).check();
  await expect(page.getByText("선택 근거 2개 · 실제 지불금 합계 890,000원")).toBeVisible();
  await expect(page.getByLabel("직접 입력한 청구액 (원)", { exact: true })).toHaveValue("");
  expect(state.writes).toHaveLength(0);
});
