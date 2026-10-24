import type { components } from "@sallimbook/api-client";
import type { ApiErrorCode } from "../../platform/api";
import { isDateOnly, isUuid, todaySeoul } from "../finance/dates";
import { parseKrw } from "../assets/months/model";
export type Rule = components["schemas"]["RuleResponse"];
export type RuleTerms = components["schemas"]["RuleVersionResponse"];
export type Obligation = components["schemas"]["ObligationResponse"];
export type Settlement = components["schemas"]["SettlementResponse"];
export type ObligationHistoryItem = components["schemas"]["ObligationHistoryItem"];
const historyLabels: Record<ObligationHistoryItem["action"], string> = {
  create: "회차 생성",
  regenerate: "규칙 변경 반영",
  reschedule: "예정일 변경",
  skip: "건너뛰기",
  unskip: "건너뛰기 복원",
  complete: "수동 완료",
  reopen: "수동 완료 재개",
  settle: "실제 납부",
  void_settlement: "납부 무효",
};
export function historyLabel(row: ObligationHistoryItem): string {
  if (row.action === "regenerate" && row.schedule_state === "superseded") return "규칙 종료로 대체";
  // An older cached response may still carry an action this build does not know.
  return historyLabels[row.action] ?? "회차 상태 변경";
}
export const economicTypes = {
  expense: "소비성 비용",
  loan: "대출 원리금",
  asset_transfer: "연금 납입 등 자산 이동",
};
export const frequencies = { monthly: "월 주기", annual: "연 주기", days: "일수 주기" };
export const obligationStates = {
  unpaid: "납부 확인 전",
  partial: "일부 납부",
  paid: "납부 확인",
  skipped: "건너뜀",
  superseded: "다른 규칙으로 대체",
};
/** A missing record is not proof of a delinquent payment. */
export function obligationStatusLabel(row: Obligation, asOf = todaySeoul()): string {
  if (row.status === "unpaid")
    return row.scheduled_date > asOf
      ? "납부 예정"
      : row.scheduled_date === asOf
        ? "오늘 예정 · 납부 확인 전"
        : "예정일 지남 · 확인 필요";
  if (row.status === "paid" && row.expected_amount_krw === null) return "납부 확인 · 예정액 미정";
  return obligationStates[row.status];
}
export type RuleDraft = {
  title: string;
  category: string;
  amountMode: "fixed" | "variable";
  amount: string;
  economic: "expense" | "loan" | "asset_transfer";
  loan: string;
  method: "none" | "account" | "card";
  methodId: string;
  currency: string;
  foreignAmount: string;
  note: string;
  anchor: string;
  frequency: "monthly" | "annual" | "days";
  interval: string;
  from: string;
  until: string;
  endReason: string;
};
export function displayedTerms(rule: Rule, date = todaySeoul()): RuleTerms {
  const sorted = [...rule.versions].sort((a, b) =>
    a.effective_from.localeCompare(b.effective_from),
  );
  return (
    sorted.find(
      (row) => row.effective_from <= date && (!row.effective_until || date < row.effective_until),
    ) ??
    sorted.filter((row) => row.effective_from > date)[0] ??
    sorted.at(-1)!
  );
}
/**
 * The version a change from `date` follows, as the server's _split_at picks it: the last one
 * starting before the date. Until a date is chosen, the terms in effect today.
 */
export function changeBase(rule: Rule, date: string): RuleTerms {
  if (!isDateOnly(date)) return displayedTerms(rule);
  return (
    [...rule.versions]
      .sort((a, b) => a.effective_from.localeCompare(b.effective_from))
      .filter((row) => row.effective_from < date)
      .at(-1) ?? displayedTerms(rule)
  );
}
export function changeDraft(rule: Rule, date: string): RuleDraft {
  return { ...ruleDraft(changeBase(rule, date)), from: date };
}
export function pendingVersions(rule: Rule, today = todaySeoul()): RuleTerms[] {
  return rule.versions
    .filter((row) => row.effective_from > today)
    .sort((a, b) => a.effective_from.localeCompare(b.effective_from));
}
/**
 * Same split as the server's _split_at: a cutoff must follow the version already running
 * today (or the first version), and not-yet-started versions from the cutoff on are revoked.
 */
