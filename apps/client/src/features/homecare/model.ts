import type { components } from "@sallimbook/api-client";
import { parseKrw } from "../assets/months/model";
import { isDateOnly, todaySeoul } from "../finance/dates";
export type Schema = components["schemas"];
export type Appliance = Schema["ApplianceResponse"];
export type Consumable = Schema["ConsumableResponse"];
export type DeviceLink = Schema["ApplianceConsumableResponse"];
export type Movement = Schema["StockMovementResponse"];
export type Replacement = Schema["ReplacementResponse"];
export const statuses = { active: "사용 중", ended: "사용 종료", all: "모두" } as const;
export const warrantyLabels = { unknown: "보증기한 미입력", active: "보증기간 안", expired: "보증기간 지남" } as const;
export const intervals = { manual: "직접 확인", days: "일 간격", months: "개월 간격" } as const;
export const movementLabels = { receipt: "입고", replacement: "교체 사용", return_in: "반품 입고", return_out: "반품 출고", adjustment: "재고 조정", reversal: "취소 보정" } as const;
export const optional = (value: string) => value.trim() || null;
export const etag = (version: number) => `"${version}"`;
export function quantity(value: string, positive = false, maximum = 1000000): number | null {
  if (!/^(?:0|[1-9]\d*)$/.test(value)) return null;
  const parsed = Number(value); return Number.isSafeInteger(parsed) && parsed >= (positive ? 1 : 0) && parsed <= maximum ? parsed : null;
}
const actualDate = (value: string) => !value || isDateOnly(value) && value <= todaySeoul();
const bounded = (value: string, limit = 120) => value.trim().length <= limit;
export function changedFields<T extends object>(base: T, draft: T): Partial<T> { return Object.fromEntries(Object.entries(draft).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(base[key as keyof T]))) as Partial<T>; }
export function preserveDraft<T extends object>(base: T, draft: T, latest: T): T { return { ...latest, ...changedFields(base, draft) }; }
export type ApplianceDraft = { name: string; manufacturer: string; model: string; location: string; purchased: string; price: string; seller: string; warranty: string; ended: string; note: string };
export function applianceDraft(row?: Appliance): ApplianceDraft { return { name: row?.name ?? "", manufacturer: row?.manufacturer ?? "", model: row?.model ?? "", location: row?.location ?? "", purchased: row?.purchased_on ?? "", price: row?.purchase_price_krw ?? "", seller: row?.seller ?? "", warranty: row?.warranty_until ?? "", ended: row?.ended_on ?? "", note: row?.note ?? "" }; }
export function applianceInput(d: ApplianceDraft): Schema["ApplianceInput"] | null {
  if (!d.name.trim() || ![d.name, d.manufacturer, d.model, d.location, d.seller].every((v) => bounded(v)) || !actualDate(d.purchased) || !actualDate(d.ended) || d.purchased && d.ended && d.ended < d.purchased || d.warranty && !isDateOnly(d.warranty) || d.price && parseKrw(d.price) === null || d.note.length > 2000) return null;
  return { name: d.name.trim(), manufacturer: optional(d.manufacturer), model: optional(d.model), location: optional(d.location), purchased_on: optional(d.purchased), purchase_price_krw: d.price ? parseKrw(d.price) : null, seller: optional(d.seller), warranty_until: optional(d.warranty), ended_on: optional(d.ended), note: optional(d.note) };
}
export type ConsumableDraft = { name: string; sku: string; unit: string; threshold: string; ended: string; note: string };
export function consumableDraft(row?: Consumable): ConsumableDraft { return { name: row?.name ?? "", sku: row?.sku_or_model ?? "", unit: row?.unit ?? "개", threshold: String(row?.low_stock_threshold ?? 0), ended: row?.ended_on ?? "", note: row?.note ?? "" }; }
export function consumableInput(d: ConsumableDraft): Schema["ConsumableInput"] | null {
  const threshold = quantity(d.threshold); if (!d.name.trim() || !bounded(d.name) || !bounded(d.sku) || !d.unit.trim() || !bounded(d.unit, 40) || threshold === null || !actualDate(d.ended) || d.note.length > 2000) return null;
  return { name: d.name.trim(), sku_or_model: optional(d.sku), unit: d.unit.trim(), low_stock_threshold: threshold, ended_on: optional(d.ended), note: optional(d.note) };
}
export type LinkDraft = { interval: DeviceLink["interval_unit"]; count: string; quantity: string; override: string; active: boolean; note: string };
export function linkDraft(row?: DeviceLink): LinkDraft { return { interval: row?.interval_unit ?? "manual", count: row?.interval_count?.toString() ?? "", quantity: String(row?.quantity_per_replacement ?? 1), override: row?.next_check_override ?? "", active: row?.active ?? true, note: row?.note ?? "" }; }
export function linkInput(d: LinkDraft): Omit<Schema["ApplianceConsumableCreate"], "appliance_id" | "consumable_id"> | null {
  const count = d.interval === "manual" ? null : quantity(d.count, true, d.interval === "months" ? 120 : 3650); const amount = quantity(d.quantity, true);
  if (d.interval !== "manual" && count === null || amount === null || d.override && !isDateOnly(d.override) || d.note.length > 2000) return null;
  return { interval_unit: d.interval, interval_count: count, quantity_per_replacement: amount, next_check_override: optional(d.override), active: d.active, note: optional(d.note) };
}
export type MovementDraft = { kind: Schema["StockMovementCreate"]["kind"]; quantity: string; date: string; price: string; url: string; reason: string; note: string };
export function purchaseUrl(value: string): boolean { try { const url = new URL(value); return url.protocol === "https:" && !!url.hostname && !url.username && !url.password && !/[\s\x00-\x1f]/.test(value) && value.length <= 2048; } catch { return false; } }
export function movementInput(d: MovementDraft): Schema["StockMovementCreate"] | null {
  const amount = quantity(d.kind === "adjustment" ? d.quantity.replace(/^-/, "") : d.quantity, true);
  if (amount === null || !d.date || !actualDate(d.date) || d.price && parseKrw(d.price) === null || d.url && !purchaseUrl(d.url) || d.note.length > 2000 || d.reason.trim().length > 500 || d.kind === "adjustment" && !d.reason.trim()) return null;
  return { kind: d.kind, quantity_delta: d.kind === "return_out" || d.kind === "adjustment" && d.quantity.startsWith("-") ? -amount : amount, occurred_on: d.date, unit_cost_krw: d.price ? parseKrw(d.price) : null, purchase_url: optional(d.url), reason: optional(d.reason), note: optional(d.note) };
}
