import { expect, test } from "@playwright/test";
import {
  addDays,
  applianceDraft,
  attentionRank,
  compareAttention,
  compareWarranty,
  dueSoon,
  matchesTodayFilter,
  applianceInput,
  consumableDraft,
  consumableInput,
  linkDraft,
  linkInput,
  movementInput,
  quantity,
  purchaseUrl,
} from "../src/features/homecare/model";
import type { Schema } from "../src/features/homecare/model";
import { applianceRow, linkRow } from "./support/homecare";
import { uid } from "./support/finance";

test("appliance purchase money preserves missing and explicit zero without financial fields", () => {
  const draft = { ...applianceDraft(), name: "합성 공기청정기" };
  expect(applianceInput(draft)?.purchase_price_krw).toBeNull();
  expect(applianceInput({ ...draft, price: "0" })?.purchase_price_krw).toBe("0");
  expect(applianceInput({ ...draft, price: "9007199254740993" })?.purchase_price_krw).toBe(
    "9007199254740993",
  );
  expect(applianceInput({ ...draft, purchased: "2025-03-01", ended: "2025-02-28" })).toBeNull();
  expect(applianceInput({ ...draft, purchased: "2099-01-01" })).toBeNull();
  expect(applianceInput({ ...draft, warranty: "2099-01-01" })).not.toBeNull();
});
test("shared SKU inputs are bounded exact integers and have no initial stock mutation", () => {
  const draft = { ...consumableDraft(), name: "합성 필터", unit: "개" };
  expect(consumableInput(draft)).toMatchObject({ low_stock_threshold: 0 });
  expect(Object.hasOwn(consumableInput(draft)!, "stock_quantity")).toBe(false);
  for (const value of ["-1", "1.2", "1e2", "1000001", "", "01"]) expect(quantity(value)).toBeNull();
  expect(quantity("1000000")).toBe(1000000);
  expect(quantity("0")).toBe(0);
});
test("device cycles distinguish manual, bounded month/day intervals and explicit override clear", () => {
  const draft = linkDraft();
  expect(linkInput(draft)).toMatchObject({
    interval_unit: "manual",
    interval_count: null,
    next_check_override: null,
  });
  expect(linkInput({ ...draft, interval: "months", count: "120" })).not.toBeNull();
  expect(linkInput({ ...draft, interval: "months", count: "121" })).toBeNull();
  expect(linkInput({ ...draft, interval: "days", count: "3650" })).not.toBeNull();
  expect(linkInput({ ...draft, interval: "days", count: "3651" })).toBeNull();
  expect(linkInput({ ...draft, quantity: "0" })).toBeNull();
  expect(linkInput({ ...draft, override: "2025-02-30" })).toBeNull();
});
test("stock deltas require direction, bounded counts, actual dates and adjustment reasons", () => {
  const draft = {
    kind: "receipt" as const,
    quantity: "3",
    date: "2025-02-10",
    price: "",
    url: "",
    reason: "",
    note: "",
  };
  expect(movementInput(draft)).toMatchObject({ quantity_delta: 3, unit_cost_krw: null });
  expect(movementInput({ ...draft, kind: "return_out" })).toMatchObject({ quantity_delta: -3 });
  expect(movementInput({ ...draft, kind: "adjustment", quantity: "-1" })).toBeNull();
  expect(
    movementInput({ ...draft, kind: "adjustment", quantity: "-1", reason: "합성 실물 확인" })
      ?.quantity_delta,
  ).toBe(-1);
  expect(movementInput({ ...draft, quantity: "0" })).toBeNull();
  expect(movementInput({ ...draft, date: "2099-01-01" })).toBeNull();
  for (const value of [
    "javascript:alert(1)",
    "http://example.test",
    "https://user@example.test",
    "https://example.test/a b",
  ])
    expect(purchaseUrl(value)).toBe(false);
  expect(purchaseUrl("https://example.test/item?id=1")).toBe(true);
});

const status = (
  id: number,
  patch: Partial<Schema["HomecareStatusItem"]> = {},
): Schema["HomecareStatusItem"] => ({
  ...linkRow(id),
  appliance_name: "합성 거실 청정기",
  appliance_location: null,
  consumable_name: "합성 공용 필터",
  sku_or_model: null,
  unit: "개",
  low_stock_threshold: 1,
  as_of: "2026-10-17",
  replacement_due: false,
  next_check_on: "2026-12-01",
  purchase_needed: false,
  low_stock: false,
  ...patch,
});

