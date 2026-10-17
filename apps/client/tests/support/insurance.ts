import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockCashflow, ruleRow } from "./cashflow";
import { jointAsset, uid } from "./finance";
type S = components["schemas"];
const entity = (id: number) => ({ id: uid(id), household_id: uid(3), version: 1, created_at: jointAsset.created_at, updated_at: jointAsset.updated_at, created_by_member_id: uid(2), updated_by_member_id: uid(2) });
export function policyRow(id = 80): S["PolicyResponse"] { return { ...entity(id), insurer: "합성 보험사", product_name: "합성 실손 계약", policyholder_member_id: uid(2), insured_member_id: uid(5), beneficiary_note: "합성 본인", contract_start: "2024-01-01", contract_end: "2030-12-31", coverage_start: "2024-02-01", coverage_end: "2030-11-30", payment_start: "2024-01-01", payment_end: "2028-12-31", status: "active", valuation_asset_id: null, note: "합성 계약 메모", masked_number: "••••ONLY", has_number: true }; }
export function caseRow(id = 90): S["CaseResponse"] { return { ...entity(id), title: "합성 독립 진료 사건", patient_member_id: uid(2), diagnosis_note: "합성 상세에서만 확인할 진단 설명", diagnosis_code: "SYNTHETIC-CODE", start_on: "2025-02-01", end_on: null, treatment_state: "ongoing", financial_state: "open" }; }
export function nodeRow(id = 91, patch: Partial<S["MedicalNodeResponse"]> = {}): S["MedicalNodeResponse"] { return { ...entity(id), case_id: uid(90), parent_id: null, kind: "outpatient", label: "합성 첫 외래", provider_name: "합성 의료기관", start_on: "2025-02-01", end_on: null, sort_order: 0, note: null, ...patch }; }
export function insuranceFixture() {
  const initial = caseRow();
  const state = {
    policies: [policyRow()], cases: [initial], nodes: [nodeRow(), nodeRow(92, { parent_id: uid(91), kind: "prescription", label: "합성 처방" }), nodeRow(93, { parent_id: uid(92), kind: "pharmacy", label: "합성 약국", provider_name: "합성 약국기관" })],
    coverages: [{ ...entity(81), policy_id: uid(80), name: "합성 미확인 보장", benefit_type: "reimbursement", insured_amount_krw: null, coverage_start: "2024-02-01", coverage_end: null, active: true, note: null }, { ...entity(82), policy_id: uid(80), name: "합성 명시적 0원 보장", benefit_type: "fixed", insured_amount_krw: "0", coverage_start: null, coverage_end: null, active: true, note: null }] as S["CoverageResponse"][],
    premiums: [{ ...entity(83), policy_id: uid(80), rule_id: uid(60), active: true, ended_at: null, rule: ruleRow() }] as S["PremiumLinkResponse"][],
    histories: new Map<string, S["CaseRevisionResponse"][]>([[initial.id, [{ ...initial, case_id: initial.id, changed_by_member_id: uid(2), changed_at: initial.updated_at, reason: null }]]]),
    writes: [] as { method: string; path: string; body: Record<string, unknown>; version: string | undefined }[], queries: [] as { path: string; query: URLSearchParams }[], pageSize: 200,
    conflict: "" as "" | "policy" | "coverage" | "case" | "node", failure: false, revealDelay: 0, revealDenied: false, revealCalls: 0, numberWriteKeys: [] as string[][],
  };
  const response = (json: unknown, status = 200) => ({ status, json }); const error = (code: string, status = 409) => response({ error: { code, message: "UNTRUSTED_INSURANCE_ERROR", request_id: "synthetic" } }, status);
  const page = <T extends { id: string }>(rows: T[], query: URLSearchParams) => { const offset = query.has("cursor") ? rows.findIndex((r) => r.id === query.get("cursor")) + 1 : 0; const items = rows.slice(offset, offset + state.pageSize); return { items, next_cursor: offset + items.length < rows.length ? items.at(-1)!.id : null }; };
  async function handle(method: string, path: string, query: URLSearchParams, body: Record<string, unknown> = {}, headers: Record<string, string> = {}) {
    const rest = path.replace("/api/v1/insurance/", "").split("/"); const [collection, id, child, childId] = rest;
    if (method === "GET") state.queries.push({ path, query });
    else if (child !== "reveal") {
      if (Object.hasOwn(body, "policy_number")) { state.numberWriteKeys.push(Object.keys(body)); }
      state.writes.push({ method, path, body: Object.fromEntries(Object.entries(body).filter(([key]) => key !== "policy_number")), version: headers["if-match"] });
      if (state.failure) { state.failure = false; return error("REQUEST_FAILED", 503); }
    }
    if (["claims", "payouts", "medical-expenses"].includes(collection!) && !id && method === "GET") return response({ items: [], next_cursor: null });
    if (collection === "policies") {
      if (!id && method === "GET") return response(page(state.policies.filter((p) => (!query.has("status") || p.status === query.get("status")) && (!query.has("insured_member_id") || p.insured_member_id === query.get("insured_member_id")) && (!query.has("policyholder_member_id") || p.policyholder_member_id === query.get("policyholder_member_id"))), query));
      if (!id && method === "POST") { const row = { ...policyRow(200 + state.policies.length), ...body, has_number: false, masked_number: null } as S["PolicyResponse"]; state.policies.push(row); return response(row, 201); }
      const row = state.policies.find((p) => p.id === id); if (!row) return error("NOT_FOUND", 404);
      if (child === "reveal") { state.revealCalls++; if (state.revealDelay) await new Promise((resolve) => setTimeout(resolve, state.revealDelay)); if (state.revealDenied) return error("REAUTHENTICATION_REQUIRED", 403); return response({ id: row.id, policy_number: "SYNTHETIC-POLICY-ONLY", display_for_seconds: 30 }); }
      if (child === "coverages") {
        if (method === "GET") return response(page(state.coverages.filter((c) => c.policy_id === id), query));
        if (method === "POST") { const added = { ...entity(300 + state.coverages.length), policy_id: id, ...body } as S["CoverageResponse"]; state.coverages.push(added); return response(added, 201); }
        const current = state.coverages.find((c) => c.id === childId && c.policy_id === id); if (!current) return error("NOT_FOUND", 404);
        if (state.conflict === "coverage") { state.conflict = ""; current.version++; current.note = "합성 다른 보장 메모"; }
        if (headers["if-match"] !== `"${current.version}"`) return error("VERSION_CONFLICT"); Object.assign(current, body, { version: current.version + 1 }); return response(current);
      }
      if (child === "premium-links") {
        if (method === "GET") return response(page(state.premiums.filter((p) => p.policy_id === id), query));
        if (method === "POST") { if (state.premiums.some((p) => p.rule_id === body.rule_id)) return error("PREMIUM_RULE_ALREADY_LINKED"); const added = { ...entity(400 + state.premiums.length), policy_id: id, rule_id: String(body.rule_id), active: true, ended_at: null, rule: ruleRow(Number(String(body.rule_id).slice(-12))) }; state.premiums.push(added); return response(added, 201); }
        const current = state.premiums.find((p) => p.id === childId); if (!current) return error("NOT_FOUND", 404); if (headers["if-match"] !== `"${current.version}"`) return error("VERSION_CONFLICT"); Object.assign(current, body, { version: current.version + 1 }); return response(current);
      }
      if (method === "GET") return response(row);
      if (state.conflict === "policy") { state.conflict = ""; row.version++; row.note = "합성 다른 계약 메모"; row.insurer = "합성 서버 보험사"; }
      if (headers["if-match"] !== `"${row.version}"`) return error("VERSION_CONFLICT");
      if (Object.hasOwn(body, "policy_number")) { row.has_number = body.policy_number !== null; row.masked_number = row.has_number ? "••••ONLY" : null; delete body.policy_number; }
      Object.assign(row, body, { version: row.version + 1 }); return response(row);
    }
    if (collection === "cases") {
      if (!id && method === "GET") return response(page(state.cases.filter((c) => (!query.has("patient_member_id") || c.patient_member_id === query.get("patient_member_id")) && (!query.has("treatment_state") || c.treatment_state === query.get("treatment_state")) && (!query.has("financial_state") || c.financial_state === query.get("financial_state"))).map(({ diagnosis_note: _note, diagnosis_code: _code, ...c }) => c), query));
      if (!id && method === "POST") { const row = { ...caseRow(500 + state.cases.length), ...body } as S["CaseResponse"]; state.cases.push(row); state.histories.set(row.id, [{ ...row, case_id: row.id, changed_at: row.updated_at, changed_by_member_id: uid(2), reason: null }]); return response(row, 201); }
      const row = state.cases.find((c) => c.id === id); if (!row) return error("NOT_FOUND", 404);
      if (child === "summary") return response({ case_id: id, medical_paid_krw: "0", medical_refunded_krw: "0", net_medical_krw: "0", insurance_received_krw: "0", insurance_returned_krw: "0", net_received_krw: "0", net_burden_krw: "0", benefits: [] });
      if (child === "history") { const all = [...state.histories.get(id!)!].reverse().filter((r) => !query.has("cursor") || r.version < Number(query.get("cursor"))); const items = all.slice(0, state.pageSize); return response({ items, next_cursor: items.length < all.length ? items.at(-1)!.version : null }); }
      if (child === "nodes") {
        if (method === "GET" && !childId) return response(page(state.nodes.filter((n) => n.case_id === id), query));
        if (method === "POST") { const added = { ...nodeRow(600 + state.nodes.length), ...body, case_id: id } as S["MedicalNodeResponse"]; state.nodes.push(added); return response(added, 201); }
        const current = state.nodes.find((n) => n.id === childId && n.case_id === id); if (!current) return error("NOT_FOUND", 404);
        if (rest[4] === "summary") return response({ case_id: id, node_id: childId, subtree_node_count: 1, medical_paid_krw: "0", medical_refunded_krw: "0", net_medical_krw: "0" });
        if (method === "GET") return response(current);
        if (state.conflict === "node") { state.conflict = ""; current.version++; current.note = "합성 다른 진료 메모"; }
        if (headers["if-match"] !== `"${current.version}"`) return error("VERSION_CONFLICT");
        if (method === "DELETE") { if (state.nodes.some((n) => n.parent_id === current.id)) return error("MEDICAL_NODE_IN_USE"); state.nodes = state.nodes.filter((n) => n.id !== current.id); return response(null, 204); }
        Object.assign(current, body, { version: current.version + 1 }); return response(current);
      }
      if (method === "GET") return response(row);
      if (state.conflict === "case") { state.conflict = ""; row.version++; row.diagnosis_note = "합성 다른 진단 메모"; }
      if (headers["if-match"] !== `"${row.version}"`) return error("VERSION_CONFLICT");
      Object.assign(row, Object.fromEntries(Object.entries(body).filter(([k]) => k !== "reason")), { version: row.version + 1 }); state.histories.get(id!)!.push({ ...row, case_id: row.id, changed_by_member_id: uid(2), changed_at: row.updated_at, reason: String(body.reason) }); return response(row);
    }
    return error("NOT_FOUND", 404);
  }
  return Object.assign(state, { handle });
}
export async function mockInsurance(page: Page) {
  const cashflow = await mockCashflow(page); const state = insuranceFixture();
  await page.route("**/api/v1/insurance/**", async (route) => { const url = new URL(route.request().url()); const result = await state.handle(route.request().method(), url.pathname, url.searchParams, route.request().postDataJSON() ?? {}, route.request().headers()); if (result.status === 204) return route.fulfill({ status: 204 }); return route.fulfill(result); });
  return Object.assign(state, { cashflow });
}