export function withdrawalPlan(
  rule: Rule,
  date: string,
  today = todaySeoul(),
): { floor: string; withdrawn: RuleTerms[] } {
  const sorted = [...rule.versions].sort((a, b) =>
    a.effective_from.localeCompare(b.effective_from),
  );
  const floor = (sorted.filter((row) => row.effective_from <= today).at(-1) ?? sorted[0]!)
    .effective_from;
  const withdrawn = isDateOnly(date)
    ? sorted.filter(
        (row) =>
          row.effective_from > floor && row.effective_from > today && row.effective_from >= date,
      )
    : [];
  return { floor, withdrawn };
}
// The shared CashflowError wording is about occurrences and the last start date; rule
// changes and ends need the revocation meaning instead.
export const ruleCommandMessages: Partial<Record<ApiErrorCode, string>> = {
  OBLIGATION_HAS_PAYMENT:
    "철회할 예정 변경에 실제 납부나 수동 변경한 회차가 있어요. 그 회차를 먼저 정리하거나 예정 변경 이후 날짜를 선택해 주세요.",
  RULE_PERIOD_OVERLAP:
    "현재 적용 중인 시작일 뒤이면서 종료 적용일 전인 날짜를 선택해 주세요. 종료일을 연장하거나 지난 규칙을 덮어쓰지 않아요.",
};
/** How the detail page offers a payment: normally, only after a check when already paid, or not at all. */
export function settlementEntry(row: Obligation): "settle" | "additional" | null {
  if (row.schedule_state !== "active" || row.skipped || row.manually_completed) return null;
  return row.status === "paid" ? "additional" : "settle";
}
export function ruleDraft(row?: RuleTerms): RuleDraft {
  return row
    ? {
        title: row.title,
        category: row.category,
        amountMode: row.amount_mode,
        amount: row.expected_amount_krw ?? "",
        economic: row.economic_type,
        loan: row.loan_asset_id ?? "",
        method: row.card_id ? "card" : row.account_id ? "account" : "none",
        methodId: row.card_id ?? row.account_id ?? "",
        currency: row.currency_reference ?? "",
        foreignAmount: row.foreign_amount_reference ?? "",
        note: row.note ?? "",
        anchor: row.anchor_date,
        frequency: row.frequency,
        interval: String(row.interval_count),
        from: todaySeoul(),
        until: "",
        endReason: "",
      }
    : {
        title: "",
        category: "구독",
        amountMode: "fixed",
        amount: "",
        economic: "expense",
        loan: "",
        method: "none",
        methodId: "",
        currency: "",
        foreignAmount: "",
        note: "",
        anchor: "",
        frequency: "monthly",
        interval: "1",
        from: "",
        until: "",
        endReason: "",
      };
}
export function ruleInput(draft: RuleDraft): components["schemas"]["RuleCreate"] | null {
  const amount = draft.amount === "" ? null : parseKrw(draft.amount);
  const foreignPair =
    (!draft.currency && !draft.foreignAmount) ||
    (/^[A-Z]{3}$/.test(draft.currency) &&
      /^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$/.test(draft.foreignAmount) &&
      draft.foreignAmount.length <= 40);
  if (
    !draft.title.trim() ||
    draft.title.trim().length > 120 ||
    !draft.category.trim() ||
    draft.category.trim().length > 40 ||
    draft.note.length > 2000 ||
    (draft.amount !== "" && amount === null) ||
    (draft.amountMode === "fixed" && amount === null) ||
    (draft.method !== "none" && !isUuid(draft.methodId)) ||
    (draft.economic === "loan" && draft.loan && !isUuid(draft.loan)) ||
    !foreignPair ||
    !isDateOnly(draft.anchor) ||
    !isDateOnly(draft.from) ||
    !/^[1-9][0-9]{0,3}$/.test(draft.interval) ||
    Number(draft.interval) > 3650 ||
    !!draft.until !== !!draft.endReason.trim() ||
    (draft.until &&
      (!isDateOnly(draft.until) || draft.until <= draft.from || draft.endReason.length > 500))
  )
    return null;
  return {
    title: draft.title.trim(),
    category: draft.category.trim(),
    amount_mode: draft.amountMode,
    expected_amount_krw: amount,
    economic_type: draft.economic,
    loan_asset_id: draft.economic === "loan" ? draft.loan || null : null,
    account_id: draft.method === "account" ? draft.methodId : null,
    card_id: draft.method === "card" ? draft.methodId : null,
    currency_reference: draft.currency || null,
    foreign_amount_reference: draft.foreignAmount || null,
    note: draft.note.trim() || null,
    anchor_date: draft.anchor,
    frequency: draft.frequency,
    interval_count: Number(draft.interval),
    effective_from: draft.from,
    effective_until: draft.until || null,
    end_reason: draft.endReason.trim() || null,
  };
}
export function preserveRuleChanges(
  previous: RuleDraft,
  draft: RuleDraft,
  latest: RuleDraft,
): RuleDraft {
  return {
    ...latest,
    ...Object.fromEntries(
      Object.entries(draft).filter(([key, value]) => previous[key as keyof RuleDraft] !== value),
    ),
  };
}
export function generationValid(start: string, end: string): boolean {
  return (
    isDateOnly(start) &&
    isDateOnly(end) &&
    start <= end &&
    new Date(`${end}T00:00:00Z`).getTime() - new Date(`${start}T00:00:00Z`).getTime() <=
      365 * 86_400_000
  );
}
export function paymentSplit(
  amount: string,
  principal: string,
  interest: string,
  economic: Obligation["economic_type"],
): { principal: string; interest: string | null } | null {
  const money = parseKrw(amount);
  if (!money || money === "0") return null;
  if (economic !== "loan") return { principal: "0", interest: null };
  const p = parseKrw(principal);
  const i = parseKrw(interest);
  return p !== null && i !== null && BigInt(p) + BigInt(i) === BigInt(money)
    ? { principal: p, interest: i }
    : null;
}