test("due soon covers the next seven days from server as_of and excludes due or unknown dates", () => {
  expect(addDays("2026-10-28", 7)).toBe("2026-11-04");
  expect(addDays("2026-12-28", 7)).toBe("2027-01-04");
  expect(addDays("2028-02-25", 7)).toBe("2028-03-03");
  const at = (next: string | null, due: boolean | null, as_of = "2026-10-17") =>
    dueSoon({ as_of, next_check_on: next, replacement_due: due });
  expect(at("2026-10-18", false)).toBe(true);
  expect(at("2026-10-24", false)).toBe(true);
  expect(at("2026-10-25", false)).toBe(false);
  expect(at("2026-10-17", true)).toBe(false);
  expect(at(null, null)).toBe(false);
  expect(at("2026-11-04", false, "2026-10-28")).toBe(true);
  expect(at("2026-11-05", false, "2026-10-28")).toBe(false);
  expect(at("2027-01-04", false, "2026-12-28")).toBe(true);
});

test("attention ranks due, purchase, soon, low stock and unknown before ready links and orders names in Korean", () => {
  const rows = [
    status(311, { appliance_name: "합성 가습기" }),
    status(315, { appliance_name: "합성 냉장고", replacement_due: null, next_check_on: null }),
    status(313, {
      appliance_name: "합성 공기청정기",
      consumable_name: "합성 예비 필터",
      low_stock: true,
    }),
    status(312, { appliance_name: "합성 세탁기", next_check_on: "2026-10-24" }),
    status(314, { appliance_name: "합성 정수기", purchase_needed: true }),
    status(310, {
      appliance_name: "합성 제습기",
      replacement_due: true,
      next_check_on: "2026-10-17",
    }),
    status(316, {
      appliance_name: "합성 공기청정기",
      replacement_due: true,
      next_check_on: "2026-10-01",
      purchase_needed: true,
    }),
  ];
  expect(rows.map(attentionRank)).toEqual([5, 4, 3, 2, 1, 0, 0]);
  expect([...rows].sort(compareAttention).map((r) => r.id)).toEqual([
    uid(316),
    uid(310),
    uid(314),
    uid(312),
    uid(313),
    uid(315),
    uid(311),
  ]);
  expect(rows.filter((r) => matchesTodayFilter(r, "attention"))).toHaveLength(6);
  expect(rows.filter((r) => matchesTodayFilter(r, "soon")).map((r) => r.id)).toEqual([uid(312)]);
  expect(rows.filter((r) => matchesTodayFilter(r, "due")).map((r) => r.id)).toEqual([
    uid(310),
    uid(316),
  ]);
  expect(rows.filter((r) => matchesTodayFilter(r, "all"))).toHaveLength(7);
});
test("warranty order puts the soonest active expiry first then the most recent expiry then unknown", () => {
  const rows = [
    applianceRow(120, {
      name: "합성 김치냉장고",
      warranty_until: "2025-12-31",
      warranty_status: "expired",
    }),
    applianceRow(121, {
      name: "합성 건조기",
      warranty_until: "2026-10-16",
      warranty_status: "expired",
    }),
    applianceRow(122, {
      name: "합성 식기세척기",
      warranty_until: "2027-03-01",
      warranty_status: "active",
    }),
    applianceRow(123, {
      name: "합성 로봇청소기",
      warranty_until: "2026-11-01",
      warranty_status: "active",
    }),
    applianceRow(124, { name: "합성 안마의자", warranty_until: null, warranty_status: "unknown" }),
    applianceRow(125, {
      name: "합성 가스레인지",
      warranty_until: "2026-11-01",
      warranty_status: "active",
    }),
  ];
  expect([...rows].sort(compareWarranty).map((r) => r.name)).toEqual([
    "합성 가스레인지",
    "합성 로봇청소기",
    "합성 식기세척기",
    "합성 건조기",
    "합성 김치냉장고",
    "합성 안마의자",
  ]);
});
