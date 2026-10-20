import { expect, test } from "@playwright/test";
import { mockFinance, uid } from "./support/finance";
import {
  assetDraft,
  changedAssetFields,
  mergeAssetDraft,
  percentToShare,
  shareToPercent,
} from "../src/features/assets/model";
import { jointAsset } from "./support/finance";

test.use({ trace: "off", screenshot: "off", video: "off" });

test("share conversion is exact at the API boundary and ownership merges as a relationship", () => {
  expect(percentToShare("33.3333333333333333")).toBe("0.333333333333333333");
  expect(shareToPercent("0.333333333333333333")).toBe("33.3333333333333333");
  expect(percentToShare("0")).toBe("0");
  expect(percentToShare("100")).toBe("1");
  for (const value of ["", "100.0000000000000001", "1e2", "-1", "0.12345678901234567"])
    expect(percentToShare(value)).toBeNull();
  const original = {
    ...jointAsset,
    ownership_kind: "individual" as const,
    owner_member_id: uid(2),
  };
  const draft = { ...assetDraft(original), owner_member_id: uid(5) };
  const merged = mergeAssetDraft(jointAsset, draft, changedAssetFields(original, draft));
  expect(merged.ownership_kind).toBe("individual");
  expect(merged.owner_member_id).toBe(uid(5));
});

