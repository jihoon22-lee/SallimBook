import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockInsuranceEvents, claimRow } from "./insurance-events";
import { uid } from "./finance";
type S = components["schemas"];
export type Result = { status: number; body: unknown; abort?: boolean };
const timestamp = "2025-03-02T03:00:00Z";
const entity = (id: number) => ({
  id: uid(id),
  household_id: uid(3),
  version: 1,
  created_by_member_id: uid(2),
  updated_by_member_id: uid(2),
  created_at: timestamp,
  updated_at: timestamp,
});
export const applianceRow = (
  id = 100,
  patch: Partial<S["ApplianceResponse"]> = {},
): S["ApplianceResponse"] => ({
  ...entity(id),
  name: "합성 거실 청정기",
  manufacturer: "합성 제조사",
  model: "SYNTHETIC-AIR",
  location: "거실",
  purchased_on: "2024-01-01",
  purchase_price_krw: null,
  seller: null,
  warranty_until: "2025-12-31",
  ended_on: null,
  note: null,
  status: "active",
  warranty_status: "expired",
  as_of: "2026-10-17",
  ...patch,
});
export const consumableRow = (
  id = 200,
  patch: Partial<S["ConsumableResponse"]> = {},
): S["ConsumableResponse"] => ({
  ...entity(id),
  version: 7,
  name: "합성 공용 필터",
  sku_or_model: "SYNTHETIC-FILTER",
  unit: "개",
  low_stock_threshold: 1,
  stock_quantity: 3,
  low_stock: false,
  status: "active",
  ended_on: null,
  note: null,
  ...patch,
});
export const linkRow = (
  id = 300,
  patch: Partial<S["ApplianceConsumableResponse"]> = {},
): S["ApplianceConsumableResponse"] => ({
  ...entity(id),
  version: 3,
  appliance_id: uid(100),
  consumable_id: uid(200),
  interval_unit: "months",
  interval_count: 1,
  quantity_per_replacement: 1,
  next_check_override: null,
  active: true,
  note: null,
  last_replacement_id: uid(500),
  last_replaced_on: "2025-01-31",
  next_check_on: "2025-02-28",
  next_check_source: "replacement",
  stock_quantity: 3,
  stock_version: 7,
  as_of: "2026-10-17",
  replacement_due: true,
  purchase_needed: false,
  low_stock: false,
  ...patch,
});
export const replacementRow = (
  id = 500,
  patch: Partial<S["ReplacementResponse"]> = {},
): S["ReplacementResponse"] => ({
  id: uid(id),
  household_id: uid(3),
  appliance_consumable_id: uid(300),
  consumable_id: uid(200),
  stock_movement_id: uid(401),
  replaced_on: "2025-01-31",
  quantity: 1,
  note: null,
  created_by_member_id: uid(2),
  created_at: timestamp,
  cancelled_by_movement_id: null,
  ...patch,
});
export const movementRow = (
  id = 400,
  patch: Partial<S["StockMovementResponse"]> = {},
): S["StockMovementResponse"] => ({
  id: uid(id),
  household_id: uid(3),
  consumable_id: uid(200),
  kind: "receipt",
  quantity_delta: 4,
  occurred_on: "2025-01-01",
  unit_cost_krw: null,
  purchase_url: null,
  reversal_of: null,
  reason: null,
  note: null,
  stock_version: 6,
  created_by_member_id: uid(2),
  created_at: timestamp,
  reversed_by: null,
  ...patch,
});
export function homecareFixture() {
  const state = {
    appliances: [applianceRow(), applianceRow(101, { name: "합성 안방 청정기", location: "안방" })],
    consumables: [consumableRow()],
    links: [linkRow(), linkRow(301, { appliance_id: uid(101), interval_count: 2 })],
    movements: [
      movementRow(),
      movementRow(401, {
        kind: "replacement",
        quantity_delta: -1,
        occurred_on: "2025-01-31",
        stock_version: 7,
      }),
    ],
    replacements: [replacementRow()],
    reads: [] as { path: string; query: URLSearchParams }[],
    writes: [] as {
      method: string;
      path: string;
      body: Record<string, any>;
      key?: string;
      version?: string;
    }[],
    pageSize: 200,
    nextId: 2000,
    asOf: "2026-10-17",
    previousMonthState: "confirmed" as "confirmed" | "draft" | "reopened" | "missing",
    failure: "" as "" | "before" | "after",
    conflict: "",
    statusRace: false,
    statusFailure: false,
    documented: new Set<string>(),
  };
  const response = (body: unknown, status = 200): Result => ({
    status,
    body: structuredClone(body),
  });
  const error = (code: string, status = 409) =>
    response(
      { error: { code, message: "UNTRUSTED_HOMECARE_ERROR", request_id: "synthetic" } },
      status,
    );
  const pageRows = <T extends { id: string }>(rows: T[], query: URLSearchParams) => {
    const sorted = [...rows].sort((a, b) => a.id.localeCompare(b.id));
    const cursor = query.get("cursor");
    const offset = cursor ? sorted.findIndex((r) => r.id === cursor) + 1 : 0;
    const size = Math.min(state.pageSize, Number(query.get("limit") ?? 50));
    const items = sorted.slice(offset, offset + size);
    return { items, next_cursor: offset + size < sorted.length ? items.at(-1)!.id : null };
  };
  const stockView = (r: S["ConsumableResponse"]): S["ConsumableResponse"] => ({
    ...r,
    status: r.ended_on ? "ended" : "active",
    low_stock: r.stock_quantity <= r.low_stock_threshold,
  });
  const applianceView = (r: S["ApplianceResponse"]): S["ApplianceResponse"] => ({
    ...r,
    as_of: state.asOf,
    status: r.ended_on ? "ended" : "active",
    warranty_status: !r.warranty_until
      ? "unknown"
      : r.warranty_until < state.asOf
        ? "expired"
        : "active",
  });
  const linkView = (r: S["ApplianceConsumableResponse"]): S["ApplianceConsumableResponse"] => {
    const stock = state.consumables.find((s) => s.id === r.consumable_id)!;
    const last = state.replacements
      .filter((x) => x.appliance_consumable_id === r.id && !x.cancelled_by_movement_id)
      .sort((a, b) => b.replaced_on.localeCompare(a.replaced_on) || b.id.localeCompare(a.id))[0];
    let next = r.next_check_override ?? null;
    if (!next && last && r.interval_unit !== "manual") {
      const date = new Date(`${last.replaced_on}T00:00:00Z`);
      if (r.interval_unit === "days") date.setUTCDate(date.getUTCDate() + r.interval_count!);
      else {
        const day = date.getUTCDate();
        date.setUTCDate(1);
        date.setUTCMonth(date.getUTCMonth() + r.interval_count!);
        const end = new Date(
          Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0),
        ).getUTCDate();
        date.setUTCDate(Math.min(day, end));
      }
      next = date.toISOString().slice(0, 10);
    }
    return {
      ...r,
      as_of: state.asOf,
      last_replacement_id: last?.id ?? null,
      last_replaced_on: last?.replaced_on ?? null,
      next_check_on: next,
      next_check_source: r.next_check_override ? "override" : next ? "replacement" : "unknown",
      stock_quantity: stock.stock_quantity,
      stock_version: stock.version,
      low_stock: stock.stock_quantity <= stock.low_stock_threshold,
      replacement_due: next === null ? null : next <= state.asOf,
      purchase_needed: stock.stock_quantity < r.quantity_per_replacement,
    };
  };
  const receipts = new Map<string, { fingerprint: string; result: Result }>();
  async function handle(
    method: string,
    path: string,
    query = new URLSearchParams(),
    body: Record<string, any> = {},
    headers: Record<string, string> = {},
  ): Promise<Result | undefined> {
    if (!/^\/api\/v1\/(appliances|consumables|appliance-consumables|homecare)(\/|$)/.test(path))
      return undefined;
    const [, , , domain, id, action, childId, command] = path.split("/");
    const stock = state.consumables.find((r) => r.id === id);
    const appliance = state.appliances.find((r) => r.id === id);
    const link = state.links.find((r) => r.id === id);
    if (method === "GET") {
      state.reads.push({ path, query });
      if (domain === "homecare") {
        if (state.statusFailure) return error("UNAVAILABLE", 503);
        if (state.statusRace && query.has("cursor")) {
          state.statusRace = false;
          state.asOf = "2026-10-18";
        }
        const rows = state.links
          .filter(
            (r) =>
              r.active &&
              !state.appliances.find((a) => a.id === r.appliance_id)?.ended_on &&
              !state.consumables.find((c) => c.id === r.consumable_id)?.ended_on,
          )
          .map((r): S["HomecareStatusItem"] => {
            const a = state.appliances.find((a) => a.id === r.appliance_id)!;
            const c = state.consumables.find((c) => c.id === r.consumable_id)!;
            return {
              ...linkView(r),
              appliance_name: a.name,
              appliance_location: a.location ?? null,
              consumable_name: c.name,
              sku_or_model: c.sku_or_model ?? null,
              unit: c.unit,
              low_stock_threshold: c.low_stock_threshold,
            };
          });
        return response({ as_of: state.asOf, ...pageRows(rows, query) });
      }
      if (domain === "appliances") {
        if (id) return appliance ? response(applianceView(appliance)) : error("NOT_FOUND", 404);
        const rows = state.appliances
          .map(applianceView)
          .filter(
            (r) => query.get("status") === "all" || r.status === (query.get("status") ?? "active"),
          );
        return response(pageRows(rows, query));
      }
      if (domain === "consumables") {
        if (!id)
          return response(
            pageRows(
              state.consumables
                .map(stockView)
                .filter(
                  (r) =>
                    query.get("status") === "all" || r.status === (query.get("status") ?? "active"),
                ),
              query,
            ),
          );
        if (!stock) return error("NOT_FOUND", 404);
        if (action === "stock-movements") {
          const rows = state.movements.filter((r) => r.consumable_id === stock.id);
          const row = rows.find((r) => r.id === childId);
          return childId
            ? row
              ? response(row)
              : error("NOT_FOUND", 404)
            : response(pageRows(rows, query));
        }
        return response(stockView(stock));
      }
      if (domain === "appliance-consumables") {
        if (!id)
          return response(
            pageRows(
              state.links
                .filter(
                  (r) =>
                    (!query.has("appliance_id") || r.appliance_id === query.get("appliance_id")) &&
                    (!query.has("consumable_id") ||
                      r.consumable_id === query.get("consumable_id")) &&
                    (!query.has("active") || r.active === (query.get("active") === "true")),
                )
                .map(linkView),
              query,
            ),
          );
        if (!link) return error("NOT_FOUND", 404);
        if (action === "replacements") {
          const rows = state.replacements.filter((r) => r.appliance_consumable_id === link.id);
          const row = rows.find((r) => r.id === childId);
          return childId
            ? row
              ? response(row)
              : error("NOT_FOUND", 404)
            : response(pageRows(rows, query));
        }
        return response(linkView(link));
      }
      return error("NOT_FOUND", 404);
    }
    const key = headers["idempotency-key"],
      version = headers["if-match"];
    state.writes.push({ method, path, body: structuredClone(body), key, version });
    const fingerprint = JSON.stringify([method, version, body]);
    const receiptId = `${path}:${key}`;
    if (key && receipts.has(receiptId)) {
      const old = receipts.get(receiptId)!;
      return old.fingerprint === fingerprint
        ? structuredClone(old.result)
        : error("IDEMPOTENCY_CONFLICT");
    }
    if (state.failure === "before") {
      state.failure = "";
      return { status: 0, body: null, abort: true };
    }
    const finish = (result: Result) => {
      if (key && result.status < 300)
        receipts.set(receiptId, { fingerprint, result: structuredClone(result) });
      if (state.failure === "after" && result.status < 300) {
        state.failure = "";
        return { status: 0, body: null, abort: true };
      }
      return result;
    };
    if (!action && method === "POST") {
      if (domain === "appliances") {
        const row = applianceRow(state.nextId++, body);
        state.appliances.push(row);
        return finish(response(applianceView(row), 201));
      }
      if (domain === "consumables") {
        if (
          body.sku_or_model &&
          state.consumables.some((r) => r.sku_or_model === body.sku_or_model)
        )
          return error("CONSUMABLE_SKU_EXISTS");
        const row = consumableRow(state.nextId++, { ...body, stock_quantity: 0, version: 1 });
        state.consumables.push(row);
        return finish(response(stockView(row), 201));
      }
      if (domain === "appliance-consumables") {
        if (
          state.links.some(
            (r) => r.appliance_id === body.appliance_id && r.consumable_id === body.consumable_id,
          )
        )
          return error("APPLIANCE_CONSUMABLE_EXISTS");
        const row = linkRow(state.nextId++, { ...body, version: 1 });
        state.links.push(row);
        return finish(response(linkView(row), 201));
      }
    }
    if (!action && (method === "PATCH" || method === "DELETE")) {
      const row = domain === "appliances" ? appliance : domain === "consumables" ? stock : link;
      if (!row) return error("NOT_FOUND", 404);
      if (state.conflict === domain) {
        state.conflict = "";
        row.note = "배우자가 작성한 합성 메모";
        row.version++;
      }
      if (version !== `"${row.version}"`) return error("VERSION_CONFLICT");
      if (method === "DELETE") {
        const linked =
          domain === "appliances"
            ? state.links.some((r) => r.appliance_id === id)
            : domain === "consumables"
              ? state.links.some((r) => r.consumable_id === id) ||
                state.movements.some((r) => r.consumable_id === id)
              : state.replacements.some((r) => r.appliance_consumable_id === id);
        if (linked || state.documented.has(id!))
          return error(
            domain === "appliances"
              ? "APPLIANCE_IN_USE"
              : domain === "consumables"
                ? "CONSUMABLE_IN_USE"
                : "APPLIANCE_CONSUMABLE_IN_USE",
          );
        if (domain === "appliances") state.appliances = state.appliances.filter((r) => r.id !== id);
        else if (domain === "consumables")
          state.consumables = state.consumables.filter((r) => r.id !== id);
        else state.links = state.links.filter((r) => r.id !== id);
        return finish(response(null, 204));
      }
      if (
        domain === "consumables" &&
        body.unit &&
        body.unit !== stock!.unit &&
        state.movements.some((r) => r.consumable_id === id)
      )
        return error("CONSUMABLE_UNIT_IN_USE");
      Object.assign(row, body, { version: row.version + 1 });
      return finish(
        response(
          domain === "appliances"
            ? applianceView(appliance!)
            : domain === "consumables"
              ? stockView(stock!)
              : linkView(link!),
        ),
      );
    }
    const sourceStock = stock ?? state.consumables.find((r) => r.id === link?.consumable_id);
    if (!sourceStock) return error("NOT_FOUND", 404);
    if (state.conflict === "stock") {
      state.conflict = "";
      sourceStock.stock_quantity++;
      sourceStock.version++;
    }
    if (state.conflict === "link" && link) {
      state.conflict = "";
      link.note = "배우자 주기 합성 메모";
      link.version++;
    }
    if (action === "replacements" && !command && body.quantity > sourceStock.stock_quantity)
      return error("INSUFFICIENT_STOCK");
    if (version !== `"${sourceStock.version}"`) return error("VERSION_CONFLICT");
    const mutation = (
      kind: S["StockMovementResponse"]["kind"],
      delta: number,
      date: string,
      patch: Partial<S["StockMovementResponse"]> = {},
    ) => {
      sourceStock.stock_quantity += delta;
      sourceStock.version++;
      const row = movementRow(state.nextId++, {
        ...patch,
        consumable_id: sourceStock.id,
        kind,
        quantity_delta: delta,
        occurred_on: date,
        stock_version: sourceStock.version,
      });
      state.movements.push(row);
      return row;
    };
    const ref = (movement: S["StockMovementResponse"], replacementId: string | null = null) =>
      response(
        {
          id: movement.id,
          consumable_id: sourceStock.id,
          stock_version: movement.stock_version,
          replacement_id: replacementId,
        },
        command ? 200 : 201,
      );
    if (command === "cancel") {
      const replacement =
        action === "replacements"
          ? state.replacements.find((r) => r.id === childId && r.appliance_consumable_id === id)
          : undefined;
      const original = state.movements.find(
        (r) =>
          r.id === (replacement?.stock_movement_id ?? childId) &&
          r.consumable_id === sourceStock.id,
      );
      if (!original) return error("NOT_FOUND", 404);
      if (original.reversed_by) return error("STOCK_MOVEMENT_ALREADY_REVERSED");
      if (original.kind === "replacement" && !replacement)
        return error("REPLACEMENT_CANCEL_REQUIRED");
      if (sourceStock.stock_quantity - original.quantity_delta < 0)
        return error("INSUFFICIENT_STOCK");
      const row = mutation("reversal", -original.quantity_delta, body.occurred_on, {
        reason: body.reason,
        reversal_of: original.id,
      });
      original.reversed_by = row.id;
      if (replacement) replacement.cancelled_by_movement_id = row.id;
      return finish(ref(row, replacement?.id ?? null));
    }
    if (sourceStock.ended_on) return error("CONSUMABLE_UNAVAILABLE");
    if (action === "stock-movements") {
      if (sourceStock.stock_quantity + body.quantity_delta < 0) return error("INSUFFICIENT_STOCK");
      return finish(ref(mutation(body.kind, body.quantity_delta, body.occurred_on, { ...body })));
    }
    if (action === "replacements" && link) {
      if (!link.active) return error("APPLIANCE_CONSUMABLE_UNAVAILABLE");
      if (state.appliances.find((a) => a.id === link.appliance_id)?.ended_on)
        return error("APPLIANCE_UNAVAILABLE");
      if (body.link_version !== link.version) return error("VERSION_CONFLICT");
      const row = mutation("replacement", -body.quantity, body.replaced_on, { note: body.note });
      const replacement = replacementRow(state.nextId++, {
        appliance_consumable_id: link.id,
        consumable_id: sourceStock.id,
        stock_movement_id: row.id,
        replaced_on: body.replaced_on,
        quantity: body.quantity,
        note: body.note,
      });
      state.replacements.push(replacement);
      if (body.clear_next_check_override && link.next_check_override) {
        link.next_check_override = null;
        link.version++;
      }
      return finish(ref(row, replacement.id));
    }
    return error("NOT_FOUND", 404);
  }
  return Object.assign(state, { handle, linkView, stockView });
}
export async function mockHomecare(page: Page) {
  const insurance = await mockInsuranceEvents(page);
  insurance.claims.push(claimRow(), claimRow(1201));
  const state = homecareFixture();
  const trendResponse = (query: URLSearchParams): S["AssetTrendResponse"] => {
    const month = query.get("from")!;
    const period = homeComparison(month).current;
    const missing = state.previousMonthState === "missing";
    return {
      from_month: month,
      to_month: query.get("to")!,
      filters: {},
      series_kind: "household_net_assets",
      points: [
        {
          month,
          state: state.previousMonthState,
          revision: missing ? null : period.revision,
          totals: missing ? null : period.totals,
          value_state: missing ? "missing_month" : "unconfirmed",
          observed_amount_krw: missing ? null : "4000000",
          confirmed_amount_krw: state.previousMonthState === "confirmed" ? "4000000" : null,
          included_in_total: missing ? null : true,
          as_of_date: null,
          dates: period.dates,
        },
      ],
    };
  };
  await page.route("**/api/v1/asset-trends?*", (route) =>
    route.fulfill({ json: trendResponse(new URL(route.request().url()).searchParams) }),
  );

  await page.route("**/api/v1/asset-comparison?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    state.reads.push({ path: "/api/v1/asset-comparison", query });
    return route.fulfill({ json: homeComparison(query.get("to") ?? "2025-01") });
  });
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const result = await state.handle(
      route.request().method(),
      url.pathname,
      url.searchParams,
      route.request().postDataJSON() ?? {},
      route.request().headers(),
    );
    if (!result) return route.fallback();
    if (result.abort) return route.abort("failed");
    if (result.status === 204) return route.fulfill({ status: 204 });
    return route.fulfill({ status: result.status, json: result.body });
  });
  return Object.assign(state, { insurance, cashflow: insurance.cashflow, trendResponse });
}
export function homeComparison(month: string): S["AssetComparisonResponse"] {
  const dates = {
    non_month_end_asset_ids: [],
    missing_date_asset_ids: [uid(11)],
    mixed_dates: false,
  };
  const current: S["ComparisonPeriod"] = {
    month,
    state: "draft",
    confirmed_at: null,
    dates,
    revision: { month, revision_id: uid(9000), revision_no: 1, version: 3 },
    totals: {
      assets_krw: "5000000",
      liabilities_krw: "1000000",
      net_assets_krw: "4000000",
      provisional: true,
      item_count: 3,
      verified_count: 1,
      missing_count: 1,
      carried_count: 1,
    },
  };
  return {
    from_month: "2024-12",
    to_month: month,
    filters: {},
    state: "unconfirmed",
    current,
    previous: {
      ...current,
      month: "2024-12",
      state: "confirmed",
      revision: { month: "2024-12", revision_id: uid(8999), revision_no: 1, version: 2 },
      totals: {
        ...current.totals!,
        provisional: false,
        item_count: 3,
        verified_count: 3,
        missing_count: 0,
        carried_count: 0,
      },
    },
    total_delta_krw: null,
    common_scope_delta_krw: null,
    change_percent: null,
    change_percent_unavailable_reason: "unconfirmed",
    scope_changed: null,
    added_asset_ids: [],
    removed_asset_ids: [],
    changed_share_asset_ids: [],
    item_count: 3,
    items: [],
    next_cursor: null,
  };
}
