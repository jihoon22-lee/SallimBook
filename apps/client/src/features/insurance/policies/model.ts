import type { Policy, PolicyInput } from "../model";
import { optional, validPeriod } from "../model";
import { isDateOnly, isUuid } from "../../finance/dates";
import { parseKrwInput } from "../../../shared/krw";
export type PolicyDraft = {
  insurer: string;
  product: string;
  holder: string;
  insured: string;
  beneficiary: string;
  contractStart: string;
  contractEnd: string;
  coverageStart: string;
  coverageEnd: string;
  paymentStart: string;
  paymentEnd: string;
  /** Premiums already paid up to a date, for the time before plans were registered. */
  paidBefore: string;
  paidThrough: string;
  status: Policy["status"];
  asset: string;
  note: string;
};
export function policyDraft(row?: Policy): PolicyDraft {
  return {
    insurer: row?.insurer ?? "",
    product: row?.product_name ?? "",
    holder: row?.policyholder_member_id ?? "",
    insured: row?.insured_member_id ?? "",
    beneficiary: row?.beneficiary_note ?? "",
    contractStart: row?.contract_start ?? "",
    contractEnd: row?.contract_end ?? "",
    coverageStart: row?.coverage_start ?? "",
    coverageEnd: row?.coverage_end ?? "",
    paymentStart: row?.payment_start ?? "",
    paymentEnd: row?.payment_end ?? "",
    paidBefore: row?.premium_paid_before_krw ?? "",
    paidThrough: row?.premium_paid_through ?? "",
    status: row?.status ?? "active",
    asset: row?.valuation_asset_id ?? "",
    note: row?.note ?? "",
  };
}
export function policyInput(d: PolicyDraft): PolicyInput | null {
  if (
    !d.insurer.trim() ||
    !d.product.trim() ||
    d.insurer.trim().length > 120 ||
    d.product.trim().length > 120 ||
    d.beneficiary.length > 1000 ||
    d.note.length > 2000 ||
    ![d.holder, d.insured, d.asset].every((id) => !id || isUuid(id)) ||
    !validPeriod(d.contractStart, d.contractEnd) ||
    !validPeriod(d.coverageStart, d.coverageEnd, true) ||
    !validPeriod(d.paymentStart, d.paymentEnd)
  )
    return null;
  // The amount and its date belong together: both or neither.
  const paid = d.paidBefore.trim() ? parseKrwInput(d.paidBefore) : null;
  if (
    (paid && !paid.ok) ||
    Boolean(paid) !== Boolean(d.paidThrough) ||
    (paid && !isDateOnly(d.paidThrough))
  )
    return null;
  return {
    insurer: d.insurer.trim(),
    product_name: d.product.trim(),
    policyholder_member_id: optional(d.holder),
    insured_member_id: optional(d.insured),
    beneficiary_note: optional(d.beneficiary),
    contract_start: optional(d.contractStart),
    contract_end: optional(d.contractEnd),
    coverage_start: d.coverageStart,
    coverage_end: optional(d.coverageEnd),
    payment_start: optional(d.paymentStart),
    payment_end: optional(d.paymentEnd),
    premium_paid_before_krw: paid?.ok ? paid.krw : null,
    premium_paid_through: paid ? d.paidThrough : null,
    status: d.status,
    valuation_asset_id: optional(d.asset),
    note: optional(d.note),
  };
}
