import { expect, test } from "@playwright/test";
import { mockVaultOverview, share } from "./support/vault-overview";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-10-18T00:00:00Z"));
});

test("opening setup brings the protected form into view and gives it keyboard focus", async ({
  page,
}) => {
  const state = await mockVaultOverview(page);
  Object.assign(state.status, {
    initialized: false,
    id: null,
    version: null,
    current_key_version: null,
    own_membership: "not_enrolled",
    members: [],
  });
  await page.goto("/vault");
  await page.getByRole("button", { name: "보관함 처음 설정", exact: true }).click();
  const region = page.getByRole("region", { name: "보관함 보호 작업", exact: true });
  await expect(region).toBeFocused();
  const top = await region.evaluate((element) => element.getBoundingClientRect().top);
  expect(top).toBeGreaterThanOrEqual(0);
  expect(top).toBeLessThan(page.viewportSize()!.height - 100);
});

test("overview exposes safe status and masks only with no secret inputs or persistence", async ({
  page,
}) => {
  const state = await mockVaultOverview(page);
  await page.goto("/vault");
  await expect(page.getByText("현재 키 버전 1 · 내 보관함 권한: 접근 가능")).toBeVisible();
  await expect(page.getByText("•••• 1111", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "이 구성원에게 공유", exact: true })).toBeEnabled();
  await expect(page.getByText(/선택적 공유 CVC\/CVV/)).toBeVisible();
  await expect(page.getByRole("button", { name: /이 기기의 CVC\/CVV/ })).toHaveCount(0);
  await expect(
    page.locator('input[type="password"], input[name="pan"], input[name="cvc"]'),
  ).toHaveCount(0);
  expect(new Set(state.reads)).toEqual(new Set(["/api/v1/vault/status", "/api/v1/vault/shares"]));
  expect(state.cashflow.writes).toHaveLength(0);
  expect(
    await page.evaluate(async () => ({
      local: localStorage.length,
      session: sessionStorage.length,
      cache: (await caches.keys()).length,
    })),
  ).toEqual({ local: 0, session: 0, cache: 0 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    page.viewportSize()!.width,
  );
});

test("setup and membership gates distinguish uninitialized not-enrolled and revoked", async ({
  page,
}) => {
  const state = await mockVaultOverview(page);
  state.status.initialized = false;
  state.status.own_membership = "not_enrolled";
  await page.goto("/vault");
  await expect(page.getByRole("button", { name: "보관함 처음 설정", exact: true })).toBeEnabled();
  state.status.initialized = true;
  await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
  await expect(page.getByText(/가계에 가입해도 카드 비밀은 자동 공유되지 않아요/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "복구코드로 보관함 복구", exact: true }),
  ).toHaveCount(0);
  state.status.own_membership = "revoked";
  await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
  await expect(page.getByText(/보관함 접근이 철회됐어요/)).toBeVisible();
  await expect(page.getByRole("button", { name: "이 구성원에게 공유", exact: true })).toHaveCount(
    0,
  );
});

test("rotation requirement blocks new edit share and active rotation exposes safe progress", async ({
  page,
}) => {
  const state = await mockVaultOverview(page);
  state.status.rotation_required = true;
  await page.goto("/vault");
  await expect(
    page.getByRole("button", { name: "카드 비밀 등록·수정", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "이 구성원에게 공유", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "보관함 키 회전 시작", exact: true }),
  ).toBeEnabled();
  state.status.pending_rotation_id = uid(801);
  await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
  await expect(page.getByRole("heading", { name: "진행 중인 키 회전", exact: true })).toBeVisible();
  await expect(page.getByText("0 / 1", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "보관함 암호 변경", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "카드 비밀 제거", exact: true })).toBeDisabled();
});

test("share pagination shows expired and incoming offers without confusing account invitation", async ({
  page,
}) => {
  const state = await mockVaultOverview(page);
  state.pageSize = 1;
  state.shares = [
    share(900, { expires_at: "2026-10-17T00:00:00Z" }),
    share(901, { source_member_id: uid(5), target_member_id: uid(2) }),
  ];
  await page.goto("/vault");
  await expect(page.getByText(/합성 구성원 하나 → 합성 구성원 둘 · 만료됨/)).toBeVisible();
  await expect(page.getByRole("button", { name: "공유 요청 취소", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "공유 요청 더 보기", exact: true }).click();
  await expect(page.getByRole("button", { name: "공유 수락", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "공유 요청 더 보기", exact: true })).toHaveCount(0);
});

test("failed status refresh hides stale authorization and can explicitly recover", async ({
  page,
}) => {
  const state = await mockVaultOverview(page);
  await page.goto("/vault");
  await expect(page.getByRole("button", { name: "보관함 암호 변경", exact: true })).toBeVisible();
  state.failRead = "/status";
  await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("button", { name: "보관함 암호 변경", exact: true })).toHaveCount(0);
  await expect(page.getByText("UNTRUSTED_VAULT_DETAIL")).toHaveCount(0);
  state.failRead = "";
  await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
  await expect(page.getByRole("button", { name: "보관함 암호 변경", exact: true })).toBeVisible();
});

