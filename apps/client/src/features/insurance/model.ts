import type { components, operations } from "@sallimbook/api-client";
import { isDateOnly } from "../finance/dates";
export type Schema = components["schemas"];
export type Policy = Schema["PolicyResponse"];
export type PolicyInput = Omit<Schema["PolicyCreate"], "policy_number">;
export type PolicyPatch = Omit<Schema["PolicyPatch"], "policy_number">;
export type Coverage = Schema["CoverageResponse"];
export type InsuranceCase = Schema["CaseResponse"];
export type CaseListItem = Schema["CaseListItem"];
export type MedicalNode = Schema["MedicalNodeResponse"];
export type PolicyQuery = NonNullable<operations["listInsurancePolicies"]["parameters"]["query"]>;
export type CaseQuery = NonNullable<operations["listInsuranceCases"]["parameters"]["query"]>;
export const policyStatuses = { active: "유지 중", ended: "계약 종료", lapsed: "실효" };
export const benefits = { reimbursement: "의료비 보전", fixed: "정액", other: "기타" };
export const treatments = { ongoing: "치료 중", ended: "치료 종료" };
export const finances = { open: "정산 중", settled: "정산 종료" };
export const nodeKinds = { outpatient: "외래", inpatient: "입원", surgery: "수술", prescription: "처방", pharmacy: "약국", follow_up: "추적 외래", group: "사용자 그룹" };
export const optional = (value: string) => value.trim() || null;
export const validPeriod = (start: string, end: string, required = false) => (!required || !!start) && (!start || isDateOnly(start)) && (!end || isDateOnly(end)) && (!start || !end || start <= end);
export function changedFields<T extends object>(before: T, after: T): Partial<T> { return Object.fromEntries(Object.entries(after).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(before[key as keyof T]))) as Partial<T>; }
export function preserveDraft<T extends object>(before: T, draft: T, current: T): T { return { ...current, ...changedFields(before, draft) }; }
export function descendants(nodes: MedicalNode[], root: string): Set<string> {
  const found = new Set([root]); let frontier = [root];
  while (frontier.length) { const next: string[] = []; for (const node of nodes) if (node.parent_id && frontier.includes(node.parent_id) && !found.has(node.id)) { found.add(node.id); next.push(node.id); } frontier = next; }
  return found;
}
export function ancestors(nodes: MedicalNode[], id: string): MedicalNode[] {
  const result: MedicalNode[] = []; const seen = new Set<string>(); let node = nodes.find((row) => row.id === id);
  while (node && !seen.has(node.id)) { seen.add(node.id); result.unshift(node); node = nodes.find((row) => row.id === node!.parent_id); }
  return result;
}
