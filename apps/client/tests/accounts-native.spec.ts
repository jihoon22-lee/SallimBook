import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { members, sampleAccount, uid } from "./support/finance";
// Bridge simulations verify React dispatch only; Android policy and device security need native tests.
test.use({ trace: "off", screenshot: "off", video: "off" });
async function nativeFinanceMock(
  page: Page,
  scenario: "normal" | "conflict" | "reauth" | "cancelled" | "expired" = "normal",
) {
  await page.addInitScript(
    ({ account, household, scenario }) => {
      const state = {
        account,
        calls: [] as { method: string; args: Record<string, unknown> }[],
        http: 0,
        accountGets: 0,
        editOnce: true,
        deleted: false,
      };
      Object.assign(window, {
        __financeNative: state,
        CapacitorCustomPlatform: { name: "android" },
        Capacitor: {
          PluginHeaders: [
            {
              name: "SallimBookAuth",
              methods: [
                "getSession",
                "request",
                "getAssetComparison",
                "getAssetTrends",
                "listAssets",
                "getAsset",
                "createAsset",
                "updateAsset",
                "archiveAsset",
                "deleteAsset",
                "getAccountPaymentLinks",
                "listIncome",
                "listAccounts",
                "getAccount",
                "createAccount",
                "updateAccount",
                "deleteAccount",
                "editAccountNumberUI",
                "showAccountNumberUI",
                "showAccountNumberWithPasskeyUI",
              ]
                .map((name) => ({ name, rtype: "promise" }))
                .concat([
                  { name: "addListener", rtype: "callback" },
                  { name: "removeListener", rtype: "promise" },
                ]),
            },
          ],
          nativeCallback: () => "synthetic-lock-listener",
          nativePromise: async (
            _plugin: string,
            method: string,
            args: Record<string, unknown> = {},
          ) => {
            if (method === "removeListener") return;
            state.calls.push({ method, args });
            const ok = (value: unknown) => ({ ok: true, value });
            const metadata = (body: unknown) => ok({ status: 200, body });
            if (method === "getSession") return ok({ available: true, authenticated: true });
            if (method === "request" && args.path === "/api/v1/me") return metadata(household[0]);
            if (method === "request" && args.path === "/api/v1/household/members")
              return metadata(household);
            if (method === "listIncome") return metadata({ items: [], next_cursor: null });
            if (method === "getAccountPaymentLinks")
              return metadata({
                resource_kind: "account",
                resource_id: account.id,
                resource_version: account.version,
                asset_id: account.asset_id,
                as_of_date: (args.query as { as_of_date: string }).as_of_date,
                usage_digest: "0".repeat(64),
                requires_confirmation: false,
                coverage: "registered_recurring_only",
                account_withdrawal_total_available: false,
                rules: { items: [], total_count: 0, next_cursor: null },
                obligations: { items: [], total_count: 0, next_cursor: null },
                cards: { items: [], total_count: 0, next_cursor: null },
              });
            if (method === "getAssetComparison") {
              const query = args.query as { from: string; to: string };
              const period = (month: string) => ({
                month,
                state: "missing",
                revision: null,
                confirmed_at: null,
                totals: null,
                dates: {
                  non_month_end_asset_ids: [],
                  missing_date_asset_ids: [],
                  mixed_dates: false,
                },
              });
              return metadata({
                from_month: query.from,
                to_month: query.to,
                filters: {},
                state: "current_missing",
                previous: period(query.from),
                current: period(query.to),
                total_delta_krw: null,
                common_scope_delta_krw: null,
                change_percent: null,
                change_percent_unavailable_reason: "current_missing",
                scope_changed: null,
                added_asset_ids: [],
                removed_asset_ids: [],
                changed_share_asset_ids: [],
                item_count: 0,
                items: [],
                next_cursor: null,
              });
            }
            if (method === "getAssetTrends") {
              const query = args.query as { from: string; to: string };
              return metadata({
                from_month: query.from,
                to_month: query.to,
                filters: {},
                series_kind: "asset_owned_amount",
                points: [],
              });
            }
            if (method === "listAccounts")
              return metadata({ items: state.deleted ? [] : [state.account], next_cursor: null });
            if (method === "deleteAsset")
              return ok({ status: 409, body: { error: { code: "ASSET_IN_USE" } } });
            if (method === "deleteAccount") {
              state.deleted = true;
              return ok({ status: 204, body: null });
            }
            if (method === "getAccount") {
              state.accountGets++;
              return metadata(state.account);
            }
            if (method === "listAssets")
              return metadata({ items: [state.account.asset], next_cursor: null });
            if (method === "getAsset") return metadata(state.account.asset);
            if (method === "updateAccount") {
              Object.assign(state.account, args.input, { version: state.account.version + 1 });
              return metadata(state.account);
            }
            if (method === "showAccountNumberUI") {
              if (scenario === "reauth") return { ok: false, code: "REAUTHENTICATION_REQUIRED" };
              if (scenario === "expired") return { ok: false, code: "SESSION_EXPIRED" };
              return ok({ status: "completed" });
            }
            if (method === "showAccountNumberWithPasskeyUI") return ok({ status: "completed" });
            if (method === "editAccountNumberUI") {
              state.account.version++;
              state.account.masked_number = "••••TEST";
              if (scenario === "conflict" && state.editOnce) {
                state.editOnce = false;
                return { ok: false, code: "VERSION_CONFLICT" };
              }
              return ok({ status: scenario === "cancelled" ? "cancelled" : "saved" });
            }
            return { ok: false, code: "INVALID_REQUEST" };
          },
        },
      });
      const fetch = window.fetch;
      window.fetch = (input, init) => {
        const url = input instanceof Request ? input.url : String(input);
        if (new URL(url, location.href).pathname.startsWith("/api/")) state.http++;
        return fetch.call(window, input, init);
      };
    },
    { account: sampleAccount, household: members, scenario },
  );
}
async function state(page: Page) {
  return page.evaluate(
    () =>
      (
        window as unknown as {
          __financeNative: {
            calls: { method: string; args: Record<string, unknown> }[];
            http: number;
            accountGets: number;
          };
        }
      ).__financeNative,
  );
}
async function assertBoundary(page: Page) {
  await expect(page.locator("input[type=password],output")).toHaveCount(0);
  const observed = await state(page);
  expect(observed.http).toBe(0);
  expect(
    observed.calls
      .filter(
        (call) =>
          call.method.endsWith("NumberUI") || call.method === "showAccountNumberWithPasskeyUI",
      )
      .every(
        (call) =>
          Object.keys(call.args).sort().join(",") ===
          (call.method === "editAccountNumberUI" ? "accountId,ifMatch" : "accountId"),
      ),
  ).toBe(true);
  expect(
    observed.calls.every((call) => !JSON.stringify(call.args).includes("account_number")),
  ).toBe(true);
  expect(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0)).toBe(
    true,
  );
}

