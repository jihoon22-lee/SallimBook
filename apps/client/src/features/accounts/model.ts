import type { components, operations } from "@sallimbook/api-client";
import { isDateOnly } from "../finance/dates";
export type Account = components["schemas"]["AccountResponse"];
export type AccountQuery = NonNullable<operations["listAccounts"]["parameters"]["query"]>;
export type AccountInput = Omit<components["schemas"]["AccountCreate"], "account_number">;
export type AccountPatch = Omit<components["schemas"]["AccountPatch"], "account_number">;
export const accountTypes: Record<Account["account_type"], string> = { checking: "입출금", savings: "적금", term_deposit: "정기예금", brokerage: "증권", pension_savings: "연금저축", irp: "IRP", dc_pension: "DC 퇴직연금", isa: "ISA", cma: "CMA", other: "기타" };
export type AccountDraft = { institution_name: string; account_type: Account["account_type"] | ""; purpose: string; opened_on: string };
export const accountLabels: Record<keyof AccountDraft, string> = { institution_name: "금융기관", account_type: "계좌 유형", purpose: "용도", opened_on: "개설일" };
export function accountDraft(account?: Account): AccountDraft { return { institution_name: account?.institution_name ?? "", account_type: account?.account_type ?? "", purpose: account?.purpose ?? "", opened_on: account?.opened_on ?? "" }; }
export function accountInput(draft: AccountDraft) {
  if (!draft.institution_name.trim() || !draft.account_type || (draft.opened_on && !isDateOnly(draft.opened_on))) return null;
  return { institution_name: draft.institution_name.trim(), account_type: draft.account_type, purpose: draft.purpose.trim() || null, opened_on: draft.opened_on || null };
}
