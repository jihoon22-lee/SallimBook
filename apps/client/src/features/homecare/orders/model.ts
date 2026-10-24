import type { components } from "@sallimbook/api-client";
import { ApiError } from "../../../platform/api";
import { parseKrw } from "../../assets/months/model";
import { purchaseUrl, quantity } from "../model";
export type Order = components["schemas"]["ConsumableOrderResponse"];
export type Plan = components["schemas"]["PurchasePlanResponse"];
export type PlanItem = components["schemas"]["PurchasePlanItem"];
export type OrderInput = Omit<components["schemas"]["ConsumableOrderCreate"], "consumable_id">;
export const orderStates = {
  planned: "구매 예정",
  ordered: "주문 중",
  received: "입고 완료",
  cancelled: "취소됨",
} as const;
export const count = (value: number) => value.toLocaleString("ko-KR");
export type OrderDraft = { quantity: string; price: string; url: string; note: string };
export function orderDraft(
  row?: Pick<Order, "quantity" | "unit_cost_krw" | "purchase_url" | "note">,
): OrderDraft {
  return {
    quantity: row ? String(row.quantity) : "",
    price: row?.unit_cost_krw ?? "",
    url: row?.purchase_url ?? "",
    note: row?.note ?? "",
  };
}
export function orderInput(draft: OrderDraft): OrderInput | null {
  const qty = quantity(draft.quantity, true);
  const price = draft.price ? parseKrw(draft.price) : null;
  if (
    qty === null ||
    (draft.price && price === null) ||
    (draft.url && !purchaseUrl(draft.url)) ||
    draft.note.length > 2000
  )
    return null;
  return {
    quantity: qty,
    unit_cost_krw: price,
    purchase_url: draft.url || null,
    note: draft.note.trim() || null,
  };
}
export async function completePlan(read: (cursor?: string) => Promise<Plan>): Promise<Plan> {
  const first = await read();
  const items = [...first.items];
  const ids = new Set(items.map((item) => item.consumable.id));
  if (ids.size !== items.length) throw new ApiError(409, "VERSION_CONFLICT");
  const cursors = new Set<string>();
  let cursor = first.next_cursor;
  while (cursor) {
    if (cursors.has(cursor) || cursors.size >= 100) throw new ApiError(0, "REQUEST_FAILED");
    cursors.add(cursor);
    const page = await read(cursor);
    if (page.as_of !== first.as_of || page.through !== first.through)
      throw new ApiError(409, "VERSION_CONFLICT");
    for (const row of page.items) {
      if (ids.has(row.consumable.id)) throw new ApiError(409, "VERSION_CONFLICT");
      ids.add(row.consumable.id);
      items.push(row);
    }
    cursor = page.next_cursor;
  }
  return { ...first, items, next_cursor: null };
}
export function daysAfter(day: string, days: number): string {
  const value = new Date(`${day}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}
