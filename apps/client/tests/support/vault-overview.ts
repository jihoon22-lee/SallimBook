import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockCashflow } from "./cashflow";
import { members, uid } from "./finance";
type S = components["schemas"];
export function share(
  id: number,
  patch: Partial<S["VaultShareResponse"]> = {},
): S["VaultShareResponse"] {
  return {
    id: uid(id),
    household_id: uid(3),
    source_member_id: uid(2),
    target_member_id: uid(5),
    key_version: 1,
    state: "pending",
    version: 1,
    closed_at: null,
    expires_at: "2030-02-20T03:00:00Z",
    ...patch,
  };
}
export async function mockVaultOverview(page: Page, native = false) {
  const cashflow = await mockCashflow(page);
  const state = {
    status: {
      id: uid(800),
      household_id: uid(3),
      initialized: true,
      own_membership: "active",
      current_key_version: 1,
      pending_rotation_id: null,
      rotation_required: false,
      version: 1,
      members: [
        { member_id: uid(2), status: "active", version: 1, next_wrapping_generation: 2 },
        { member_id: uid(5), status: "not_enrolled", version: null, next_wrapping_generation: 1 },
      ],
    } as S["VaultStatusResponse"],
    shares: [] as S["VaultShareResponse"][],
    pageSize: 50,
    rotation: {
      id: uid(801),
      household_id: uid(3),
      key_version: 2,
      source_key_version: 1,
      state: "staging",
      version: 1,
      key_check_prepared: true,
      recovery_prepared: false,
      cards: [
        {
          card_id: uid(50),
          last_four: "1111",
          prepared: false,
          source_envelope_id: uid(802),
          source_revision: 1,
        },
      ],
      members: [{ member_id: uid(2), prepared: true, source_membership_version: 1 }],
    } as S["VaultRotationResponse"],
    failRead: "",
    readFailureStatus: 503,
    actionFailure: "",
    actionStatus: "completed",
    delay: 0,
    cardDelay: 0,
    calls: [] as { method: string; args: Record<string, any> }[],
    http: [] as string[],
    reads: [] as string[],
    onAction: (_args: Record<string, any>) => {},
    cashflow,
  };
  const listShares = (cursor?: string) => {
    const start = cursor ? state.shares.findIndex((item) => item.id === cursor) + 1 : 0;
    const items = state.shares.slice(start, start + state.pageSize);
    return {
      items,
      next_cursor: start + items.length < state.shares.length ? items.at(-1)!.id : null,
    };
  };
  await page.route("**/api/v1/vault/**", async (route) => {
    const url = new URL(route.request().url());
    state.reads.push(url.pathname);
    if (state.failRead && url.pathname.endsWith(state.failRead))
      return route.fulfill({
        status: state.readFailureStatus,
        json: {
          error: {
            code: state.readFailureStatus === 401 ? "UNAUTHENTICATED" : "UNAVAILABLE",
            message: "UNTRUSTED_VAULT_DETAIL",
            request_id: "synthetic",
          },
        },
      });
    if (route.request().method() !== "GET")
      return route.fulfill({ status: 500, json: { error: { code: "UNAVAILABLE" } } });
    const body = url.pathname.endsWith("/status")
      ? state.status
      : url.pathname.endsWith("/shares")
        ? listShares(url.searchParams.get("cursor") ?? undefined)
        : state.rotation;
    return route.fulfill({ json: body, headers: { "Cache-Control": "no-store" } });
  });
  if (!native) return state;
  const metadata = (body: unknown) => ({ ok: true, value: { status: 200, body } });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) state.http.push(request.url());
  });
  await page.exposeFunction(
    "syntheticVaultOverview",
    async (method: string, args: Record<string, any>) => {
      state.calls.push({ method, args });
      if (method === "getSession")
        return { ok: true, value: { available: true, authenticated: true } };
      if (method === "request") return metadata(args.path === "/api/v1/me" ? members[0] : members);
      if (method === "openVaultUI") {
        if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay));
        if (state.actionFailure) return { ok: false, code: state.actionFailure };
        if (state.actionStatus === "completed") state.onAction(args);
        return { ok: true, value: { status: state.actionStatus } };
      }
      if (state.failRead === method) return { ok: false, code: "NETWORK_UNAVAILABLE" };
      if (method === "getVaultStatus") return metadata(state.status);
      if (method === "listVaultShares") return metadata(listShares(args.query?.cursor));
      if (method === "getVaultRotation") return metadata(state.rotation);
      if (method === "listCards") return metadata({ items: cashflow.cards, next_cursor: null });
      if (method === "getCard") {
        if (state.cardDelay) await new Promise((resolve) => setTimeout(resolve, state.cardDelay));
        return metadata(cashflow.cards.find((item) => item.id === args.cardId));
      }
      return { ok: false, code: "INVALID_REQUEST" };
    },
  );
  await page.addInitScript(() =>
    Object.assign(window, {
      CapacitorCustomPlatform: { name: "android" },
      Capacitor: {
        PluginHeaders: [
          {
            name: "SallimBookAuth",
            methods: [
              "getSession",
              "request",
              "openVaultUI",
              "getVaultStatus",
              "listVaultShares",
              "getVaultRotation",
              "listCards",
              "getCard",
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
            : (window as any).syntheticVaultOverview(method, args),
      },
    }),
  );
  return state;
}
