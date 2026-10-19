import { expect, test } from "@playwright/test";
import {
  applianceDraft,
  applianceInput,
  consumableDraft,
  consumableInput,
  linkDraft,
  linkInput,
  movementInput,
  quantity,
  purchaseUrl,
} from "../src/features/homecare/model";

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
