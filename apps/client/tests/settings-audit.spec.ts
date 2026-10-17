import { expect, test } from "@playwright/test";
import { auditRow, mockAudit } from "./support/audit";
import { members, uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
const records = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "감사 기록 목록", exact: true });

test("settings is a live account household protection export audit and version hub", async ({ page }) => {
  await mockAudit(page); await page.goto("/settings"); const main = page.getByRole("main");
  await expect(main.getByText("합성 구성원 하나 · 가계 관리자", { exact: true })).toBeVisible();
  await expect(main.getByText("합성 구성원 둘 · 가계 구성원", { exact: true })).toBeVisible();
  for (const name of ["계정과 기기", "보관함", "자료 내보내기", "감사 이력"]) await expect(main.getByRole("link", { name: new RegExp(`^${name}`) })).toBeVisible();
  await expect(main.getByText(/웹 클라이언트 버전 0\.1\.0/)).toBeVisible(); await expect(main.getByRole("button", { name: "이 Android 앱 잠그기" })).toHaveCount(0);
  await expect(page.getByText(/기능 준비 중 ·/)).toHaveCount(0); await main.getByRole("link", { name: /^감사 이력/ }).click(); await expect(page).toHaveURL(/\/settings\/audit$/);
});

test("audit shows only safe metadata Seoul time and server issuance semantics with paginated deduplication", async ({ page }) => {
  const state = await mockAudit(page); state.extraValues = true; state.duplicateMore = true;
  await page.goto("/settings/audit"); await expect(records(page).getByRole("listitem")).toHaveCount(2);
  await expect(records(page).getByText(/2026\. 10\. 18\./).first()).toBeVisible(); await expect(records(page).getByText(/기기에 실제로 저장됐는지는/)).toBeVisible();
  await records(page).getByText("기록 식별정보", { exact: true }).first().click(); await expect(records(page).getByText(uid(9200), { exact: true })).toBeVisible();
  await expect(page.getByText("UNEXPECTED_PRIVATE_VALUE")).toHaveCount(0);
  await page.getByRole("button", { name: "감사 기록 더 보기", exact: true }).click(); await expect(records(page).getByRole("listitem")).toHaveCount(3);
  expect(state.queries.filter((query) => query.cursor)).toEqual([{ limit: "50", cursor: "synthetic-next-2" }]); expect(state.queries.filter((query) => !query.cursor).every((query) => JSON.stringify(query) === JSON.stringify({ limit: "50" }))).toBe(true);
  expect(await page.evaluate(async () => ({ local: localStorage.length, session: sessionStorage.length, cache: (await caches.keys()).length }))).toEqual({ local: 0, session: 0, cache: 0 });
});

test("filters preserve UUID actor and exclusive Seoul end date and reset page cursor", async ({ page }) => {
  const state = await mockAudit(page); await page.goto("/settings/audit"); await expect(records(page).getByRole("listitem")).toHaveCount(2);
  await page.getByLabel("대상 종류", { exact: true }).selectOption("asset"); await page.getByLabel("작업 종류", { exact: true }).selectOption("update");
  await page.getByLabel("작업 구성원", { exact: true }).selectOption(members[0]!.member_id); await page.getByLabel("대상 ID (선택)").fill(uid(10));
  await page.getByLabel("시작 날짜", { exact: true }).fill("2026-10-18"); await page.getByLabel("마지막 날짜 (포함)").fill("2026-10-18");
  await page.getByRole("button", { name: "조건 적용", exact: true }).click(); await expect(records(page).getByRole("listitem")).toHaveCount(1);
  expect(state.queries.at(-1)).toEqual({ limit: "50", entity_type: "asset", action: "update", actor_member_id: members[0]!.member_id, entity_id: uid(10), since: "2026-10-17T15:00:00.000Z", until: "2026-10-18T15:00:00.000Z" });
  await expect(page).toHaveURL(/\/settings\/audit$/); await page.getByRole("button", { name: "조건 초기화", exact: true }).click(); await expect(records(page).getByRole("listitem")).toHaveCount(2); expect(state.queries.at(-1)).toEqual({ limit: "50" });
});

