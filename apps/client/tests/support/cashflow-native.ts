import type { Page } from "@playwright/test";
import { members } from "./finance";
import type { mockCashflow } from "./cashflow";
type State = Awaited<ReturnType<typeof mockCashflow>>;
type Args = Record<string, any>;
export async function mockNativeCashflow(
  page: Page,
  state: State,
  failure?: "APP_LOCKED" | "SESSION_EXPIRED" | "NETWORK_UNAVAILABLE",
) {
  const calls: { method: string; args: Args }[] = [];
  const http: string[] = [];
  const mapping: Record<string, { method: string; path: (args: Args) => string }> = {
    listIncome: { method: "GET", path: () => "/income" },
    incomeSummary: { method: "GET", path: () => "/income/summary" },
    incomeDuplicateCandidates: { method: "GET", path: () => "/income/duplicates" },
    getIncomeInsuranceSource: {
      method: "GET",
      path: (a) => `/income/${a.recordId}/insurance-source`,
    },
    getRecurringRuleInsuranceLink: {
      method: "GET",
      path: (a) => `/recurring-rules/${a.ruleId}/insurance-link`,
    },
    getIncome: { method: "GET", path: (a) => `/income/${a.recordId}` },
    incomeHistory: { method: "GET", path: (a) => `/income/${a.recordId}/history` },
    createIncome: { method: "POST", path: () => "/income" },
    correctIncome: { method: "PATCH", path: (a) => `/income/${a.recordId}` },
    voidIncome: { method: "POST", path: (a) => `/income/${a.recordId}/void` },
    returnIncome: { method: "POST", path: (a) => `/income/${a.recordId}/returns` },
    convertIncomePrecision: { method: "POST", path: () => "/income/convert" },
    listCards: { method: "GET", path: () => "/cards" },
    getCard: { method: "GET", path: (a) => `/cards/${a.cardId}` },
    createCard: { method: "POST", path: () => "/cards" },
    updateCard: { method: "PATCH", path: (a) => `/cards/${a.cardId}` },
    archiveCard: { method: "POST", path: (a) => `/cards/${a.cardId}/archive` },
    deleteCard: { method: "DELETE", path: (a) => `/cards/${a.cardId}` },
    listRecurringRules: { method: "GET", path: () => "/recurring-rules" },
    getRecurringRule: { method: "GET", path: (a) => `/recurring-rules/${a.ruleId}` },
    createRecurringRule: { method: "POST", path: () => "/recurring-rules" },
    changeRecurringRule: { method: "PATCH", path: (a) => `/recurring-rules/${a.ruleId}` },
    endRecurringRule: { method: "POST", path: (a) => `/recurring-rules/${a.ruleId}/end` },
    deleteRecurringRule: { method: "DELETE", path: (a) => `/recurring-rules/${a.ruleId}` },
    generateObligations: { method: "POST", path: () => "/obligations/generate" },
    listObligations: { method: "GET", path: () => "/obligations" },
    fixedCostSummary: { method: "GET", path: () => "/obligations/summary" },
    getObligation: { method: "GET", path: (a) => `/obligations/${a.obligationId}` },
    obligationHistory: { method: "GET", path: (a) => `/obligations/${a.obligationId}/history` },
    rescheduleObligation: { method: "PATCH", path: (a) => `/obligations/${a.obligationId}` },
    skipObligation: { method: "POST", path: (a) => `/obligations/${a.obligationId}/skip` },
    unskipObligation: { method: "POST", path: (a) => `/obligations/${a.obligationId}/unskip` },
    completeObligation: { method: "POST", path: (a) => `/obligations/${a.obligationId}/complete` },
    reopenObligation: { method: "POST", path: (a) => `/obligations/${a.obligationId}/reopen` },
    settleObligation: { method: "POST", path: (a) => `/obligations/${a.obligationId}/settlements` },
    listObligationSettlements: {
      method: "GET",
      path: (a) => `/obligations/${a.obligationId}/settlements`,
    },
    voidFixedSettlement: { method: "POST", path: (a) => `/settlements/${a.settlementId}/void` },
    getCardPaymentLinks: { method: "GET", path: (a) => `/cards/${a.resourceId}/payment-links` },
    getAccountPaymentLinks: {
      method: "GET",
      path: (a) => `/accounts/${a.resourceId}/payment-links`,
    },
    archiveAsset: { method: "POST", path: (a) => `/assets/${a.assetId}/archive` },
    updateAsset: { method: "PATCH", path: (a) => `/assets/${a.assetId}` },
  };
  const metadata = (body: unknown, status = 200) => ({ ok: true, value: { status, body } });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) http.push(request.url());
  });
  await page.exposeFunction("syntheticCashflowNative", async (method: string, args: Args) => {
    calls.push({ method, args });
    if (method === "getSession")
      return { ok: true, value: { available: true, authenticated: true } };
    if (method === "request") return metadata(args.path === "/api/v1/me" ? members[0] : members);
    if (failure) return { ok: false, code: failure };
    if (method === "listAccounts")
      return metadata({ items: state.finance.accounts, next_cursor: null });
    if (method === "getAccount")
      return metadata(state.finance.accounts.find((row) => row.id === args.accountId));
    if (method === "listAssets")
      return metadata({
        items: state.finance.assets.filter(
          (row) => !args.query?.kind || row.kind === args.query.kind,
        ),
        next_cursor: null,
      });
    if (method === "getAsset")
      return metadata(state.finance.assets.find((row) => row.id === args.assetId));
    if (method === "getAssetComparison") {
      const query = args.query;
      const period = (month: string) => ({
        month,
        state: "missing",
        revision: null,
        confirmed_at: null,
        totals: null,
        dates: { non_month_end_asset_ids: [], missing_date_asset_ids: [], mixed_dates: false },
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
    if (method === "getAssetTrends")
      return metadata({
        from_month: args.query.from,
        to_month: args.query.to,
        filters: {},
        series_kind: "asset_owned_amount",
        points: [],
      });
    const route = mapping[method];
    if (!route) return { ok: false, code: "INVALID_REQUEST" };
    const query = new URLSearchParams(
      Object.fromEntries(
        Object.entries(args.query ?? {})
          .filter(([, value]) => value !== undefined && value !== null)
          .map(([key, value]) => [key, String(value)]),
      ),
    );
    const result = await state.handle(
      route.method,
      `/api/v1${route.path(args)}`,
      query,
      args.input ?? {},
      {
        ...(args.idempotencyKey ? { "idempotency-key": args.idempotencyKey } : {}),
        ...(args.ifMatch ? { "if-match": args.ifMatch } : {}),
      },
    );
    return result?.abort
      ? { ok: false, code: "NETWORK_UNAVAILABLE" }
      : result
        ? metadata(result.body, result.status)
        : { ok: false, code: "INVALID_REQUEST" };
  });
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
                "listAccounts",
                "getAccount",
                "listAssets",
                "getAsset",
                "getAssetComparison",
                "getAssetTrends",
              ]
                .map((name) => ({ name, rtype: "promise" }))
                .concat([
                  { name: "addListener", rtype: "callback" },
                  { name: "removeListener", rtype: "promise" },
                ]),
            },
          ],
          nativeCallback: () => "synthetic-listener",
          nativePromise: (_plugin: string, method: string, args = {}) =>
            method === "removeListener"
              ? Promise.resolve()
              : (window as any).syntheticCashflowNative(method, args),
        },
      }),
    Object.keys(mapping),
  );
  return { calls, http };
}