test("native account metadata uses typed bridge with no web API or number input", async ({
  page,
}) => {
  await nativeFinanceMock(page);
  await page.goto("/accounts");
  await page.getByRole("link", { name: "합성 개인 금융 자산", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 개인 금융 자산", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Android에서 전체 계좌번호 보기", exact: true }).click();
  await expect.poll(async () => (await state(page)).accountGets).toBeGreaterThan(1);
  await page.getByRole("button", { name: "패스키로 이 계좌번호만 확인", exact: true }).click();
  await expect
    .poll(async () =>
      (await state(page)).calls.some((call) => call.method === "showAccountNumberWithPasskeyUI"),
    )
    .toBe(true);
  await page.getByRole("link", { name: "계좌 정보 수정", exact: true }).click();
  await page.getByLabel("용도 (선택)", { exact: true }).fill("합성 네이티브 변경 용도");
  await page.getByRole("button", { name: "계좌 수정 저장", exact: true }).click();
  await expect(page.getByText("합성 네이티브 변경 용도", { exact: true })).toBeVisible();
  const calls = (await state(page)).calls.filter((call) => call.method === "updateAccount");
  expect(calls).toHaveLength(1);
  expect(calls[0]?.args).toEqual({
    accountId: uid(30),
    input: { purpose: "합성 네이티브 변경 용도" },
    ifMatch: '"1"',
  });
  await assertBoundary(page);
});

