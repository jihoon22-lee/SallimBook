import type { components } from "@sallimbook/api-client";
import { isValidMonth } from "../../../shared/MonthContext";
import { isDateOnly, todaySeoul } from "../../finance/dates";
export type MonthRecord = components["schemas"]["MonthResponse"];
export type MonthValue = components["schemas"]["MonthValueResponse"];
export type MonthTotals = components["schemas"]["MonthTotals"];
export type MonthReference = components["schemas"]["MonthReference"];
export type MonthValueInput = components["schemas"]["MonthValueUpdate"];
export const monthStates = { draft: "작성 중", reopened: "정정 중", confirmed: "확정" } as const;
export const verificationStates = {
  missing: "미입력",
  carried_unconfirmed: "불러온 값 · 미확인",
  verified: "확인 완료",
} as const;
export function parseKrw(value: string): string | null {
  const trimmed = value.trim();
  if (!/^[0-9]{1,20}$/.test(trimmed)) return null;
  return BigInt(trimmed).toString();
}
export function formatKrw(value: string | null): string {
  if (value === null) return "미입력";
  if (!/^(0|-?[1-9][0-9]{0,19})$/.test(value)) return "금액 확인 필요";
  return `${BigInt(value).toLocaleString("ko-KR")}원`;
}
/** Display-only preview; the API's Decimal/int result remains authoritative. */
export function ownedPreview(
  amount: string,
  share: string,
  basis: MonthValue["amount_basis"],
): string | null {
  const value = parseKrw(amount);
  if (value === null || !/^(0(?:\.[0-9]{1,18})?|1(?:\.0{1,18})?)$/.test(share)) return null;
  if (basis === "owned") return value;
  if (basis !== "whole") return null;
  const [whole = "0", fraction = ""] = share.split(".");
  const divisor = 10n ** BigInt(fraction.length);
  const scaled = BigInt(whole + fraction);
  return ((BigInt(value) * scaled * 2n + divisor) / (divisor * 2n)).toString();
}
export function monthEnd(month: string): string {
  if (!isValidMonth(month)) return "";
  const year = Number(month.slice(0, 4));
  const number = Number(month.slice(5));
  const days =
    number === 2
      ? year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
        ? 29
        : 28
      : [4, 6, 9, 11].includes(number)
        ? 30
        : 31;
  return `${month}-${days}`;
}
export function previousMonth(month: string): string | null {
  if (!isValidMonth(month) || month === "0001-01") return null;
  const year = Number(month.slice(0, 4));
  const number = Number(month.slice(5));
  return number === 1
    ? `${String(year - 1).padStart(4, "0")}-12`
    : `${month.slice(0, 4)}-${String(number - 1).padStart(2, "0")}`;
}
export function maxAsOfDate(month: string): string {
  return monthEnd(month) < todaySeoul() ? monthEnd(month) : todaySeoul();
}
export type ValueDraft = {
  mode: "amount" | "unchanged" | "missing";
  amount: string;
  asOf: string;
  reason: string;
};
export function valueDraft(row: MonthValue): ValueDraft {
  return {
    mode: "amount",
    amount: row.input_amount_krw ?? "",
    asOf: row.as_of_date ?? "",
    reason: row.change_reason ?? "",
  };
}
export function valueInput(
  revisionId: string,
  row: MonthValue,
  draft: ValueDraft,
  month: string,
): MonthValueInput | null {
  if (
    draft.mode !== "missing" &&
    (!isDateOnly(draft.asOf) || draft.asOf.slice(0, 7) !== month || draft.asOf > todaySeoul())
  )
    return null;
  const common = {
    revision_id: revisionId,
    value_id: row.id,
    change_reason: draft.reason.trim() || null,
  };
  if (draft.mode === "missing")
    return { ...common, unchanged: false, input_amount_krw: null, as_of_date: null };
  if (draft.mode === "unchanged")
    return row.verification_state === "carried_unconfirmed" && row.input_amount_krw !== null
      ? { ...common, unchanged: true, as_of_date: draft.asOf }
      : null;
  const amount = parseKrw(draft.amount);
  return amount === null
    ? null
    : { ...common, unchanged: false, input_amount_krw: amount, as_of_date: draft.asOf };
}
export function scopeDifferences(previous: MonthRecord | null, current: MonthRecord) {
  const prior = new Map(
    (previous?.values ?? [])
      .filter((row) => row.inclusion_status === "included")
      .map((row) => [row.asset_id, row]),
  );
  const next = new Map(
    current.values
      .filter((row) => row.inclusion_status === "included")
      .map((row) => [row.asset_id, row]),
  );
  const canonical = (value: string) =>
    value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
  return {
    added: [...next.values()].filter((row) => !prior.has(row.asset_id)),
    removed: [...prior.values()].filter((row) => !next.has(row.asset_id)),
    changedShare: [...next.values()].filter(
      (row) =>
        prior.has(row.asset_id) &&
        canonical(prior.get(row.asset_id)!.household_share) !== canonical(row.household_share),
    ),
    hasPrevious: previous !== null,
  };
}
export function scopeIdentity(row: MonthValue): string {
  return JSON.stringify([
    row.asset_id,
    row.name,
    row.kind,
    row.category,
    row.ownership_kind,
    row.owner_member_id,
    row.household_share.includes(".")
      ? row.household_share.replace(/0+$/, "").replace(/\.$/, "")
      : row.household_share,
    row.amount_basis,
    row.inclusion_status,
    row.started_on,
    row.ended_on,
  ]);
}

/** A carried note only while a carried amount remains; cleared rows say nothing. */
export function carriedNote(row: MonthValue): string | null {
  if (row.verification_state === "carried_unconfirmed")
    return row.origin === "carried"
      ? "이전 기록에서 불러온 금액이에요. 이번 달 실제 값과 기준일을 확인해 주세요."
      : "자산 범위를 반영해 다시 확인할 금액이에요. 이번 달 실제 값과 기준일을 확인해 주세요.";
  if (row.verification_state === "verified" && row.origin === "carried")
    return "이전 기록에서 불러온 금액이에요. 직접 확인을 마쳤어요.";
  return null;
}