test("401 read unmounts all authenticated vault controls", async ({ page }) => {
  const state = await mockVaultOverview(page);
  state.failRead = "/status";
  state.readFailureStatus = 401;
  await page.goto("/vault");
  await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "보관함 처음 설정", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "카드 비밀", exact: true })).toHaveCount(0);
});

test("card detail retains ordinary metadata operations and exposes separate protected entry", async ({
  page,
}) => {
  await mockVaultOverview(page);
  await page.goto(`/cards/${uid(50)}`);
  await expect(page.getByRole("button", { name: "카드 사용 종료", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "카드 정보 수정", exact: true })).toBeVisible();
  await page.getByText("암호 보관함 관리", { exact: true }).click();
  await expect(page.getByRole("button", { name: "카드 비밀 제거", exact: true })).toBeVisible();
  await expect(
    page.getByText(/공유 CVC\/CVV는 보관함에서 동의 후 암호화해 저장해요/),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /이 기기의 CVC\/CVV/ })).toHaveCount(0);
});

test("card with protected secret locks last four while ordinary alias stays editable", async ({
  page,
}) => {
  const state = await mockVaultOverview(page);
  state.cashflow.cards[0]!.has_secret = true;
  await page.goto(`/cards/${uid(50)}/edit`);
  await expect(page.getByLabel("마지막 네 자리 (선택)", { exact: true })).toBeDisabled();
  await expect(
    page.getByRole("link", { name: "카드 보관함에서 번호 수정", exact: true }),
  ).toHaveAttribute("href", `/cards/${uid(50)}`);
  await page.getByLabel("카드 별칭", { exact: true }).fill("합성 별칭 변경");
  await page.getByRole("button", { name: "카드 변경 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 별칭 변경", exact: true })).toBeVisible();
  expect(state.cashflow.writes).toHaveLength(1);
  expect(state.cashflow.writes[0]!.body).not.toHaveProperty("last_four");
  expect(state.cashflow.writes[0]!.body).toMatchObject({ alias: "합성 별칭 변경" });
});

test("new secret discovered during conflict supersedes stale last-four draft only", async ({
  page,
}) => {
  const state = await mockVaultOverview(page);
  await page.goto(`/cards/${uid(50)}/edit`);
  await page.getByLabel("마지막 네 자리 (선택)", { exact: true }).fill("2222");
  await page.getByLabel("카드 별칭", { exact: true }).fill("합성 유지 별칭");
  state.cashflow.cards[0]!.version++;
  state.cashflow.cards[0]!.has_secret = true;
  state.cashflow.cards[0]!.last_four = "3333";
  state.cashflow.cards[0]!.masked_number = "•••• 3333";
  await page.getByRole("button", { name: "카드 변경 저장", exact: true }).click();
  await page.getByRole("button", { name: "현재 카드와 비교", exact: true }).click();
  await page.getByRole("button", { name: "비교한 카드 변경 유지", exact: true }).click();
  await expect(page.getByLabel("마지막 네 자리 (선택)", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("마지막 네 자리 (선택)", { exact: true })).toHaveValue("3333");
  await expect(page.getByLabel("카드 별칭", { exact: true })).toHaveValue("합성 유지 별칭");
  await page.getByRole("button", { name: "카드 변경 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 유지 별칭", exact: true })).toBeVisible();
  expect(state.cashflow.writes.at(-1)!.body).not.toHaveProperty("last_four");
});

test("server-stored cards link to details instead of offering a second vault import", async ({
  page,
}) => {
  const state = await mockVaultOverview(page);
  Object.assign(state.cashflow.cards[0]!, { has_stored_details: true, has_secret: false });
  await page.goto("/vault");
  await expect(
    page.getByRole("button", { name: "미등록 카드 비밀 일괄 입력", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "암호 없이 저장한 카드정보 보기", exact: true }),
  ).toBeVisible();
});
