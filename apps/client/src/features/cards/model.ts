import type { components, operations } from "@sallimbook/api-client";
import { isDateOnly, isUuid, todaySeoul } from "../finance/dates";
export type Card = components["schemas"]["CardResponse"];
export type CardInput = components["schemas"]["CardCreate"];
export type CardPatch = components["schemas"]["CardPatch"];
export type CardQuery = NonNullable<operations["listCards"]["parameters"]["query"]>;
export type CardDraft = { owner: string; issuer: string; product: string; alias: string; type: "credit" | "debit"; lastFour: string; settlementDay: string; account: string; started: string; ended: string; note: string };
export const cardTypes = { credit: "신용카드", debit: "체크카드" };
export function cardDraft(row?: Card): CardDraft { return row ? { owner: row.owner_member_id, issuer: row.issuer_name, product: row.product_name, alias: row.alias ?? "", type: row.card_type, lastFour: row.last_four ?? "", settlementDay: row.settlement_day === null ? "" : String(row.settlement_day), account: row.settlement_account_id ?? "", started: row.started_on ?? "", ended: row.ended_on ?? "", note: row.note ?? "" } : { owner: "", issuer: "", product: "", alias: "", type: "credit", lastFour: "", settlementDay: "", account: "", started: "", ended: "", note: "" }; }
export function cardEndDateError(ended: string, started: string | null = null): string {
  if (!ended) return "";
  if (!isDateOnly(ended)) return "카드 사용 종료일을 올바른 날짜로 입력해 주세요.";
  if (ended > todaySeoul()) return "카드 사용 종료일은 서울 기준 오늘을 넘을 수 없어요.";
  if (started && isDateOnly(started) && ended < started) return "카드 사용 종료일은 사용 시작일과 같거나 늦어야 해요.";
  return "";
}
export function cardInput(draft: CardDraft): CardInput | null {
  if (!isUuid(draft.owner) || !draft.issuer.trim() || draft.issuer.trim().length > 120 || !draft.product.trim() || draft.product.trim().length > 120 || draft.alias.length > 80 || draft.note.length > 500 || draft.lastFour && !/^\d{4}$/.test(draft.lastFour) || draft.settlementDay && !/^(?:[1-9]|[12][0-9]|3[01])$/.test(draft.settlementDay) || draft.account && !isUuid(draft.account) || draft.started && !isDateOnly(draft.started) || cardEndDateError(draft.ended, draft.started)) return null;
  return { owner_member_id: draft.owner, issuer_name: draft.issuer.trim(), product_name: draft.product.trim(), alias: draft.alias.trim() || null, card_type: draft.type, last_four: draft.lastFour || null, settlement_day: draft.settlementDay ? Number(draft.settlementDay) : null, settlement_account_id: draft.account || null, started_on: draft.started || null, ended_on: draft.ended || null, note: draft.note.trim() || null };
}
export function preserveCardChanges(previous: CardDraft, draft: CardDraft, latest: CardDraft): CardDraft { return { ...latest, ...Object.fromEntries(Object.entries(draft).filter(([key, value]) => previous[key as keyof CardDraft] !== value)) }; }
