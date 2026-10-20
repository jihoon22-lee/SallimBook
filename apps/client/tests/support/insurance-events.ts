import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import catalog from "../../../../packages/test-fixtures/catalog.json" with { type: "json" };
import { incomeRow } from "./cashflow";
import { insuranceFixture, mockInsurance, caseRow, nodeRow } from "./insurance";
import { uid } from "./finance";
type S = components["schemas"];
type Result = { status: number; body: unknown; abort?: boolean };
const timestamp = "2025-02-20T03:00:00Z";
const entity = (id: number) => ({
  id: uid(id),
  household_id: uid(3),
  version: 1,
  created_by_member_id: uid(2),
  updated_by_member_id: uid(2),
  created_at: timestamp,
  updated_at: timestamp,
});
export function expenseRow(id = 1000, amount = "30000"): S["ExpenseResponse"] {
  return {
    ...entity(id),
    version: 7,
    case_id: uid(90),
    node_id: uid(91),
    provider_name: "합성 의료기관",
    receipt_reference: `SYNTHETIC-RECEIPT-${id}`,
    gross_medical_krw: null,
    public_coverage_krw: null,
    correction_of_id: null,
    correction_reason: null,
    cash: incomeRow(id + 10000, {
      kind: "medical_payment",
      flow: "out",
      amount_krw: amount,
      date_precision: "day",
      occurred_on: "2025-02-10",
      editable: false,
      voidable: false,
    }),
    lines: [],
    line_count: 0,
  };
}
export function payoutRow(
  id = 1100,
  amount = "600000",
  benefit: S["BenefitType"] = "reimbursement",
): S["PayoutResponse"] {
  return {
    ...entity(id),
    version: 5,
    insurer_note: "합성 보험사 입금",
    correction_of_id: null,
    correction_reason: null,
    cash: incomeRow(id + 10000, {
      kind: "insurance_receipt",
      flow: "in",
      amount_krw: amount,
      date_precision: "day",
      occurred_on: "2025-02-15",
      editable: false,
      voidable: false,
    }),
    allocation_count: 1,
    allocations: [
      {
        ...entity(id + 1000),
        payout_id: uid(id),
        case_id: uid(90),
        policy_id: uid(80),
        claim_id: null,
        benefit_type: benefit,
        amount_krw: amount,
      },
    ],
  };
}
export function claimRow(id = 1200, expenses: string[] = []): S["ClaimResponse"] {
  return {
    ...entity(id),
    case_id: uid(90),
    policy_id: uid(80),
    claim_reference: `SYNTHETIC-CLAIM-${id}`,
    submitted_on: null,
    requested_krw: null,
    decided_krw: null,
    claim_state: "draft",
    decision_note: null,
    expense_ids: expenses,
    expense_count: expenses.length,
  };
}
export function insuranceEventsFixture(core: ReturnType<typeof insuranceFixture>) {
  core.cases.push({ ...caseRow(95), title: "합성 두 번째 사건" });
  core.nodes.push(nodeRow(96, { case_id: uid(95), label: "합성 다른 사건 진료" }));
  const state = {
    core,
    expenses: catalog.fixtures.medical_case.cash_records.map((r, i) =>
      expenseRow(1000 + i, r.amount_krw),
    ),
    payouts: catalog.fixtures.insurance_receipts.map((r, i) =>
      payoutRow(1100 + i, r.amount_krw, i ? "fixed" : "reimbursement"),
    ),
    refunds: [] as S["RefundResponse"][],
    returns: [] as S["ReturnResponse"][],
    claims: [] as S["ClaimResponse"][],
    histories: new Map<string, S["CashResponse"][]>(),
    claimHistories: new Map<string, S["ClaimRevisionResponse"][]>(),
    allocationHistories: new Map<string, S["AllocationRevisionResponse"][]>(),
    writes: [] as {
      path: string;
      method: string;
      body: Record<string, any>;
      key?: string;
      version?: string;
    }[],
    reads: [] as { path: string; query: URLSearchParams }[],
    pageSize: 200,
    nextId: 3000,
    failure: "" as "" | "before" | "after",
    conflict: false,
  };
  const response = (body: unknown, status = 200): Result => ({
    status,
    body: structuredClone(body),
  });
  const error = (code: string, status = 409) =>
    response(
      { error: { code, message: "UNTRUSTED_EVENT_ERROR", request_id: "synthetic" } },
      status,
    );
  const remember = (row: { id: string; cash: S["CashResponse"] }) => {
    const history = state.histories.get(row.id) ?? [];
    history.push(structuredClone(row.cash));
    state.histories.set(row.id, history);
  };
  const rememberClaim = (row: S["ClaimResponse"], reason: string | null = null) => {
    const history = state.claimHistories.get(row.id) ?? [];
    history.push({
      ...structuredClone(row),
      claim_id: row.id,
      changed_by_member_id: uid(2),
      changed_at: timestamp,
      reason,
    });
    state.claimHistories.set(row.id, history);
  };
  const rememberAllocation = (row: S["AllocationResponse"], reason: string | null = null) => {
    const history = state.allocationHistories.get(row.id) ?? [];
    history.push({
      ...structuredClone(row),
      allocation_id: row.id,
      changed_by_member_id: uid(2),
      changed_at: timestamp,
      reason,
    });
    state.allocationHistories.set(row.id, history);
  };
  for (const row of [...state.expenses, ...state.payouts]) remember(row);
  for (const row of state.payouts) for (const a of row.allocations) rememberAllocation(a);
  const page = <T extends { id: string }>(rows: T[], query: URLSearchParams) => {
    const offset = query.has("cursor")
      ? rows.findIndex((r) => r.id === query.get("cursor")) + 1
      : 0;
    const items = rows.slice(offset, offset + state.pageSize);
    return { items, next_cursor: offset + items.length < rows.length ? items.at(-1)!.id : null };
  };
  const historyPage = <T extends { version: number }>(rows: T[], query: URLSearchParams) => {
    const all = [...rows]
      .reverse()
      .filter((r) => !query.has("cursor") || r.version < Number(query.get("cursor")));
    const items = all.slice(0, state.pageSize);
    return { items, next_cursor: items.length < all.length ? items.at(-1)!.version : null };
  };
  const sum = (rows: { amount_krw: string }[]) =>
    rows.reduce((n, row) => n + BigInt(row.amount_krw), 0n);
  const caseSummary = (id: string) => {
    const expenses = state.expenses.filter((e) => e.case_id === id && e.cash.state === "active");
    const paid = sum(expenses.map((e) => e.cash));
    const refunded = sum(
      state.refunds
        .filter((r) => r.cash.state === "active" && expenses.some((e) => e.id === r.expense_id))
        .map((r) => r.cash),
    );
    const allocations = state.payouts
      .filter((p) => p.cash.state === "active")
      .flatMap((p) => p.allocations.filter((a) => a.case_id === id));
    const returnedRows = state.returns.filter(
      (r) =>
        r.cash.state === "active" && allocations.some((a) => a.id === r.original_allocation_id),
    );
    const received = sum(allocations);
    const returned = sum(returnedRows.map((r) => r.cash));
    return {
      case_id: id,
      medical_paid_krw: String(paid),
      medical_refunded_krw: String(refunded),
      net_medical_krw: String(paid - refunded),
      insurance_received_krw: String(received),
      insurance_returned_krw: String(returned),
      net_received_krw: String(received - returned),
      net_burden_krw: String(paid - refunded - received + returned),
      benefits: (["reimbursement", "fixed", "other"] as const).map((type) => {
        const parts = allocations.filter((a) => a.benefit_type === type);
        const returns = returnedRows.filter((r) =>
          parts.some((a) => a.id === r.original_allocation_id),
        );
        const received = sum(parts);
        const returned = sum(returns.map((r) => r.cash));
        return {
          benefit_type: type,
          received_krw: String(received),
          returned_krw: String(returned),
          net_received_krw: String(received - returned),
        };
      }),
    };
  };
  const receipts = new Map<string, Result>();
  function newCash(
    body: Record<string, any>,
    kind: S["CashResponse"]["kind"],
    parent?: S["CashResponse"],
  ): S["CashResponse"] {
    return incomeRow(state.nextId++, {
      kind,
      flow: ["medical_payment", "insurance_return"].includes(kind) ? "out" : "in",
      amount_krw: body.amount_krw,
      date_precision: "day",
      occurred_on: body.occurred_on,
      account_id: body.account_id ?? null,
      card_id: body.card_id ?? null,
      note: body.note ?? null,
      editable: false,
      voidable: false,
      reason: body.reason ?? null,
      reverses_id: parent?.id ?? null,
    });
  }
  function createExpense(body: Record<string, any>, original?: string) {
    const id = state.nextId++;
    const { reason: _reason, ...input } = body;
    const row = {
      ...expenseRow(id),
      ...input,
      id: uid(id),
      version: 1,
      correction_of_id: original ?? null,
      correction_reason: body.reason ?? null,
      cash: newCash(body, "medical_payment"),
      lines: (body.lines ?? []).map((l: S["ExpenseLineInput"]) => ({
        ...l,
        id: uid(state.nextId++),
      })),
      line_count: body.lines?.length ?? 0,
    };
    state.expenses.push(row);
    remember(row);
    return row;
  }
  function createPayout(body: Record<string, any>, original?: string) {
    const id = state.nextId++;
    const { reason: _reason, ...input } = body;
    const row = {
      ...payoutRow(id),
      ...input,
      id: uid(id),
      version: 1,
      correction_of_id: original ?? null,
      correction_reason: body.reason ?? null,
      cash: newCash(body, "insurance_receipt"),
      allocations: body.allocations.map((a: S["AllocationInput"]) => ({
        ...entity(state.nextId++),
        ...a,
        payout_id: uid(id),
      })),
      allocation_count: body.allocations.length,
    };
    state.payouts.push(row);
    remember(row);
    row.allocations.forEach(rememberAllocation);
    return row;
  }
  function makeVoid(row: { id: string; version: number; cash: S["CashResponse"] }, reason: string) {
    row.cash.state = "void";
    row.cash.version++;
    row.cash.action = "void";
    row.cash.reason = reason;
    row.version++;
    remember(row);
  }
  async function handle(
    method: string,
    path: string,
    query: URLSearchParams,
    body: Record<string, any> = {},
    headers: Record<string, string> = {},
  ): Promise<Result> {
    const [collection, id, action, childId, subAction] = path
      .replace("/api/v1/insurance/", "")
      .split("/");
    if (method === "GET") {
      state.reads.push({ path, query });
      if (collection === "cases" && action === "summary") return response(caseSummary(id!));
      if (collection === "cases" && action === "nodes" && subAction === "summary") {
        const ids = new Set([childId]);
        let prior = 0;
        while (prior !== ids.size) {
          prior = ids.size;
          for (const node of core.nodes) if (ids.has(node.parent_id ?? "")) ids.add(node.id);
        }
        const rows = state.expenses.filter((e) => ids.has(e.node_id) && e.cash.state === "active");
        const paid = sum(rows.map((e) => e.cash));
        const refunded = sum(
          state.refunds
            .filter((r) => r.cash.state === "active" && rows.some((e) => e.id === r.expense_id))
            .map((r) => r.cash),
        );
        return response({
          case_id: id,
          node_id: childId,
          subtree_node_count: ids.size,
          medical_paid_krw: String(paid),
          medical_refunded_krw: String(refunded),
          net_medical_krw: String(paid - refunded),
        });
      }
      if (collection === "medical-expenses") {
        if (!id)
          return response(
            page(
              state.expenses.filter(
                (e) =>
                  (!query.has("case_id") || e.case_id === query.get("case_id")) &&
                  (!query.has("node_id") || e.node_id === query.get("node_id")) &&
                  (!query.has("state") || e.cash.state === query.get("state")),
              ),
              query,
            ),
          );
        if (action === "refunds")
          return response(
            page(
              state.refunds.filter((r) => r.expense_id === id),
              query,
            ),
          );
      }
      if (collection === "payouts") {
        if (!id)
          return response(
            page(
              state.payouts.filter((p) =>
                p.allocations.some(
                  (a) =>
                    (!query.has("case_id") || a.case_id === query.get("case_id")) &&
                    (!query.has("policy_id") || a.policy_id === query.get("policy_id")) &&
                    (!query.has("claim_id") || a.claim_id === query.get("claim_id")),
                ),
              ),
              query,
            ),
          );
        if (action === "returns")
          return response(
            page(
              state.returns.filter((r) => r.payout_id === id),
              query,
            ),
          );
      }
      if (collection === "claims") {
        if (!id)
          return response(
            page(
              state.claims.filter(
                (c) =>
                  (!query.has("case_id") || c.case_id === query.get("case_id")) &&
                  (!query.has("policy_id") || c.policy_id === query.get("policy_id")),
              ),
              query,
            ),
          );
        const claim = state.claims.find((c) => c.id === id);
        if (!claim) return error("NOT_FOUND", 404);
        if (action === "history")
          return response(
            historyPage(
              state.claimHistories.get(id) ?? [
                {
                  ...claim,
                  claim_id: claim.id,
                  changed_at: timestamp,
                  changed_by_member_id: uid(2),
                  reason: null,
                },
              ],
              query,
            ),
          );
        return response(claim);
      }
      if (collection === "payout-allocations") {
        const a = state.payouts.flatMap((p) => p.allocations).find((a) => a.id === id);
        if (!a) return error("NOT_FOUND", 404);
        return response(
          action === "history" ? historyPage(state.allocationHistories.get(id!) ?? [], query) : a,
        );
      }
      const rows =
        collection === "medical-expenses"
          ? state.expenses
          : collection === "medical-refunds"
            ? state.refunds
            : collection === "payouts"
              ? state.payouts
              : collection === "returns"
                ? state.returns
                : null;
      if (rows) {
        const row = rows.find((r) => r.id === id);
        if (!row) return error("NOT_FOUND", 404);
        return response(
          action === "history" ? historyPage(state.histories.get(id!) ?? [], query) : row,
        );
      }
      const fallback = await core.handle(method, path, query, body, headers);
      return response(fallback.json, fallback.status);
    }
    if (
      ![
        "medical-expenses",
        "medical-refunds",
        "payouts",
        "returns",
        "claims",
        "payout-allocations",
      ].includes(collection!)
    ) {
      const fallback = await core.handle(method, path, query, body, headers);
      return response(fallback.json, fallback.status);
    }
    state.writes.push({
      method,
      path,
      body: structuredClone(body),
      key: headers["idempotency-key"],
      version: headers["if-match"],
    });
    const receiptKey = headers["idempotency-key"];
    if (receiptKey && receipts.has(receiptKey)) return structuredClone(receipts.get(receiptKey)!);
    if (state.failure === "before") {
      state.failure = "";
      return { status: 0, body: null, abort: true };
    }
    const finish = (row: { id: string; version: number }, status = 201) => {
      const result = response({ id: row.id, version: row.version }, status);
      if (receiptKey) receipts.set(receiptKey, result);
      if (state.failure === "after") {
        state.failure = "";
        return { status: 0, body: null, abort: true };
      }
      return result;
    };
    if (collection === "claims") {
      if (!id) {
        const row = {
          ...claimRow(state.nextId++),
          ...body,
          expense_count: body.expense_ids?.length ?? 0,
        };
        state.claims.push(row);
        rememberClaim(row);
        return response(row, 201);
      }
      const row = state.claims.find((c) => c.id === id);
      if (!row) return error("NOT_FOUND", 404);
      if (!state.claimHistories.has(id!)) rememberClaim(row);
      if (state.conflict) {
        state.conflict = false;
        row.version++;
        row.decision_note = "합성 다른 심사 메모";
      }
      if (headers["if-match"] !== `"${row.version}"`) return error("VERSION_CONFLICT");
      Object.assign(row, body, {
        version: row.version + 1,
        expense_count: body.expense_ids?.length ?? row.expense_count,
      });
      rememberClaim(row, body.reason);
      return response(row);
    }
    if (collection === "payout-allocations") {
      const parent = state.payouts.find((p) => p.allocations.some((a) => a.id === id));
      const a = parent?.allocations.find((a) => a.id === id);
      if (!parent || !a) return error("NOT_FOUND", 404);
      if (state.conflict) {
        state.conflict = false;
        a.version++;
        parent.version++;
      }
      if (headers["if-match"] !== `"${a.version}"`) return error("VERSION_CONFLICT");
      Object.assign(a, Object.fromEntries(Object.entries(body).filter(([k]) => k !== "reason")), {
        version: a.version + 1,
      });
      parent.version++;
      rememberAllocation(a, body.reason);
      return finish(a, 200);
    }
    if (!id && collection === "medical-expenses") return finish(createExpense(body));
    if (!id && collection === "payouts") return finish(createPayout(body));
    const rows =
      collection === "medical-expenses"
        ? state.expenses
        : collection === "medical-refunds"
          ? state.refunds
          : collection === "payouts"
            ? state.payouts
            : state.returns;
    const row = rows.find((r) => r.id === id);
    if (!row) return error("NOT_FOUND", 404);
    if (state.conflict) {
      state.conflict = false;
      row.version++;
      row.cash.note = "합성 다른 원본 메모";
    }
    if (headers["if-match"] !== `"${row.version}"`) return error("VERSION_CONFLICT");
    if (row.cash.state !== "active") return error("EVENT_ALREADY_VOID");
    if (action === "refunds" || (collection === "medical-refunds" && action === "correct")) {
      const original = "expense_id" in row ? row : undefined;
      const parent = original
        ? state.expenses.find((e) => e.id === original.expense_id)!
        : state.expenses.find((e) => e.id === row.id)!;
      if (original) makeVoid(original, body.reason);
      const refund = {
        ...entity(state.nextId++),
        expense_id: parent.id,
        correction_of_id: original?.id ?? null,
        reason: body.reason,
        cash: newCash(body, "medical_refund", parent.cash),
      };
      parent.version++;
      state.refunds.push(refund);
      remember(refund);
      return finish(refund);
    }
    if (action === "returns" || (collection === "returns" && action === "correct")) {
      const original = "payout_id" in row ? row : undefined;
      const parent = original
        ? state.payouts.find((p) => p.id === original.payout_id)!
        : state.payouts.find((p) => p.id === row.id)!;
      if (original) makeVoid(original, body.reason);
      const returned = {
        ...entity(state.nextId++),
        payout_id: parent.id,
        original_allocation_id: body.original_allocation_id,
        correction_of_id: original?.id ?? null,
        reason: body.reason,
        cash: newCash(body, "insurance_return", parent.cash),
      };
      parent.version++;
      state.returns.push(returned);
      remember(returned);
      return finish(returned);
    }
    if (collection === "medical-expenses") {
      if (state.refunds.some((r) => r.expense_id === row.id && r.cash.state === "active"))
        return error("MEDICAL_EXPENSE_HAS_REFUNDS");
      if (state.claims.some((c) => c.expense_ids.includes(row.id)))
        return error("MEDICAL_EXPENSE_IN_CLAIM");
    }
    if (
      collection === "payouts" &&
      state.returns.some((r) => r.payout_id === row.id && r.cash.state === "active")
    )
      return error("INSURANCE_PAYOUT_HAS_RETURNS");
    makeVoid(row, body.reason);
    if (action === "correct")
      return finish(
        collection === "medical-expenses"
          ? createExpense(body, row.id)
          : createPayout(body, row.id),
      );
    if ("expense_id" in row) state.expenses.find((e) => e.id === row.expense_id)!.version++;
    if ("payout_id" in row) state.payouts.find((p) => p.id === row.payout_id)!.version++;
    return finish(row, 200);
  }
  return Object.assign(state, { handle, caseSummary });
}
export async function mockInsuranceEvents(page: Page) {
  const core = await mockInsurance(page);
  const events = insuranceEventsFixture(core);
  await page.route("**/api/v1/insurance/**", async (route) => {
    const url = new URL(route.request().url());
    const result = await events.handle(
      route.request().method(),
      url.pathname,
      url.searchParams,
      route.request().postDataJSON() ?? {},
      route.request().headers(),
    );
    if (result.abort) return route.abort("failed");
    if (result.status === 204) return route.fulfill({ status: 204 });
    return route.fulfill({ status: result.status, json: result.body });
  });
  return Object.assign(events, { cashflow: core.cashflow });
}