test("invalid UUID or reversed dates never issue a filtered read", async ({ page }) => {
  const state = await mockAudit(page); await page.goto("/settings/audit"); await expect(records(page).getByRole("listitem")).toHaveCount(2); const initialReads = state.queries.length;
  await page.getByLabel("대상 ID (선택)").fill("not-a-uuid"); await page.getByRole("button", { name: "조건 적용", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("UUID");
  await page.getByLabel("대상 ID (선택)").fill(""); await page.getByLabel("시작 날짜", { exact: true }).fill("2026-10-19"); await page.getByLabel("마지막 날짜 (포함)").fill("2026-10-18"); await page.getByRole("button", { name: "조건 적용", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("마지막 날짜"); expect(state.queries).toHaveLength(initialReads);
});

for (const [code, status, message] of [["INVALID_CURSOR", 400, "페이지 기준"], ["INVALID_AUDIT_FILTER", 422, "조회 조건"], ["AUDIT_METADATA_INVALID", 503, "기록의 형식"], ["FORBIDDEN", 403, "볼 수 없어요"], ["NOT_FOUND", 404, "접근할 수 없어요"], ["network", 0, "서버 연결"]] as const) test(`audit ${code} hides stale rows and requires explicit fresh read`, async ({ page }) => {
  const state = await mockAudit(page); await page.goto("/settings/audit"); await expect(records(page).getByRole("listitem")).toHaveCount(2);
  state.failure = code; state.failureStatus = status; await page.getByRole("button", { name: "감사 기록 더 보기", exact: true }).click(); await expect(records(page).getByRole("alert")).toContainText(message); await expect(records(page).getByRole("listitem")).toHaveCount(0); await expect(page.getByText("UNTRUSTED_AUDIT_ERROR")).toHaveCount(0);
  state.failure = ""; await page.getByRole("button", { name: "처음부터 다시 불러오기", exact: true }).click(); await expect(records(page).getByRole("listitem")).toHaveCount(2); expect(state.queries.at(-1)).toEqual({ limit: "50" });
});

test("audit expired session unmounts metadata and signed out entry makes no audit read", async ({ page }) => {
  const state = await mockAudit(page); state.failure = "UNAUTHENTICATED"; state.failureStatus = 401; await page.goto("/settings/audit"); await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible(); await expect(records(page)).toHaveCount(0);
  state.finance.signedIn = false; state.queries.length = 0; await page.reload(); await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible(); expect(state.queries).toHaveLength(0);
});

test("new filter ignores a delayed old response and empty state is explicit", async ({ page }) => {
  const state = await mockAudit(page); state.delay = 600; await page.goto("/settings/audit"); await expect.poll(() => state.queries.length).toBeGreaterThan(0); state.delay = 0;
  await page.getByLabel("대상 종류", { exact: true }).selectOption("insurance_case"); await page.getByRole("button", { name: "조건 적용", exact: true }).click(); await expect(page.getByText("이 조건에 맞는 감사 기록이 없어요.", { exact: true })).toBeVisible(); await page.waitForTimeout(700); await expect(records(page).getByRole("listitem")).toHaveCount(0);
});

test("long metadata and enlarged narrow display stay within the page and details are keyboard operable", async ({ page }) => {
  const state = await mockAudit(page); state.rows = [auditRow(9200, { request_id: "S".repeat(128), changed_fields: Array(64).fill("acknowledge_non_month_end_dates") })];
  await page.setViewportSize({ width: 320, height: 720 }); await page.goto("/settings/audit"); await page.addStyleTag({ content: "html { font-size: 200%; }" });
  const summary = records(page).getByText("기록 식별정보", { exact: true }); await summary.focus(); await page.keyboard.press("Enter"); await expect(page.getByText("S".repeat(128), { exact: true })).toBeVisible(); expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test("household lookup failure preserves audit availability and offers retry", async ({ page }) => {
  const state = await mockAudit(page); state.finance.membersFailure = true; await page.goto("/settings/audit"); await expect(records(page).getByRole("listitem")).toHaveCount(2); await expect(page.getByLabel("작업 구성원", { exact: true })).toBeDisabled();
  state.finance.membersFailure = false; await page.getByRole("button", { name: "구성원 목록 다시 불러오기", exact: true }).click(); await expect(page.getByLabel("작업 구성원", { exact: true })).toBeEnabled();
});

test("settings long member names wrap in enlarged narrow layout", async ({ page }) => {
  await mockAudit(page); await page.route("**/api/v1/household/members", (route) => route.fulfill({ json: [{ ...members[0], display_name: "S".repeat(80) }] }));
  await page.setViewportSize({ width: 320, height: 720 }); await page.goto("/settings"); await page.addStyleTag({ content: "html { font-size: 200%; }" }); await expect(page.getByText(`${"S".repeat(80)} · 가계 관리자`, { exact: true })).toBeVisible(); expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});
