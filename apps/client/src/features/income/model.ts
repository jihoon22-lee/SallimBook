import type { components, operations } from "@sallimbook/api-client";
import { isValidMonth } from "../../shared/MonthContext";
import { isDateOnly, isUuid, todaySeoul } from "../finance/dates";
import { parseKrw } from "../assets/months/model";
export type Income = components["schemas"]["CashResponse"];
export type IncomeInput = Omit<components["schemas"]["IncomeCreate"], "card_id">;
export type IncomePatch = components["schemas"]["IncomePatch"];
export type IncomeReturn = Omit<components["schemas"]["IncomeReturn"], "card_id" | "member_id">;
export type IncomeConversion = Omit<components["schemas"]["IncomeConvert"], "replacements"> & { replacements: Omit<components["schemas"]["IncomeInput"], "card_id">[] };
export type IncomeQuery = operations["listIncome"]["parameters"]["query"];
export type IncomeDraft = { kind: IncomeInput["kind"]; member: string; month: string; precision: "day" | "month"; date: string; amount: string; account: string; note: string };
export const incomeKinds = { salary: "급여", bonus: "상여", other_income: "기타 수입", income_return: "수입 반환", insurance_receipt: "보험금 수령", insurance_return: "보험금 반환" } as const;
export const manualKinds = { salary: "급여", bonus: "상여", other_income: "기타 수입" } as const;
export const incomeActions = { create: "등록", correct: "정정", void: "무효", convert_source: "전환한 원본", convert_result: "전환 결과" };
export function manualIncome(row: Income): boolean { return Object.hasOwn(manualKinds, row.kind); }
export function incomeDraft(month: string, row?: Income): IncomeDraft {
  return row ? { kind: manualIncome(row) ? row.kind as IncomeInput["kind"] : "salary", member: row.member_id ?? "", month: row.period_month, precision: row.date_precision, date: row.occurred_on ?? "", amount: row.amount_krw, account: row.account_id ?? "", note: row.note ?? "" } : { kind: "salary", member: "", month, precision: "month", date: "", amount: "", account: "", note: "" };
}
export function incomeInput(draft: IncomeDraft): IncomeInput | null {
  const amount = parseKrw(draft.amount);
  if (!amount || amount === "0" || !isUuid(draft.member) || !isValidMonth(draft.month) || draft.account && !isUuid(draft.account) || draft.note.length > 2000 || draft.precision === "day" && (!isDateOnly(draft.date) || draft.date > todaySeoul())) return null;
  return { duplicate_acknowledged: false, kind: draft.kind, member_id: draft.member, period_month: draft.month, date_precision: draft.precision, occurred_on: draft.precision === "day" ? draft.date : null, amount_krw: amount, account_id: draft.account || null, note: draft.note.trim() || null };
}
export function incomePatch(base: IncomeDraft, draft: IncomeDraft, reason: string, duplicateAcknowledged: boolean): IncomePatch | null {
  const previous = incomeInput(base); const current = incomeInput(draft); if (!previous || !current || !reason.trim() || reason.trim().length > 500) return null;
  const changed = Object.fromEntries(Object.entries(current).filter(([key, value]) => previous[key as keyof IncomeInput] !== value));
  return Object.keys(changed).length ? { ...changed, reason: reason.trim(), duplicate_acknowledged: duplicateAcknowledged } : null;
}
export function preserveIncomeChanges(previous: IncomeDraft, draft: IncomeDraft, latest: IncomeDraft): IncomeDraft {
  return { ...latest, ...Object.fromEntries(Object.entries(draft).filter(([key, value]) => previous[key as keyof IncomeDraft] !== value)) };
}
export function conversionTotal(rows: { amount_krw: string }[]): string { return rows.reduce((sum, row) => sum + BigInt(row.amount_krw), 0n).toString(); }
