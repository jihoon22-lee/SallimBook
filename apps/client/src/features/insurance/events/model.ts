import type { ApiError } from "../../../platform/api";
import type { Schema } from "../model";
import { optional } from "../model";
import { parseKrw } from "../../assets/months/model";
import { isDateOnly, isUuid, todaySeoul } from "../../finance/dates";
export const claimStates = {
  draft: "청구 초안",
  submitted: "접수",
  documents_required: "추가 서류 필요",
  reviewing: "심사 중",
  decided: "결과 확인",
  closed: "청구 종료",
  withdrawn: "청구 철회",
};
export type ActualDraft = {
  amount: string;
  date: string;
  method: "none" | "account" | "card";
  methodId: string;
  note: string;
};
export function actualDraft(cash?: Schema["CashResponse"]): ActualDraft {
  return {
    amount: cash?.amount_krw ?? "",
    date: cash?.occurred_on ?? todaySeoul(),
    method: cash?.card_id ? "card" : cash?.account_id ? "account" : "none",
    methodId: cash?.card_id || cash?.account_id || "",
    note: cash?.note ?? "",
  };
}
export function actualInput(draft: ActualDraft) {
  const amount = parseKrw(draft.amount);
  if (
    amount === null ||
    amount === "0" ||
    !isDateOnly(draft.date) ||
    draft.date > todaySeoul() ||
    (draft.method !== "none" && !isUuid(draft.methodId)) ||
    draft.note.length > 2000
  )
    return null;
  return {
    amount_krw: amount,
    occurred_on: draft.date,
    account_id: draft.method === "account" ? draft.methodId : null,
    card_id: draft.method === "card" ? draft.methodId : null,
    note: optional(draft.note),
  };
}
export function exactSum(amounts: string[]): string | null {
  const values = amounts.map(parseKrw);
  return values.some((value) => value === null)
    ? null
    : values.reduce((sum, value) => sum + BigInt(value!), 0n).toString();
}
export type EventKind = "expense" | "refund" | "payout" | "return";
export type EventRow =
  | Schema["ExpenseResponse"]
  | Schema["RefundResponse"]
  | Schema["PayoutResponse"]
  | Schema["ReturnResponse"];
export const eventPaths = {
  expense: "expenses",
  refund: "refunds",
  payout: "payouts",
  return: "returns",
};
export const eventNames = {
  expense: "의료비",
  refund: "의료비 환불",
  payout: "보험금 수령",
  return: "보험금 반환",
};
/**
 * Only a stale version or an already-void original warrants comparing with the current
 * record. Rule conflicts (expense in a claim, refunds or returns present, amounts over the
 * original) explain themselves; the failed request kept no idempotency reservation, so the
 * same save can be retried after fixing the cause.
 */
export function needsCompare(error: ApiError | null): boolean {
  return (
    error?.status === 409 &&
    (error.code === "VERSION_CONFLICT" || error.code === "EVENT_ALREADY_VOID")
  );
}
