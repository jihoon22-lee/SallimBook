import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import catalog from "../../../../packages/test-fixtures/catalog.json" with { type: "json" };
import { mockHomecare, movementRow, type Result } from "./homecare";
import { uid } from "./finance";
type Order = components["schemas"]["ConsumableOrderResponse"];
export async function mockOrders(page: Page) {
  const state = await mockHomecare(page);
  const fixture = catalog.edge_cases.shared_purchase_plan;
  state.consumables[0]!.stock_quantity = fixture.stock_quantity;
  state.consumables[0]!.low_stock = true;
  const orders: Order[] = [];
  const control = {
    failAfter: "",
    conflict: "",
    planFailure: false,
    dateRace: false,
    unknown: false,
  };
  const baseHandle = state.handle;
  const completed = new Map<string, { fingerprint: string; result: Result }>();
  const reply = (body: unknown, status = 200): Result => ({ status, body: structuredClone(body) });
  const error = (code: string, status = 409) =>
    reply({ error: { code, message: "SYNTHETIC_ORDER_ERROR", request_id: "synthetic" } }, status);
  function pageRows<T extends { id: string }>(rows: T[], query: URLSearchParams) {
    const cursor = query.get("cursor");
    const start = cursor ? rows.findIndex((row) => row.id === cursor) + 1 : 0;
    const size = Math.min(state.pageSize, Number(query.get("limit") ?? 50));
    const items = rows.slice(start, start + size);
    return { items, next_cursor: start + size < rows.length ? items.at(-1)!.id : null };
  }
  function orderRow(id: number, stockId: string, patch: Partial<Order> = {}): Order {
    const stock = state.consumables.find((row) => row.id === stockId)!;
    return {
      id: uid(id),
      household_id: uid(3),
      version: 1,
      created_by_member_id: uid(2),
      updated_by_member_id: uid(2),
      created_at: "2026-10-17T00:00:00Z",
      updated_at: "2026-10-17T00:00:00Z",
      consumable_id: stockId,
      consumable_name: stock.name,
      unit: stock.unit,
      sku_or_model: stock.sku_or_model,
      quantity: 1,
      unit_cost_krw: null,
      purchase_url: null,
      note: null,
      state: "planned",
      ordered_on: null,
      ordered_by_member_id: null,
      received_on: null,
      received_by_member_id: null,
      stock_movement_id: null,
      receipt_reversed_by: null,
      cancel_reason: null,
      ...patch,
    };
  }
  state.handle = async (method, path, query = new URLSearchParams(), body = {}, headers = {}) => {
    if (path !== "/api/v1/homecare/purchase-plan" && !path.startsWith("/api/v1/consumable-orders"))
      return baseHandle(method, path, query, body, headers);
    if (method === "GET") {
      state.reads.push({ path, query });
      if (path.endsWith("purchase-plan")) {
        if (control.planFailure) return error("REQUEST_FAILED", 503);
        const stocks = state.consumables.filter(
          (row) =>
            !row.ended_on &&
            (!query.get("q") ||
              row.name.includes(query.get("q")!) ||
              row.sku_or_model?.includes(query.get("q")!)),
        );
        const paged = pageRows(stocks, query);
        const items = paged.items.map((stock) => {
          const open = orders.filter(
            (row) => row.consumable_id === stock.id && ["planned", "ordered"].includes(row.state),
          );
          const planned = open
            .filter((row) => row.state === "planned")
            .reduce((n, row) => n + row.quantity, 0);
          const ordered = open
            .filter((row) => row.state === "ordered")
            .reduce((n, row) => n + row.quantity, 0);
          const sources = state.links
            .filter((row) => row.consumable_id === stock.id)
            .map((link, i) => ({
              link_id: link.id,
              appliance_id: link.appliance_id,
              appliance_name: state.appliances.find((a) => a.id === link.appliance_id)!.name,
              next_check_on: control.unknown && i === 1 ? null : state.asOf,
              replacement_count: control.unknown && i === 1 ? null : 1,
              quantity: control.unknown && i === 1 ? null : 1,
            }));
          const demand = sources.reduce((n, row) => n + (row.quantity ?? 0), 0);
          const shortage = Math.max(0, demand - stock.stock_quantity);
          return {
            consumable: stock,
            demand_quantity: demand,
            shortage_quantity: shortage,
            planned_quantity: planned,
            ordered_quantity: ordered,
            additional_quantity: Math.max(0, shortage - planned - ordered),
            open_order_count: open.length,
            unscheduled_link_count: sources.filter((row) => row.quantity === null).length,
            demand_sources: sources,
            additional_source_count: 0,
            last_receipt: movementRow(400, {
              consumable_id: stock.id,
              kind: "receipt",
              quantity_delta: 1,
              unit_cost_krw: "0",
              purchase_url: "https://example.test/filter",
              occurred_on: "2026-10-16",
            }),
          };
        });
        return reply({
          as_of: control.dateRace && query.has("cursor") ? "2026-10-18" : state.asOf,
          through: query.get("through") ?? state.asOf,
          items,
          next_cursor: paged.next_cursor,
        });
      }
      const id = path.split("/")[4];
      if (id)
        return orders.find((row) => row.id === id)
          ? reply(orders.find((row) => row.id === id))
          : error("NOT_FOUND", 404);
      const filter = query.get("state") ?? "open";
      return reply(
        pageRows(
          orders.filter(
            (row) =>
              (!query.get("consumable_id") || row.consumable_id === query.get("consumable_id")) &&
              (filter === "all" || filter === "open"
                ? filter === "all" || ["planned", "ordered"].includes(row.state)
                : row.state === filter) &&
              (!query.get("q") ||
                row.consumable_name.includes(query.get("q")!) ||
                row.sku_or_model?.includes(query.get("q")!)),
          ),
          query,
        ),
      );
    }
    state.writes.push({
      method,
      path,
      body: structuredClone(body),
      key: headers["idempotency-key"],
      version: headers["if-match"],
    });
    const key = `${method}:${path}:${headers["idempotency-key"]}`;
    const fingerprint = JSON.stringify({ body, version: headers["if-match"] });
    if (headers["idempotency-key"] && completed.has(key)) {
      const prior = completed.get(key)!;
      return prior.fingerprint === fingerprint
        ? structuredClone(prior.result)
        : error("IDEMPOTENCY_CONFLICT");
    }
    const [, , , , id, action] = path.split("/");
    let result: Result;
    if (!id) {
      const row = orderRow(state.nextId++, body.consumable_id, body);
      orders.push(row);
      result = reply({ id: row.id, version: row.version }, 201);
    } else {
      const row = orders.find((order) => order.id === id);
      if (!row) return error("NOT_FOUND", 404);
      const stock = state.consumables.find((item) => item.id === row.consumable_id)!;
      if (control.conflict === (action ?? "edit")) {
        control.conflict = "";
        row.version++;
        row.updated_by_member_id = uid(5);
        row.note = "합성 배우자 메모";
        if (action === "receive") {
          row.quantity++;
          stock.stock_quantity++;
          stock.version++;
        }
        return error("VERSION_CONFLICT");
      }
      if (headers["if-match"] !== `"${row.version}"`) return error("VERSION_CONFLICT");
      if (!["planned", "ordered"].includes(row.state))
        return error("CONSUMABLE_ORDER_STATE_CONFLICT");
      if (!action) Object.assign(row, body);
      if (action === "submit") {
        row.state = "ordered";
        row.ordered_on = body.ordered_on;
        row.ordered_by_member_id = uid(2);
      }
      if (action === "cancel") {
        row.state = "cancelled";
        row.cancel_reason = body.reason;
      }
      if (action === "receive") {
        if (stock.version !== body.stock_version) return error("VERSION_CONFLICT");
        stock.stock_quantity += row.quantity;
        stock.version++;
        stock.low_stock = stock.stock_quantity <= stock.low_stock_threshold;
        row.state = "received";
        row.received_on = body.received_on;
        row.received_by_member_id = uid(2);
        row.stock_movement_id = uid(state.nextId++);
        state.movements.push(
          movementRow(state.nextId++, {
            id: row.stock_movement_id,
            consumable_id: stock.id,
            quantity_delta: row.quantity,
            occurred_on: body.received_on,
            stock_version: stock.version,
          }),
        );
      }
      row.version++;
      row.updated_by_member_id = uid(2);
      result = reply(action ? { id: row.id, version: row.version } : row);
    }
    if (headers["idempotency-key"]) completed.set(key, { fingerprint, result });
    if (control.failAfter === (action ?? "create")) {
      control.failAfter = "";
      return { status: 0, body: null, abort: true };
    }
    return result;
  };
  return { state, orders, control, orderRow };
}