for (const scenario of ["conflict", "cancelled"] as const)
  test(`native edit ${scenario} refreshes masked metadata and uses the refreshed version`, async ({
    page,
  }) => {
    await nativeFinanceMock(page, scenario);
    await page.goto(`/accounts/${uid(30)}`);
    await page.getByRole("button", { name: "Android에서 계좌번호 관리", exact: true }).click();
    await expect(page.getByText("••••TEST", { exact: true })).toBeVisible();
    if (scenario === "conflict")
      await expect(page.getByRole("alert")).toContainText("다른 곳에서 정보가 변경");
    else await expect(page.getByText("계좌번호 작업을 취소했어요.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Android에서 계좌번호 관리", exact: true }).click();
    await expect
      .poll(
        async () =>
          (await state(page)).calls.filter((call) => call.method === "editAccountNumberUI").length,
      )
      .toBe(2);
    expect(
      (await state(page)).calls
        .filter((call) => call.method === "editAccountNumberUI")
        .map((call) => call.args.ifMatch),
    ).toEqual(['"1"', '"2"']);
    await assertBoundary(page);
  });

test("native recent-auth rejection retains metadata and permits scoped passkey UI", async ({
  page,
}) => {
  await nativeFinanceMock(page, "reauth");
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "Android에서 전체 계좌번호 보기", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "패스키로 이 계좌번호만 확인", exact: true }).click();
  await expect(page.getByText("계좌번호 작업을 마쳤어요.", { exact: true })).toBeVisible();
  await assertBoundary(page);
});

test("native account session expiry unmounts protected metadata", async ({ page }) => {
  await nativeFinanceMock(page, "expired");
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "Android에서 전체 계좌번호 보기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible();
  await expect(page.getByText("••••ONLY", { exact: true })).toHaveCount(0);
  await assertBoundary(page);
});

test("native misregistration deletes send only ids and versions through named commands", async ({
  page,
}) => {
  await nativeFinanceMock(page);
  await page.goto(`/assets/${uid(11)}`);
  await page.getByRole("button", { name: "오등록 삭제 검토", exact: true }).click();
  await page
    .getByLabel("잘못 등록한 자산이며 실제 삭제할 것을 확인했어요.", { exact: true })
    .check();
  await page.getByRole("button", { name: "오등록 자산 삭제", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("연결된 기록이 있어 삭제할 수 없어요");
  // A full page load restarts the synthetic bridge state, so each page's calls are read in turn.
  const deletes = async () =>
    (await state(page)).calls
      .filter((call) => call.method.startsWith("delete"))
      .map(({ method, args }) => ({ method, args }));
  const assetCalls = await deletes();
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "오등록 삭제 검토", exact: true }).click();
  await page
    .getByLabel("잘못 등록한 계좌이며 연결된 금융 자산과 함께 삭제할 것을 확인했어요.", {
      exact: true,
    })
    .check();
  await page.getByRole("button", { name: "오등록 계좌 삭제", exact: true }).click();
  await expect(
    page.getByText("계좌와 연결된 금융 자산이 삭제된 것을 확인했어요.", { exact: true }),
  ).toBeVisible();
  expect([...assetCalls, ...(await deletes())]).toEqual([
    { method: "deleteAsset", args: { assetId: uid(11), ifMatch: '"1"' } },
    { method: "deleteAccount", args: { accountId: uid(30), ifMatch: '"1"' } },
  ]);
  await assertBoundary(page);
});
