import { expect, test } from "@playwright/test";
import { krwFieldError, krwMessages, parseKrwInput } from "../src/shared/krw";
import { parseKrw } from "../src/features/assets/months/model";

test("parseKrwInput accepts grouped won amounts and rejects ambiguous input", () => {
  const accepted = [
    ["3,500,000", "3500000"],
    ["3500000", "3500000"],
    ["３，５００，０００", "3500000"],
    ["3 500 000", "3500000"],
    ["3 500 000", "3500000"],
    ["3,500,000원", "3500000"],
    [" 3,500,000 원 ", "3500000"],
    ["0", "0"],
    ["007", "7"],
    ["12345678901234567890", "12345678901234567890"],
  ] as const;
  for (const [input, krw] of accepted)
    expect(parseKrwInput(input), input).toEqual({ ok: true, krw });
  const rejected = [
    ["", "empty"],
    ["   ", "empty"],
    ["원", "format"],
    ["1.5", "format"],
    ["1,5", "format"],
    ["35,00,000", "format"],
    ["3,500 000", "format"],
    ["0,500", "format"],
    ["-1000", "format"],
    ["+1000", "format"],
    ["1e3", "format"],
    ["123456789012345678901", "too_long"],
    ["123,456,789,012,345,678,901", "too_long"],
  ] as const;
  for (const [input, reason] of rejected)
    expect(parseKrwInput(input), input).toEqual({ ok: false, reason });
  expect(parseKrw("3,500,000")).toBe("3500000");
  expect(parseKrw("1.5")).toBeNull();
  expect(parseKrw("")).toBeNull();
});

test("krwFieldError separates empty, malformed, oversized and zero amounts", () => {
  expect(krwFieldError("", { required: true, positive: true })).toBe(krwMessages.empty);
  expect(krwFieldError("", { required: false, positive: false })).toBeNull();
  expect(krwFieldError("1.5", { required: false, positive: false })).toBe(krwMessages.format);
  expect(krwFieldError("123456789012345678901", { required: true, positive: false })).toBe(
    krwMessages.too_long,
  );
  expect(krwFieldError("0", { required: true, positive: true })).toBe(krwMessages.zero);
  expect(krwFieldError("0", { required: true, positive: false })).toBeNull();
  expect(krwFieldError("3,500,000원", { required: true, positive: true })).toBeNull();
});
