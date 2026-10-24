import { expect, test } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { auditRow, mockAudit } from "./support/audit";
import { members, mockFinance, uid } from "./support/finance";
import { mockMonths } from "./support/months";
test.use({ trace: "off", screenshot: "off", video: "off" });
const records = (page: import("@playwright/test").Page) =>
  page.getByRole("region", { name: "최근 작업 목록", exact: true });
const activityRow = (
  id: number,
  patch: Partial<components["schemas"]["ActivityEventResponse"]> = {},
): components["schemas"]["ActivityEventResponse"] => ({
  ...auditRow(id),
  target_name: "합성 공동 주택",
  target_path: `/assets/${uid(10)}`,
  ...patch,
});
for (const native of [false, true]) {
  test(`${native ? "native" : "web"} recent activity has current names actors Seoul time pages and unavailable originals`, async ({
    page,
  }) => {
    const state = await mockAudit(page, native);
    state.rows = [
      activityRow(9200),
      activityRow(9199, {
        target_name: "합성 공동 주택 수정",
        actor_member_id: members[1]!.member_id,
        occurred_at: "2026-10-17T14:00:00Z",
      }),
      activityRow(9198, { target_name: null, target_path: null, action: "delete" }),
    ];
    await page.goto("/activity");
    await expect(records(page).getByRole("listitem")).toHaveCount(2);
    await expect(
      records(page).getByText(/작업자: 합성 구성원 하나.*2026\. 10\. 18\./),
    ).toBeVisible();
    await expect(records(page).getByText(/작업자: 합성 구성원 둘.*2026\. 10\. 17\./)).toBeVisible();
    await expect(
      records(page).getByRole("link", { name: "합성 공동 주택", exact: true }),
    ).toHaveAttribute("href", `/assets/${uid(10)}`);
    await page.getByRole("button", { name: "이전 작업 더 보기" }).click();
    await expect(records(page).getByRole("listitem")).toHaveCount(3);
    await expect(
      records(page).getByText("원본을 확인할 수 없는 기록", { exact: true }),
    ).toBeVisible();
    await expect(records(page).getByRole("link")).toHaveCount(2);
    await page.getByLabel("작업한 구성원", { exact: true }).selectOption(members[1]!.member_id);
    await page.getByLabel("시작 날짜", { exact: true }).fill("2026-10-17");
    await page.getByLabel("마지막 날짜", { exact: true }).fill("2026-10-17");
    await page.getByRole("button", { name: "작업 내역 조회", exact: true }).click();
    await expect(records(page).getByRole("listitem")).toHaveCount(1);
    expect(state.queries.at(-1)).toEqual({
      limit: "50",
      actor_member_id: members[1]!.member_id,
      since: "2026-10-16T15:00:00.000Z",
      until: "2026-10-17T15:00:00.000Z",
    });
    await expect(page).toHaveURL(/\/activity$/);
    if (native) {
      expect(state.http).toEqual([]);
      expect(
        state.calls
          .filter((call) => call.method === "listAuditEvents")
          .every((call) => call.args.activity === true),
      ).toBe(true);
    } else {
      await records(page).getByRole("link", { name: "합성 공동 주택 수정" }).click();
      await expect(page).toHaveURL(new RegExp(`/assets/${uid(10)}$`));
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
  test(`${native ? "native" : "web"} activity failures hide previous names and explicit retry recovers`, async ({
    page,
  }) => {
    const state = await mockAudit(page, native);
    state.rows = [activityRow(9200)];
    await page.goto("/activity");
    await expect(
      records(page).getByRole("link", { name: "합성 공동 주택", exact: true }),
    ).toBeVisible();
    state.failure = "NOT_FOUND";
    state.failureStatus = 404;
    await page.getByRole("button", { name: "처음부터 다시 불러오기" }).click();
    await expect(records(page).getByRole("alert")).toBeVisible();
    await expect(records(page).getByRole("link")).toHaveCount(0);
    state.failure = "";
    await page.getByRole("button", { name: "처음부터 다시 불러오기" }).click();
    await expect(
      records(page).getByRole("link", { name: "합성 공동 주택", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(async () => ({
        local: localStorage.length,
        session: sessionStorage.length,
        cache: (await caches.keys()).length,
      })),
    ).toEqual({ local: 0, session: 0, cache: 0 });
  });
}
test("asset conflict names the other editor and server time without replacing the typed draft", async ({
  page,
}) => {
  const state = await mockFinance(page);
  await page.goto(`/assets/${uid(10)}`);
  await expect(page.getByText(/수정자: 합성 구성원 하나.*2026\. 10\. 17\./)).toBeVisible();
  await page.goto(`/assets/${uid(10)}/edit`);
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 내가 작성 중인 이름");
  const asset = state.assets.find((row) => row.id === uid(10))!;
  asset.updated_by_member_id = members[1]!.member_id;
  asset.updated_at = "2026-10-17T15:30:00Z";
  state.conflictOnce = true;
  await page.getByRole("button", { name: "자산 수정 저장", exact: true }).click();
  await page.getByRole("button", { name: "서버의 최신 정보 확인", exact: true }).click();
  await expect(page.getByText(/마지막 수정: 합성 구성원 둘.*2026\. 10\. 18\./)).toBeVisible();
  await expect(page.getByLabel("자산 이름", { exact: true })).toHaveValue(
    "합성 내가 작성 중인 이름",
  );
  await expect(page.getByRole("cell", { name: "합성 서버 변경 이름", exact: true })).toBeVisible();
  expect(state.patches).toHaveLength(1);
});
test("confirmed month names its confirmer separately from logged in member", async ({ page }) => {
  const state = await mockMonths(page);
  state.previous!.confirmed_by_member_id = members[1]!.member_id;
  await page.goto("/assets/months/2025-01");
  await expect(page.getByText(/월 확정: 합성 구성원 둘/)).toBeVisible();
});

test("fixed rule attributes only the version on screen and hides mismatching newer actor", async ({
  page,
}) => {
  const { mockCashflow } = await import("./support/cashflow");
  const flow = await mockCashflow(page);
  const state = { rows: [] as ReturnType<typeof auditRow>[] };
  const rule = flow.rules[0]!;
  state.rows = [
    auditRow(9400, {
      entity_type: "recurring_rule",
      entity_id: rule.id,
      after_version: rule.version,
      actor_member_id: members[1]!.member_id,
    }),
  ];
  await page.route("**/api/v1/audit-events**", (route) =>
    route.fulfill({ json: { items: state.rows, next_cursor: null } }),
  );
  await page.goto(`/fixed-payments/rules/${rule.id}`);
  await expect(page.getByText(/마지막 수정: 합성 구성원 둘/)).toBeVisible();
  state.rows[0]!.after_version = rule.version + 1;
  await page.reload();
  await expect(page.getByText(/이 버전의 수정자·시각을 확인할 수 없어요/)).toBeVisible();
  await expect(page.getByText(/마지막 수정: 합성 구성원 둘/)).toHaveCount(0);
  expect(flow.writes).toHaveLength(0);
});
