import { expect, test } from "@playwright/test";
import { mockVaultOverview, share } from "./support/vault-overview";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });

test("native overview routes public IDs for all ordinary vault workflows without secret fields or HTTP", async ({
  page,
}) => {
  const state = await mockVaultOverview(page, true);
  state.shares = [share(900), share(901, { source_member_id: uid(5), target_member_id: uid(2) })];
  await page.goto("/vault");
  const actions = [
    ["보관함 암호 변경", { action: "change-password" }],
    ["이 Android 기기 등록·재등록", { action: "register-device" }],
    ["복구코드로 보관함 복구", { action: "recover" }],
    ["보관함 키 회전 시작", { action: "rotate" }],
    ["이 구성원에게 공유", { action: "share", memberId: uid(5) }],
    ["공유 수락", { action: "accept-share", offerId: uid(901) }],
    ["공유 요청 거절", { action: "cancel-share", offerId: uid(901) }],
    ["공유 요청 취소", { action: "cancel-share", offerId: uid(900) }],
    ["전체 번호·유효기간 열람", { action: "view", cardId: uid(50) }],
    ["카드 비밀 등록·수정", { action: "edit", cardId: uid(50) }],
    ["카드 비밀 제거", { action: "purge", cardId: uid(50) }],
    ["이 기기의 CVC/CVV 삭제 검토", { action: "cvc-delete", cardId: uid(50) }],
  ] as const;
  for (const [label, expected] of actions) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect
      .poll(() => state.calls.filter((call) => call.method === "openVaultUI").at(-1)?.args)
      .toEqual(expected);
    await expect(
      page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }),
    ).toBeEnabled();
  }
  state.status.members[1]!.status = "active";
  state.status.members[1]!.version = 1;
  await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
  await page.getByRole("button", { name: "이 구성원 접근 철회 검토", exact: true }).click();
  await expect
    .poll(() => state.calls.filter((call) => call.method === "openVaultUI").at(-1)?.args)
    .toEqual({ action: "revoke-member", memberId: uid(5) });
  expect(state.calls.filter((call) => call.method === "openVaultUI")).toHaveLength(13);
  expect(state.http).toEqual([]);
  await expect(page.locator('input[type="password"], input[type="text"], textarea')).toHaveCount(0);
  await expect(
    page.getByText(/CVC\/CVV 입력·열람은 보안 검증 전이라 현재 비활성 상태예요/),
  ).toBeVisible();
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
});

test("native setup refreshes new server membership after completed protected flow", async ({
  page,
}) => {
  const state = await mockVaultOverview(page, true);
  state.status.initialized = false;
  state.status.own_membership = "not_enrolled";
  state.onAction = () => {
    state.status.initialized = true;
    state.status.own_membership = "active";
    state.status.version = 2;
  };
  await page.goto("/vault");
  await page.getByRole("button", { name: "보관함 처음 설정", exact: true }).click();
  await expect(page.getByText("현재 키 버전 1 · 내 보관함 권한: 접근 가능")).toBeVisible();
  expect(
    state.calls.filter((call) => call.method === "openVaultUI").map((call) => call.args),
  ).toEqual([{ action: "setup" }]);
  expect(state.http).toEqual([]);
});

test("native pending rotation passes only rotation ID for resume and abort", async ({ page }) => {
  const state = await mockVaultOverview(page, true);
  state.status.pending_rotation_id = uid(801);
  await page.goto("/vault");
  await page.getByRole("button", { name: "키 회전 계속하기", exact: true }).click();
  await expect(page.getByRole("button", { name: "키 회전 중단 검토", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "키 회전 중단 검토", exact: true }).click();
  await expect
    .poll(() =>
      state.calls.filter((call) => call.method === "openVaultUI").map((call) => call.args),
    )
    .toEqual([
      { action: "resume-rotation", rotationId: uid(801) },
      { action: "abort-rotation", rotationId: uid(801) },
    ]);
  expect(state.calls.find((call) => call.method === "getVaultRotation")!.args).toEqual({
    rotationId: uid(801),
  });
  expect(state.http).toEqual([]);
});

for (const cancellation of ["status", "AUTH_CANCELLED"])
  test(`native cancellation ${cancellation} has no automatic retry`, async ({ page }) => {
    const state = await mockVaultOverview(page, true);
    if (cancellation === "status") state.actionStatus = "cancelled";
    else state.actionFailure = cancellation;
    await page.goto("/vault");
    await page.getByRole("button", { name: "보관함 암호 변경", exact: true }).click();
    await expect(page.getByText("보관함 작업을 취소했어요.", { exact: true })).toBeVisible();
    expect(state.calls.filter((call) => call.method === "openVaultUI")).toHaveLength(1);
    expect(state.http).toEqual([]);
  });

for (const failure of ["APP_LOCKED", "SESSION_EXPIRED", "NETWORK_UNAVAILABLE", "KEY_INVALIDATED"])
  test(`native protected ${failure} keeps auth lifecycle and safe errors`, async ({ page }) => {
    const state = await mockVaultOverview(page, true);
    state.actionFailure = failure;
    await page.goto("/vault");
    await page.getByRole("button", { name: "보관함 암호 변경", exact: true }).click();
    if (failure === "NETWORK_UNAVAILABLE") {
      await expect(page.getByRole("alert")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "보관함 암호 변경", exact: true }),
      ).toBeEnabled();
    } else
      await expect(page.getByRole("button", { name: "보관함 암호 변경", exact: true })).toHaveCount(
        0,
      );
    expect(state.calls.filter((call) => call.method === "openVaultUI")).toHaveLength(1);
    expect(state.http).toEqual([]);
  });

test("native busy action rejects duplicate clicks and late completion cannot reopen departed overview", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.name));
  const state = await mockVaultOverview(page, true);
  state.delay = 600;
  await page.goto("/vault");
  const action = page.getByRole("button", { name: "보관함 암호 변경", exact: true });
  await action.evaluate((element) => {
    (element as HTMLButtonElement).click();
    (element as HTMLButtonElement).click();
  });
  await expect(action).toBeDisabled();
  await page.getByRole("link", { name: "합성 구독 카드", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/cards/${uid(50)}$`));
  await expect(page.getByRole("heading", { name: "합성 구독 카드", exact: true })).toBeVisible();
  await expect
    .poll(() => state.calls.filter((call) => call.method === "openVaultUI").length)
    .toBe(1);
  await page.waitForTimeout(700);
  await expect(
    page.getByText("보관함 작업을 마쳤어요. 현재 상태를 다시 확인해요.", { exact: true }),
  ).toHaveCount(0);
  expect(state.http).toEqual([]);
  expect(errors).toEqual([]);
});

test("native card details use native protected actions while ordinary metadata remains visible", async ({
  page,
}) => {
  const state = await mockVaultOverview(page, true);
  await page.goto(`/cards/${uid(50)}`);
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  await expect(page.getByRole("button", { name: "카드 사용 종료", exact: true })).toBeVisible();
  await expect
    .poll(() =>
      state.calls.filter((call) => call.method === "openVaultUI").map((call) => call.args),
    )
    .toEqual([{ action: "view", cardId: uid(50) }]);
  expect(state.http).toEqual([]);
  await expect(page.getByText(/현재 보안 검증 전이라 입력·열람은 비활성 상태예요/)).toBeVisible();
});
