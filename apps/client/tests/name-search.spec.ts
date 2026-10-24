import { expect, test, type Page } from "@playwright/test";
import { mockHomecare, applianceRow, consumableRow } from "./support/homecare";
import { jointAsset, sampleAccount, members, householdPeople, uid } from "./support/finance";
import { sampleCard, ruleRow } from "./support/cashflow";
import { caseRow, policyRow } from "./support/insurance";
import { mockInsuranceEvents } from "./support/insurance-events";
import { mockNativeInsurance } from "./support/insurance-native";
import { mockCashflow } from "./support/cashflow";
import { mockNativeCashflow } from "./support/cashflow-native";

const cardRow = (id: number, patch: Partial<typeof sampleCard> = {}) => ({
  ...sampleCard,
  id: uid(id),
  ...patch,
});

const domains = [
  {
    path: "/assets",
    api: "/assets",
    method: "listAssets",
    label: "자산·부채 이름 검색",
    more: "자산 더 보기",
    row: (id: number, name: string) => ({ ...jointAsset, id: uid(id), name }),
  },
  {
    path: "/accounts",
    api: "/accounts",
    method: "listAccounts",
    label: "계좌 이름·금융기관 검색",
    more: "계좌 더 보기",
    row: (id: number, name: string) => ({
      ...sampleAccount,
      id: uid(id),
      asset: { ...sampleAccount.asset, name },
    }),
  },
  {
    path: "/cards",
    api: "/cards",
    method: "listCards",
    label: "카드 이름·카드사 검색",
    more: "카드 더 보기",
    row: (id: number, name: string) => cardRow(id, { alias: name }),
  },
  {
    path: "/insurance/policies",
    api: "/insurance/policies",
    method: "listInsurancePolicies",
    label: "보험 계약 이름·보험사 검색",
    more: "보험 계약 더 보기",
    row: (id: number, name: string) => ({ ...policyRow(id), product_name: name }),
  },
  {
    path: "/insurance/cases",
    api: "/insurance/cases",
    method: "listInsuranceCases",
    label: "보험 사건 이름 검색",
    more: "보험 사건 더 보기",
    row: (id: number, name: string) => ({ ...caseRow(id), title: name, net_burden_krw: null }),
  },
  {
    path: "/appliances",
    api: "/appliances",
    method: "listAppliances",
    label: "가전 이름·모델·장소 검색",
    more: "기록 더 보기",
    row: (id: number, name: string) => applianceRow(id, { name }),
  },
  {
    path: "/consumables",
    api: "/consumables",
    method: "listConsumables",
    label: "소모품 이름·규격 검색",
    more: "기록 더 보기",
    row: (id: number, name: string) => consumableRow(id, { name }),
  },
  {
    path: "/fixed-payments/rules",
    api: "/recurring-rules",
    method: "listRecurringRules",
    label: "납부 규칙 이름·변경 이력 검색",
    more: "규칙 더 보기",
    row: (id: number, name: string) => ruleRow(id, { title: name }),
  },
];
async function searchLists(page: Page, native: boolean) {
  const state = await mockHomecare(page);
  const reads: { path: string; query: URLSearchParams }[] = [];
  const requests: string[] = [];
  const rows = new Map(
    domains.map((domain) => [
      domain.api,
      Array.from({ length: 58 }, (_, i) =>
        domain.row(3000 + i, i >= 55 ? `합성 Needle %_ 이름 ${i}` : `합성 기타 ${i}`),
      ),
    ]),
  );
  const read = (path: string, query: URLSearchParams) => {
    const entries = rows.get(path);
    if (!entries) return null;
    reads.push({ path, query });
    const q = query.get("q")?.trim().toLowerCase();
    const matches = entries.filter((row) => !q || JSON.stringify(row).toLowerCase().includes(q));
    const start = query.has("cursor")
      ? matches.findIndex((row) => row.id === query.get("cursor")) + 1
      : 0;
    const size = q ? 2 : 50;
    const items = matches.slice(start, start + size);
    return { items, next_cursor: start + size < matches.length ? items.at(-1)!.id : null };
  };
  if (!native) {
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      const value = read(url.pathname.replace("/api/v1", ""), url.searchParams);
      return value ? route.fulfill({ json: value }) : route.fallback();
    });
  } else {
    page.on("request", (request) => {
      if (new URL(request.url()).pathname.startsWith("/api/")) requests.push(request.url());
    });
    await page.exposeFunction(
      "syntheticSearchNative",
      (method: string, args: Record<string, any>) => {
        const metadata = (body: unknown) => ({ ok: true, value: { status: 200, body } });
        if (method === "getSession")
          return { ok: true, value: { available: true, authenticated: true } };
        if (method === "request")
          return metadata(args.path === "/api/v1/me" ? members[0] : members);
        if (method === "listHouseholdPeople")
          return metadata({ items: householdPeople, next_cursor: null });
        if (method === "getHomecareStatus")
          return metadata({ as_of: state.asOf, items: [], next_cursor: null });
        const domain = domains.find((item) => item.method === method);
        if (domain)
          return metadata(
            read(
              domain.api,
              new URLSearchParams(
                Object.entries(args.query ?? {})
                  .filter(([, value]) => value !== undefined && value !== null)
                  .map(([key, value]) => [key, String(value)]),
              ),
            ),
          );
        return { ok: false, code: "INVALID_REQUEST" };
      },
    );
    await page.addInitScript(
      (methods) =>
        Object.assign(window, {
          CapacitorCustomPlatform: { name: "android" },
          Capacitor: {
            PluginHeaders: [
              {
                name: "SallimBookAuth",
                methods: [
                  ...methods,
                  "getSession",
                  "request",
                  "listHouseholdPeople",
                  "getHomecareStatus",
                ]
                  .map((name) => ({ name, rtype: "promise" }))
                  .concat([
                    { name: "addListener", rtype: "callback" },
                    { name: "removeListener", rtype: "promise" },
                  ]),
              },
            ],
            nativeCallback: () => "synthetic",
            nativePromise: (_plugin: string, method: string, args = {}) =>
              method === "removeListener"
                ? Promise.resolve()
                : (window as any).syntheticSearchNative(method, args),
          },
        }),
      domains.map((domain) => domain.method),
    );
  }
  return { reads, requests };
}
for (const native of [false, true]) {
  test(`eight server name searches include rows beyond fifty and preserve paging ${native ? "native" : "web"}`, async ({
    page,
  }) => {
    const state = await searchLists(page, native);
    for (const domain of domains) {
      await page.goto(domain.path + (domain.path === "/accounts" ? "?status=all" : ""));
      const search = page.getByRole("search", { name: domain.label, exact: true });
      await expect(
        page.getByRole("link", { name: "합성 Needle %_ 이름 55", exact: true }),
      ).toHaveCount(0);
      await search.getByRole("searchbox").fill("Needle %_");
      await search.getByRole("button", { name: "이름 검색", exact: true }).click();
      await expect(
        page.getByRole("link", { name: "합성 Needle %_ 이름 55", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("link", { name: "합성 Needle %_ 이름 57", exact: true }),
      ).toHaveCount(0);
      await page.getByRole("button", { name: domain.more, exact: true }).click();
      await expect(
        page.getByRole("link", { name: "합성 Needle %_ 이름 57", exact: true }),
      ).toBeVisible();
      expect(
        state.reads.some(
          (read) =>
            read.path === domain.api &&
            read.query.get("q") === "Needle %_" &&
            read.query.has("cursor"),
        ),
      ).toBe(true);
      if (["/appliances", "/consumables"].includes(domain.path)) {
        const label = domain.path === "/appliances" ? "가전 사용 상태" : "소모품 사용 상태";
        await page.getByRole("combobox", { name: label, exact: true }).selectOption("all");
        await expect(search.getByRole("searchbox")).toHaveValue("Needle %_");
        expect(new URL(page.url()).searchParams.get("status")).toBe("all");
        await expect(
          page.getByRole("link", { name: "합성 Needle %_ 이름 55", exact: true }),
        ).toBeVisible();
      }
      if (domain.path === "/accounts") {
        expect(new URL(page.url()).searchParams.get("status")).toBe("all");
        await page.getByRole("link", { name: "설정", exact: true }).last().click();
        await expect(page).toHaveURL(/\/settings$/);
        await page.goBack();
        await expect(search.getByRole("searchbox")).toHaveValue("Needle %_");
        await expect(
          page.getByRole("link", { name: "합성 Needle %_ 이름 57", exact: true }),
        ).toBeVisible();
        expect(new URL(page.url()).searchParams.get("status")).toBe("all");
      }
      await search.getByRole("button", { name: "검색 지우기" }).click();
      await expect(search.getByRole("searchbox")).toHaveValue("");
    }
    if (native) expect(state.requests).toEqual([]);
  });
  test(`account and card choices search all loaded rows with owner and status context ${native ? "native" : "web"}`, async ({
    page,
  }) => {
    const state = await mockCashflow(page);
    state.pageSize = 20;
    state.finance.accounts = Array.from({ length: 55 }, (_, i) => ({
      ...sampleAccount,
      id: uid(4000 + i),
      asset: { ...sampleAccount.asset, name: i === 54 ? "합성 마지막 계좌" : `합성 계좌 ${i}` },
    }));
    state.cards = Array.from({ length: 55 }, (_, i) =>
      cardRow(5000 + i, { alias: i === 54 ? "합성 마지막 카드" : `합성 카드 ${i}` }),
    );
    if (native) await mockNativeCashflow(page, state);
    else
      await page.route("**/api/v1/accounts?*", async (route) => {
        const query = new URL(route.request().url()).searchParams;
        const offset = query.has("cursor")
          ? state.finance.accounts.findIndex((row) => row.id === query.get("cursor")) + 1
          : 0;
        const items = state.finance.accounts.slice(offset, offset + 20);
        await route.fulfill({
          json: {
            items,
            next_cursor: offset + 20 < state.finance.accounts.length ? items.at(-1)!.id : null,
          },
        });
      });
    await page.goto("/income/new");
    await page.getByRole("searchbox", { name: "입금계좌 검색", exact: true }).fill("마지막");
    await page.getByRole("searchbox", { name: "입금계좌 검색", exact: true }).press("Enter");
    expect(state.writes).toHaveLength(0);
    const account = page.getByRole("combobox", { name: "입금계좌", exact: true });
    await expect(account.getByRole("option", { name: /합성 마지막 계좌/ })).toContainText(
      "합성 구성원 둘",
    );
    await account.selectOption(uid(4054));
    await page.getByRole("searchbox", { name: "입금계좌 검색", exact: true }).fill("없는이름");
    await expect(account).toHaveValue(uid(4054));
    await page.goto("/fixed-payments/rules/new");
    await page.getByRole("combobox", { name: "납부수단 구분", exact: true }).selectOption("card");
    await page.getByRole("searchbox", { name: "납부 카드 검색", exact: true }).fill("마지막");
    const card = page.getByRole("combobox", { name: "납부 카드", exact: true });
    await expect(card.getByRole("option", { name: /합성 마지막 카드/ })).toContainText("사용 중");
    await card.selectOption(uid(5054));
    await page.getByRole("searchbox", { name: "납부 카드 검색", exact: true }).fill("없는이름");
    await expect(card).toHaveValue(uid(5054));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
  test(`case and policy choices retain selection and expose family date and state ${native ? "native" : "web"}`, async ({
    page,
  }) => {
    const state = await mockInsuranceEvents(page);
    state.core.pageSize = 20;
    state.core.cases = Array.from({ length: 55 }, (_, i) => ({
      ...caseRow(6000 + i),
      title: i === 54 ? "합성 마지막 사건" : `합성 사건 ${i}`,
    }));
    state.core.policies = Array.from({ length: 55 }, (_, i) => ({
      ...policyRow(7000 + i),
      product_name: i === 54 ? "합성 마지막 계약" : `합성 계약 ${i}`,
      status: "ended" as const,
    }));
    if (native) await mockNativeInsurance(page, state);
    await page.goto("/insurance/claims/new");
    await page.getByRole("searchbox", { name: "청구 사건 검색", exact: true }).fill("마지막");
    const cases = page.getByRole("combobox", { name: "청구 사건", exact: true });
    await expect(cases.getByRole("option", { name: /합성 마지막 사건/ })).toContainText(
      "2025.02.01",
    );
    await cases.selectOption(uid(6054));
    await page.getByRole("searchbox", { name: "청구 보험계약 검색", exact: true }).fill("마지막");
    const policies = page.getByRole("combobox", { name: "청구 보험계약", exact: true });
    await expect(policies.getByRole("option", { name: /합성 마지막 계약/ })).toContainText(
      "2024.01.01",
    );
    await policies.selectOption(uid(7054));
    await expect(page.getByText(/선택한 계약은 계약 종료 상태/)).toBeVisible();
    await page.getByRole("searchbox", { name: "청구 보험계약 검색", exact: true }).fill("없는이름");
    await expect(policies).toHaveValue(uid(7054));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}
