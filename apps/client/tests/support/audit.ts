import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { members, mockFinance, uid } from "./finance";
type Event = components["schemas"]["AuditEventResponse"];
export const auditRow = (id: number, patch: Partial<Event> = {}): Event => ({
  id: uid(id),
  actor_member_id: members[0]!.member_id,
  entity_type: "asset",
  entity_id: uid(10),
  action: "update",
  request_id: "synthetic-audit-request",
  before_version: 1,
  after_version: 2,
  occurred_at: "2026-10-17T15:01:02Z",
  changed_fields: ["name", "amount_krw"],
  ...patch,
});
export async function mockAudit(page: Page, native = false) {
  const finance = await mockFinance(page);
  const state = {
    finance,
    rows: [
      auditRow(9200),
      auditRow(9199, {
        entity_type: "user_export",
        action: "export",
        before_version: null,
        after_version: null,
        changed_fields: ["formats", "selected_documents"],
      }),
      auditRow(9198, {
        entity_type: "document",
        action: "delete",
        actor_member_id: members[1]!.member_id,
        request_id: null,
        changed_fields: [],
        occurred_at: "2026-10-16T00:00:00Z",
      }),
    ],
    queries: [] as Record<string, string>[],
    pageSize: 2,
    failure: "",
    failureStatus: 503,
    delay: 0,
    extraValues: false,
    duplicateMore: false,
    nativeFailure: "",
    nativeThrows: false,
    lockFailure: "",
    calls: [] as { method: string; args: Record<string, any> }[],
    http: [] as string[],
  };
  async function result(query: Record<string, string>) {
    state.queries.push({ ...query });
    const delay = state.delay;
    const selected = state.rows
      .filter((row) =>
        ["entity_type", "entity_id", "actor_member_id", "action"].every(
          (key) => !query[key] || row[key as keyof Event] === query[key],
        ),
      )
      .filter(
        (row) =>
          (!query.since || row.occurred_at >= query.since) &&
          (!query.until || row.occurred_at < query.until),
      );
    const start = query.cursor ? Number(query.cursor.slice("synthetic-next-".length)) : 0;
    const items = selected.slice(start, start + state.pageSize).map((row) =>
      state.extraValues
        ? {
            ...row,
            safe_diff: { note: "UNEXPECTED_PRIVATE_VALUE" },
            before: "UNEXPECTED_PRIVATE_VALUE",
          }
        : { ...row },
    );
    if (query.cursor && state.duplicateMore && selected[0]) items.unshift({ ...selected[0] });
    const body = state.failure
      ? {
          error: { code: state.failure, message: "UNTRUSTED_AUDIT_ERROR", request_id: "synthetic" },
        }
      : {
          items,
          next_cursor:
            start + state.pageSize < selected.length
              ? `synthetic-next-${start + state.pageSize}`
              : null,
        };
    const status = state.failure ? state.failureStatus : 200;
    if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    return { status, body };
  }
  await page.route("**/api/v1/audit-events**", async (route) => {
    if (state.failure === "network") {
      state.queries.push(Object.fromEntries(new URL(route.request().url()).searchParams));
      return route.abort("failed").catch(() => {});
    }
    const response = await result(Object.fromEntries(new URL(route.request().url()).searchParams));
    return route
      .fulfill({
        status: response.status,
        json: response.body,
        headers: { "Cache-Control": "no-store" },
      })
      .catch(() => {});
  });
  if (!native) return state;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) state.http.push(request.url());
  });
  await page.exposeFunction(
    "syntheticAuditNative",
    async (method: string, args: Record<string, any>) => {
      state.calls.push({ method, args });
      if (method === "getSession")
        return { ok: true, value: { available: true, authenticated: true } };
      if (method === "request")
        return {
          ok: true,
          value: { status: 200, body: args.path === "/api/v1/me" ? members[0] : members },
        };
      if (method === "lockApp")
        return state.lockFailure
          ? { ok: false, code: state.lockFailure }
          : { ok: true, value: { locked: true } };
      if (method !== "listAuditEvents") return { ok: false, code: "INVALID_REQUEST" };
      if (state.nativeThrows) throw new Error("Synthetic native method unavailable");
      if (state.nativeFailure) return { ok: false, code: state.nativeFailure };
      return {
        ok: true,
        value: await result(
          Object.fromEntries(
            Object.entries(args.query ?? {})
              .filter(([, value]) => value != null)
              .map(([key, value]) => [key, String(value)]),
          ),
        ),
      };
    },
  );
  await page.addInitScript(() =>
    Object.assign(window, {
      CapacitorCustomPlatform: { name: "android" },
      Capacitor: {
        PluginHeaders: [
          {
            name: "SallimBookAuth",
            methods: ["getSession", "request", "listAuditEvents", "lockApp"]
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
            : (window as any).syntheticAuditNative(method, args),
      },
    }),
  );
  return state;
}