test("asset filters use metadata fields and show each joint asset once without monetary placeholders", async ({
  page,
}) => {
  const state = await mockFinance(page);
  await page.goto("/assets");
  await expect(page.getByRole("link", { name: "합성 공동 주택", exact: true })).toHaveCount(1);
  await expect(page.getByRole("link", { name: "합성 종료 대출", exact: true })).toHaveCount(0);
  await page
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: "합성 공동 주택", exact: true }) })
    .getByText("소유·지분·보유기간 자세히", { exact: true })
    .click();
  await expect(page.getByText("50%", { exact: true })).toBeVisible();
  await expect(
    page.getByText("아직 금액을 조회하지 않았어요.", { exact: false }).first(),
  ).toBeVisible();
  await page.locator(".asset-filter-panel > summary").click();
  await page.getByLabel("소유자 필터", { exact: true }).selectOption(uid(5));
  await expect(page.getByRole("link", { name: "합성 공동 주택", exact: true })).toHaveCount(0);
  expect(state.queries.at(-1)?.get("owner_member_id")).toBe(uid(5));
  await page.getByRole("button", { name: "필터 초기화", exact: true }).click();
  await page.getByLabel("등록 상태 필터", { exact: true }).selectOption("archived");
  await expect(page.getByRole("link", { name: "합성 종료 대출", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("등록 상태 필터", { exact: true })).toHaveValue("archived");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("create sends explicit ownership and amount basis with canonical share and no amount fields", async ({
  page,
}) => {
  const state = await mockFinance(page);
  await page.goto("/assets/new");
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 새 공동 자산");
  await page.getByLabel("분류", { exact: true }).selectOption("real_estate");
  await page.getByLabel("소유 방식", { exact: true }).selectOption("joint");
  await page.getByLabel("가계 지분 (%)", { exact: true }).fill("33.3333333333333333");
  await page.getByLabel("금액 입력 기준", { exact: true }).selectOption("owned");
  await page.getByLabel("보유 시작일", { exact: true }).fill("2020-03-01");
  await page.getByRole("button", { name: "자산 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 새 공동 자산", exact: true })).toBeVisible();
  expect(state.creates).toHaveLength(1);
  expect(state.creates[0]?.household_share).toBe("0.333333333333333333");
  expect(state.creates[0]?.amount_basis).toBe("owned");
  expect(state.creates[0]?.owner_member_id).toBeNull();
  expect(
    Object.keys(state.creates[0]!).some((key) => key.includes("krw") || key === "balance"),
  ).toBe(false);
});

test("409 preserves draft, requires review and keeps unrelated server edits", async ({ page }) => {
  const state = await mockFinance(page);
  state.conflictOnce = true;
  await page.goto(`/assets/${uid(10)}/edit`);
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 내 수정 이름");
  await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("작성한 내용은 그대로");
  await expect(page.getByLabel("자산 이름", { exact: true })).toHaveValue("합성 내 수정 이름");
  expect(state.patches).toHaveLength(1);
  await expect(page.getByRole("button", { name: "자산 수정 저장", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "서버의 최신 정보 확인", exact: true }).click();
  await expect(page.getByRole("cell", { name: "합성 서버 변경 이름", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "비교한 내 수정 유지", exact: true }).click();
  await expect(page.getByLabel("메모 (선택)", { exact: true })).toHaveValue(
    "합성 다른 편집자의 메모",
  );
  await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 내 수정 이름", exact: true })).toBeVisible();
  expect(state.patches.map((entry) => entry.version)).toEqual(['"1"', '"2"']);
  expect(state.patches[1]?.body).toEqual({ name: "합성 내 수정 이름", closure_ack: false });
});

test("archive preserves the item and chosen date across a conflict", async ({ page }) => {
  const state = await mockFinance(page);
  state.archiveConflictOnce = true;
  await page.goto(`/assets/${uid(10)}`);
  await page.getByRole("button", { name: "사용 종료하기", exact: true }).click();
  await page.getByLabel("종료일", { exact: true }).fill("2026-09-20");
  await page.getByRole("button", { name: "사용 종료 확인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("다른 곳에서 정보가 변경");
  await page.getByRole("button", { name: "최신 자산 정보 다시 확인", exact: true }).click();
  await expect(page.getByLabel("종료일", { exact: true })).toHaveValue("2026-09-20");
  await page.getByRole("button", { name: "사용 종료 확인", exact: true }).click();
  await expect(page.getByRole("button", { name: "사용 종료하기", exact: true })).toHaveCount(0);
  await expect(page.getByText("사용 종료", { exact: true })).toBeVisible();
  expect(state.assets.find((asset) => asset.id === uid(10))?.ended_on).toBe("2026-09-20");
  expect(state.archives).toEqual(['"1"', '"2"']);
});

test("foreign and missing resources show the same safe absence without editing controls", async ({
  page,
}) => {
  await mockFinance(page);
  await page.goto(`/assets/${uid(999)}/edit`);
  await expect(page.getByRole("alert")).toContainText("찾을 수 없거나 볼 권한이 없어요");
  await expect(page.getByLabel("자산 이름", { exact: true })).toHaveCount(0);
  await expect(page.getByText("UNTRUSTED_FINANCE_ERROR")).toHaveCount(0);
});

test("domain writes renew CSRF only on its rejection and retain drafts on other failures", async ({
  page,
}) => {
  const state = await mockFinance(page);
  state.mutationCsrfOnce = true;
  await page.goto(`/assets/${uid(10)}/edit`);
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 CSRF 확인 자산");
  await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 CSRF 확인 자산", exact: true }),
  ).toBeVisible();
  expect(state.csrfCalls).toBe(2);
  state.rejectMutation = true;
  await page.getByRole("link", { name: "자산 정보 수정", exact: true }).click();
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 보존할 작성 내용");
  await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("자산 이름", { exact: true })).toHaveValue("합성 보존할 작성 내용");
  expect(state.csrfCalls).toBe(2);
});

test("asset kind restriction explains existing values without a stale-version retry loop", async ({
  page,
}) => {
  await mockFinance(page);
  await page.route(`**/api/v1/assets/${uid(10)}`, async (route) => {
    if (
      route.request().method() === "PATCH" &&
      route.request().postDataJSON().kind === "liability"
    ) {
      return route.fulfill({
        status: 409,
        json: { error: { code: "ASSET_KIND_IN_USE", message: "synthetic", request_id: uid(99) } },
      });
    }
    return route.fallback();
  });
  await page.goto(`/assets/${uid(10)}/edit`);
  await page.getByLabel("자산·부채 구분", { exact: true }).selectOption("liability");
  await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("월별 금액 기록이 있어");
  await expect(
    page.getByRole("button", { name: "서버의 최신 정보 확인", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "자산 수정 저장", exact: true })).toBeEnabled();
  await page.getByLabel("자산·부채 구분", { exact: true }).selectOption("asset");
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 구분 유지 수정");
  await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 구분 유지 수정", exact: true }),
  ).toBeVisible();
});

test("asset and account end dates stop at Seoul today and a stored future end asks for correction", async ({
  page,
}) => {
  const state = await mockFinance(page);
  await page.clock.setFixedTime(new Date("2026-03-31T14:59:00Z"));
  state.assets[2]!.ended_on = "2045-01-31";
  await page.goto(`/assets/${uid(12)}`);
  await expect(
    page.getByText("보유 종료일이 서울 기준 오늘보다 늦게 저장돼 있어요", { exact: false }),
  ).toBeVisible();
  await page.goto("/assets/new");
  await expect(page.getByLabel("보유 종료일 (선택)", { exact: true })).toHaveAttribute(
    "max",
    "2026-03-31",
  );
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "계좌 사용 종료하기", exact: true }).click();
  await expect(page.getByLabel("계좌 종료일", { exact: true })).toHaveAttribute(
    "max",
    "2026-03-31",
  );
  await page.route("**/api/v1/assets/*/archive", (route) =>
    route.fulfill({
      status: 422,
      json: { error: { code: "ASSET_END_IN_FUTURE", message: "synthetic", request_id: uid(99) } },
    }),
  );
  await page.goto(`/assets/${uid(10)}`);
  await page.getByRole("button", { name: "사용 종료하기", exact: true }).click();
  await expect(page.getByLabel("종료일", { exact: true })).toHaveAttribute("max", "2026-03-31");
  await page.getByRole("button", { name: "사용 종료 확인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "보유 종료일은 서울 기준 오늘보다 늦을 수 없어요",
  );
});
