import { expect, test } from "@playwright/test";
import { canGoBackWithinApp } from "../src/platform/navigation";
import { isValidMonth, seoulMonth } from "../src/shared/MonthContext";

test("fresh or foreign browser history cannot enable an in-app history back", () => {
  for (const state of [null, undefined, {}, { idx: 0 }, { idx: -1 }, { idx: "1" }, { idx: 1.5 }]) {
    expect(canGoBackWithinApp(state)).toBe(false);
  }
  expect(canGoBackWithinApp({ idx: 1 })).toBe(true);
});

test("month boundaries use Seoul time and reject impossible route months", () => {
  expect(seoulMonth(new Date("2026-09-30T15:00:00Z"))).toBe("2026-10");
  expect(seoulMonth(new Date("2026-09-30T14:59:59Z"))).toBe("2026-09");
  expect(isValidMonth("2026-01")).toBe(true);
  for (const value of ["0000-01", "2026-00", "2026-13", "2026-1", "2026-01-01", ""]) {
    expect(isValidMonth(value)).toBe(false);
  }
});
