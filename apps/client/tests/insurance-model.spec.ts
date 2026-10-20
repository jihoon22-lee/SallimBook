import { expect, test } from "@playwright/test";
import { policyDraft, policyInput } from "../src/features/insurance/policies/model";
import { caseDraft, caseInput } from "../src/features/insurance/cases/CaseEditor";
import { medicalInput } from "../src/features/insurance/cases/MedicalTree";
import { expenseInput } from "../src/features/insurance/events/ExpenseEditor";
import { payoutInput } from "../src/features/insurance/events/PayoutEditor";
import { actualInput, exactSum } from "../src/features/insurance/events/model";
import { ancestors, descendants, preserveDraft } from "../src/features/insurance/model";
import { caseRow, nodeRow, policyRow } from "./support/insurance";
import { uid } from "./support/finance";
const actual = {
  amount: "860000",
  date: "2025-02-10",
  method: "none" as const,
  methodId: "",
  note: "",
};
test("policy metadata separates periods and rejects inverted dates without a number field", () => {
  const draft = policyDraft(policyRow());
  const input = policyInput(draft)!;
  expect(policyInput({ ...draft, note: "가".repeat(2000) })).not.toBeNull();
  expect(policyInput({ ...draft, note: "가".repeat(2001) })).toBeNull();
  expect(Object.hasOwn(input, "policy_number")).toBe(false);
  expect(input.contract_start).not.toBe(input.coverage_start);
  expect(policyInput({ ...draft, paymentEnd: "2023-01-01" })).toBeNull();
  expect(policyInput({ ...draft, coverageStart: "" })).toBeNull();
});
test("case states remain independent and only ended treatment requires an end date", () => {
  const draft = caseDraft(caseRow());
  expect(caseInput({ ...draft, diagnosis: "가".repeat(2000) })).not.toBeNull();
  expect(caseInput({ ...draft, diagnosis: "가".repeat(2001) })).toBeNull();
  expect(caseInput({ ...draft, financial: "settled" })).toMatchObject({
    treatment_state: "ongoing",
    financial_state: "settled",
    end_on: null,
  });
  expect(caseInput({ ...draft, treatment: "ended" })).toBeNull();
  expect(caseInput({ ...draft, treatment: "ended", end: "2025-02-20" })).toMatchObject({
    financial_state: "open",
    end_on: "2025-02-20",
  });
  expect(caseInput({ ...draft, end: "2025-02-20" })).toBeNull();
});
test("medical topology finds complete descendant exclusions and ancestry without following cycles forever", () => {
  const medical = {
    parent: "",
    kind: "outpatient" as const,
    label: "합성",
    provider: "",
    start: "2025-02-10",
    end: "",
    order: "0",
    note: "가".repeat(2000),
  };
  expect(medicalInput(medical)).not.toBeNull();
  expect(medicalInput({ ...medical, note: "가".repeat(2001) })).toBeNull();
  const nodes = [
    nodeRow(),
    nodeRow(92, { parent_id: uid(91) }),
    nodeRow(93, { parent_id: uid(92) }),
    nodeRow(94),
  ];
  expect([...descendants(nodes, uid(91))]).toEqual([uid(91), uid(92), uid(93)]);
  expect(ancestors(nodes, uid(93)).map((r) => r.id)).toEqual([uid(91), uid(92), uid(93)]);
  nodes[0]!.parent_id = uid(93);
  expect(ancestors(nodes, uid(93))).toHaveLength(3);
  expect(
    medicalInput({
      parent: "",
      kind: "outpatient",
      label: "합성",
      provider: "",
      start: "2025-02-10",
      end: "2025-02-09",
      order: "0",
      note: "",
    }),
  ).toBeNull();
});
test("receipt decomposition uses exact integers and keeps public coverage as nullable reference", () => {
  const d = {
    actual,
    caseId: uid(90),
    nodeId: uid(91),
    provider: "",
    receipt: "",
    gross: "",
    publicCoverage: "0",
    lines: [
      { label: "합성 분해1", amount: "600000", type: "other" },
      { label: "합성 분해2", amount: "260000", type: "other" },
    ],
  };
  expect(expenseInput(d)).toMatchObject({
    amount_krw: "860000",
    gross_medical_krw: null,
    public_coverage_krw: "0",
  });
  expect(expenseInput({ ...d, actual: { ...actual, amount: "859999" } })).toBeNull();
  expect(exactSum(["9007199254740992", "1"])).toBe("9007199254740993");
  expect(actualInput({ ...actual, amount: "0" })).toBeNull();
  expect(actualInput({ ...actual, amount: "1.2" })).toBeNull();
});
test("multi-case payout requires conserved positive allocations and a matching policy when claiming", () => {
  const d = {
    actual: { ...actual, amount: "500000" },
    insurer: "",
    allocations: [
      {
        caseId: uid(90),
        policyId: "",
        claimId: "",
        benefit: "reimbursement" as const,
        amount: "300000",
      },
      { caseId: uid(95), policyId: "", claimId: "", benefit: "fixed" as const, amount: "200000" },
    ],
  };
  expect(payoutInput(d)?.allocations).toHaveLength(2);
  expect(Object.hasOwn(payoutInput(d)!, "card_id")).toBe(false);
  expect(
    payoutInput({
      ...d,
      allocations: [d.allocations[0]!, { ...d.allocations[1]!, amount: "150000" }],
    }),
  ).toBeNull();
  expect(
    payoutInput({
      ...d,
      allocations: [{ ...d.allocations[0]!, claimId: uid(1200) }, d.allocations[1]!],
    }),
  ).toBeNull();
});
test("conflict merge preserves only fields changed by this editor", () => {
  expect(
    preserveDraft(
      { title: "old", note: "old", amount: "1" },
      { title: "mine", note: "old", amount: "2" },
      { title: "theirs", note: "new", amount: "3" },
    ),
  ).toEqual({ title: "mine", note: "new", amount: "2" });
});
