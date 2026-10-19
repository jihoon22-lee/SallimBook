import { expect, test } from "@playwright/test";
import fixtures from "../../../packages/test-fixtures/catalog.json" with { type: "json" };
import {
  incomeDraft,
  incomeInput,
  incomePatch,
  preserveIncomeChanges,
  conversionTotal,
} from "../src/features/income/model";
import { cardDraft, cardInput } from "../src/features/cards/model";
import { generationValid, paymentSplit, ruleDraft, ruleInput } from "../src/features/fixed/model";
import { uid } from "./support/finance";
test("cash form normalization preserves exact money, month precision and changed-only corrections", () => {
  const draft = {
    ...incomeDraft("2025-02"),
    member: uid(2),
    amount: "9007199254740993",
    date: "2025-02-20",
  };
  expect(incomeInput(draft)).toMatchObject({
    amount_krw: "9007199254740993",
    occurred_on: null,
    date_precision: "month",
  });
  for (const amount of ["", "0", "-1", "1.2", "1e3", "1,000"])
    expect(incomeInput({ ...draft, amount })).toBeNull();
  expect(incomePatch(draft, { ...draft, amount: "9007199254740994" }, "합성 정정", false)).toEqual({
    amount_krw: "9007199254740994",
    reason: "합성 정정",
    duplicate_acknowledged: false,
  });
  expect(
    preserveIncomeChanges(
      draft,
      { ...draft, amount: "10" },
      { ...draft, note: "배우자가 남긴 합성 메모" },
    ),
  ).toMatchObject({ amount: "10", note: "배우자가 남긴 합성 메모" });
  expect(conversionTotal([{ amount_krw: "9007199254740993" }, { amount_krw: "7" }])).toBe(
    "9007199254741000",
  );
});
test("card metadata accepts four digits only and never creates secret fields", () => {
  const draft = {
    ...cardDraft(),
    owner: uid(2),
    issuer: "합성 카드사",
    product: "합성 카드",
    lastFour: "1234",
    settlementDay: "31",
  };
  const input = cardInput(draft)!;
  expect(input).toMatchObject({ last_four: "1234", settlement_day: 31 });
  for (const key of ["card_number", "pan", "expiry", "cvc", "cvv", "ciphertext"])
    expect(Object.hasOwn(input, key)).toBe(false);
  expect(cardInput({ ...draft, lastFour: "12345" })).toBeNull();
  expect(cardInput({ ...draft, settlementDay: "32" })).toBeNull();
  expect(cardInput({ ...draft, started: "2025-02-01", ended: "2025-01-31" })).toBeNull();
});
test("fixed inputs keep unknown separate from zero and reject malformed currency pairs and ranges", () => {
  const draft = {
    ...ruleDraft(),
    title: "합성 구독",
    from: "2025-01-01",
    anchor: "2025-01-31",
    amountMode: "variable" as const,
  };
  expect(ruleInput(draft)?.expected_amount_krw).toBeNull();
  expect(ruleInput({ ...draft, amount: "0" })?.expected_amount_krw).toBe("0");
  expect(ruleInput({ ...draft, amountMode: "fixed" })).toBeNull();
  expect(ruleInput({ ...draft, currency: "USD" })).toBeNull();
  expect(ruleInput({ ...draft, currency: "USD", foreignAmount: "20.12345678" })).toMatchObject({
    currency_reference: "USD",
    foreign_amount_reference: "20.12345678",
    expected_amount_krw: null,
  });
  expect(generationValid("2024-01-01", "2024-12-31")).toBe(true);
  expect(generationValid("2024-01-01", "2025-01-01")).toBe(false);
  expect(generationValid("2025-02-30", "2025-03-01")).toBe(false);
});
test("T-09 payment split conserves the fixture amount and keeps asset transfers separate", () => {
  const vector = fixtures.vectors.find((item) => item.id === "T-09")!;
  const input = vector.inputs as {
    payment_krw: string;
    principal_krw: string;
    interest_krw: string;
  };
  const expected = vector.expected as { consumption_krw: string };
  expect(paymentSplit(input.payment_krw, input.principal_krw, input.interest_krw, "loan")).toEqual({
    principal: input.principal_krw,
    interest: expected.consumption_krw,
  });
  expect(paymentSplit("1000000", "700000", "299999", "loan")).toBeNull();
  expect(paymentSplit("0", "0", "0", "loan")).toBeNull();
  expect(paymentSplit("9007199254740993", "", "", "asset_transfer")).toEqual({
    principal: "0",
    interest: null,
  });
});
