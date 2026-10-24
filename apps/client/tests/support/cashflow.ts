import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockFinance, uid } from "./finance";
type S = components["schemas"];
type Result = { status: number; body: unknown; abort?: boolean };
export type Write = {
  method: string;
  path: string;
  body: Record<string, any>;
  key?: string;
  version?: string;
};
const timestamp = "2025-02-20T03:00:00Z";
export function incomeRow(id: number, patch: Partial<S["CashResponse"]> = {}): S["CashResponse"] {
  return {
    id: uid(id),
    household_id: uid(3),
    kind: "salary",
    flow: "in",
    amount_krw: "3000000",
    period_month: "2025-02",
    occurred_on: null,
    date_precision: "month",
    member_id: uid(2),
    account_id: uid(30),
    card_id: null,
    reverses_id: null,
    state: "active",
    note: null,
    created_by_member_id: uid(2),
    updated_by_member_id: uid(2),
    created_at: timestamp,
    updated_at: timestamp,
    version: 1,
    action: "create",
    reason: null,
    conversion_id: null,
    editable: true,
    voidable: true,
    ...patch,
  };
}
export const sampleCard: S["CardResponse"] = {
  id: uid(50),
  household_id: uid(3),
  owner_member_id: uid(2),
  issuer_name: "합성 카드사",
  product_name: "합성 생활 카드",
  alias: "합성 구독 카드",
  card_type: "credit",
  last_four: "1111",
  masked_number: "•••• 1111",
  has_secret: false,
  settlement_day: 15,
  settlement_account_id: uid(30),
  settlement_account_status: "active",
  started_on: "2024-01-01",
  ended_on: null,
  status: "active",
  note: null,
  created_by_member_id: uid(2),
  updated_by_member_id: uid(2),
  created_at: timestamp,
  updated_at: timestamp,
  version: 1,
};
export function ruleRow(id = 60, patch: Partial<S["RuleVersionResponse"]> = {}): S["RuleResponse"] {
  return {
    id: uid(id),
    household_id: uid(3),
    version: 1,
    ended_on: null,
    end_reason: null,
    versions: [
      {
        id: uid(id + 100),
        effective_from: "2025-01-01",
        effective_until: null,
        reason: null,
        created_at: timestamp,
        title: "합성 AI 구독",
        category: "구독",
        amount_mode: "fixed",
        expected_amount_krw: "33000",
        economic_type: "expense",
        loan_asset_id: null,
        account_id: null,
        card_id: uid(50),
        currency_reference: "USD",
        foreign_amount_reference: "20",
        note: null,
        anchor_date: "2025-01-31",
        frequency: "monthly",
        interval_count: 1,
        ...patch,
      },
    ],
  };
}
export function obligationRow(
  id = 70,
  patch: Partial<S["ObligationResponse"]> = {},
): S["ObligationResponse"] {
  return {
    id: uid(id),
    household_id: uid(3),
    rule_id: uid(60),
    rule_version_id: uid(160),
    version: 1,
    title: "합성 AI 구독",
    category: "구독",
    amount_mode: "fixed",
    expected_amount_krw: "33000",
    economic_type: "expense",
    loan_asset_id: null,
    account_id: null,
    card_id: uid(50),
    currency_reference: "USD",
    foreign_amount_reference: "20",
    note: null,
    nominal_date: "2025-02-28",
    scheduled_date: "2025-02-28",
    schedule_state: "active",
    manual_override: false,
    skipped: false,
    manually_completed: false,
    status: "unpaid",
    actual_amount_krw: "0",
    difference_krw: "-33000",
    consumption_krw: "0",
    principal_krw: "0",
    asset_transfer_krw: "0",
    created_at: timestamp,
    updated_at: timestamp,
    ...patch,
  };
}
export async function mockCashflow(page: Page) {
  const finance = await mockFinance(page);
  finance.assets[2]!.status = "active";
  finance.assets[2]!.ended_on = null;
  const incomes = [
    incomeRow(40),
    incomeRow(41, {
      kind: "bonus",
      member_id: uid(5),
      amount_krw: "200000",
      date_precision: "day",
      occurred_on: "2025-02-10",
    }),
    incomeRow(42, {
      kind: "insurance_receipt",
      amount_krw: "800000",
      member_id: uid(5),
      date_precision: "day",
      occurred_on: "2025-02-15",
      editable: false,
      voidable: false,
    }),
  ];
  const state = {
    finance,
    incomes,
    cards: [structuredClone(sampleCard)],
    rules: [
      ruleRow(),
      ruleRow(61, {
        title: "합성 대출 원리금",
        economic_type: "loan",
        category: "대출",
        expected_amount_krw: "1000000",
        card_id: null,
        account_id: uid(30),
        loan_asset_id: uid(12),
        currency_reference: null,
        foreign_amount_reference: null,
      }),
    ],
    obligations: [
      obligationRow(),
      obligationRow(71, {
        rule_id: uid(61),
        rule_version_id: uid(161),
        title: "합성 대출 원리금",
        category: "대출",
        economic_type: "loan",
        expected_amount_krw: "1000000",
        difference_krw: "-1000000",
        card_id: null,
        account_id: uid(30),
        loan_asset_id: uid(12),
        currency_reference: null,
        foreign_amount_reference: null,
      }),
      obligationRow(72, {
        title: "합성 미정 납부",
        expected_amount_krw: null,
        difference_krw: null,
        amount_mode: "variable",
      }),
    ],
    payments: [] as S["SettlementResponse"][],
    writes: [] as Write[],
    reads: [] as { path: string; query: URLSearchParams }[],
    insuranceSources: new Map<string, S["IncomeInsuranceSource"]>(),
    ruleInsuranceLinks: new Map<string, S["RuleInsuranceLink"]>(),
    incomeHistory: new Map<string, S["CashResponse"][]>(),
    obligationHistory: new Map<string, S["ObligationHistoryItem"][]>(),
    failure: "" as "" | "before" | "after",
    failurePath: "",
    conflict: false,
    conflictPath: "",
    withdrawalBlocked: false,
    ruleInUse: false,
    staleReceipt: false,
    pageSize: 50,
    nextId: 300,
    linksRequired: false,
    linksVersion: 1,
    linksRace: false,
    linksMore: false,
    linksQueries: [] as URLSearchParams[],
  };
  const response = (body: unknown, status = 200): Result => ({
    status,
    body: structuredClone(body),
  });
  const error = (code: string, status = 409) =>
    response(
      { error: { code, message: "UNTRUSTED_SYNTHETIC_MESSAGE", request_id: "synthetic" } },
      status,
    );
  const receipt = (row: S["CashResponse"]) => ({ ...row, editable: false, voidable: false });
  const current = (row: S["CashResponse"]) => {
    const hasReturn = state.incomes.some((r) => r.reverses_id === row.id && r.state === "active");
    return {
      ...row,
      editable:
        row.state === "active" &&
        ["salary", "bonus", "other_income"].includes(row.kind) &&
        !hasReturn,
      voidable:
        row.state === "active" &&
        ["salary", "bonus", "other_income", "income_return"].includes(row.kind) &&
        !hasReturn,
    };
  };
  const rememberIncome = (row: S["CashResponse"]) => {
    const list = state.incomeHistory.get(row.id) ?? [];
    list.push(structuredClone(receipt(row)));
    state.incomeHistory.set(row.id, list);
  };
  state.incomes.forEach(rememberIncome);
  const rememberObligation = (
    row: S["ObligationResponse"],
    action: S["ObligationHistoryItem"]["action"],
    reason: string | null = null,
  ) => {
    const list = state.obligationHistory.get(row.id) ?? [];
    list.push({
      id: row.id,
      version: row.version,
      rule_version_id: row.rule_version_id,
      expected_amount_krw: row.expected_amount_krw,
      nominal_date: row.nominal_date,
      scheduled_date: row.scheduled_date,
      schedule_state: row.schedule_state,
      manual_override: row.manual_override,
      skipped: row.skipped,
      manually_completed: row.manually_completed,
      action,
      reason,
      updated_at: timestamp,
    });
    state.obligationHistory.set(row.id, list);
  };
  state.obligations.forEach((row) => rememberObligation(row, "create"));
  const pageRows = <T extends { id: string }>(rows: T[], query: URLSearchParams) => {
    const sorted = [...rows].sort((a, b) => a.id.localeCompare(b.id));
    const cursor = query.get("cursor");
    const index = cursor ? sorted.findIndex((row) => row.id === cursor) + 1 : 0;
    const count = Math.min(Number(query.get("limit") ?? 50), state.pageSize);
    const items = sorted.slice(index, index + count);
    return { items, next_cursor: index + count < sorted.length ? items.at(-1)!.id : null };
  };
  const totals = (rows: S["CashResponse"][]): S["IncomeTotalsResponse"] => {
    const sum = (kind: string) =>
      rows.filter((row) => row.kind === kind).reduce((n, row) => n + BigInt(row.amount_krw), 0n);
    const salary = sum("salary"),
      bonus = sum("bonus"),
      other = sum("other_income"),
      returned = sum("income_return"),
      insurance = sum("insurance_receipt"),
      insuranceReturned = sum("insurance_return");
    return {
      salary_krw: String(salary),
      bonus_krw: String(bonus),
      other_income_krw: String(other),
      income_returns_krw: String(returned),
      insurance_receipts_krw: String(insurance),
      insurance_returns_krw: String(insuranceReturned),
      earned_net_krw: String(salary + bonus + other - returned),
      insurance_net_krw: String(insurance - insuranceReturned),
      net_inflow_krw: String(salary + bonus + other - returned + insurance - insuranceReturned),
      record_count: rows.length,
    };
  };
  const refreshObligation = (row: S["ObligationResponse"]) => {
    const payments = state.payments.filter(
      (p) => p.obligation_id === row.id && p.cash.state === "active",
    );
    const sum = (key: "principal_krw" | "consumption_krw" | "asset_transfer_krw") =>
      String(payments.reduce((n, p) => n + BigInt(p[key]), 0n));
    row.actual_amount_krw = String(payments.reduce((n, p) => n + BigInt(p.cash.amount_krw), 0n));
    row.principal_krw = sum("principal_krw");
    row.consumption_krw = sum("consumption_krw");
    row.asset_transfer_krw = sum("asset_transfer_krw");
    row.difference_krw =
      row.expected_amount_krw === null
        ? null
        : String(BigInt(row.actual_amount_krw) - BigInt(row.expected_amount_krw));
    row.status =
      row.schedule_state === "superseded"
        ? "superseded"
        : row.skipped
          ? "skipped"
          : row.manually_completed ||
              (BigInt(row.actual_amount_krw) > 0n &&
                (row.expected_amount_krw === null ||
                  BigInt(row.actual_amount_krw) >= BigInt(row.expected_amount_krw)))
            ? "paid"
            : row.actual_amount_krw !== "0"
              ? "partial"
              : "unpaid";
  };
  const receipts = new Map<string, { fingerprint: string; result: Result }>();
  function usage(
    kind: "card" | "account",
    id: string,
    query: URLSearchParams,
  ): S["PaymentLinksResponse"] {
    state.linksQueries.push(query);
    if (query.has("rule_cursor") && state.linksRace) {
      state.linksRace = false;
      state.linksVersion++;
    }
    const date = query.get("as_of_date") ?? "2025-02-20";
    const linked = state.linksRequired;
    const rule = state.rules[0]!.versions[0]!;
    const rules = linked
      ? [0, ...(state.linksMore ? [1] : [])].map((index) => ({
          id: uid(160 + index),
          rule_id: uid(60 + index),
          rule_version: 1,
          title: index ? "합성 미래 연간 구독" : rule.title,
          category: rule.category,
          amount_mode: rule.amount_mode,
          expected_amount_krw: rule.expected_amount_krw ?? null,
          economic_type: rule.economic_type,
          account_id: kind === "account" ? id : null,
          card_id: kind === "card" ? id : null,
          payment_basis:
            kind === "card" ? ("card_approval_plan" as const) : ("account_payment_plan" as const),
          period: index ? ("future" as const) : ("current" as const),
          effective_from: index ? "2025-12-01" : "2025-01-01",
          effective_until: null,
          anchor_date: rule.anchor_date,
          frequency: index ? ("annual" as const) : rule.frequency,
          interval_count: rule.interval_count,
        }))
      : [];
    const ruleCursor = query.get("rule_cursor");
    const selected = ruleCursor
      ? rules.filter((r) => r.id > ruleCursor)
      : state.linksMore
        ? rules.slice(0, 1)
        : rules;
    return {
      resource_kind: kind,
      resource_id: id,
      resource_version: kind === "card" ? (state.cards.find((r) => r.id === id)?.version ?? 1) : 1,
      asset_id: kind === "account" ? uid(11) : null,
      as_of_date: date,
      usage_digest: String(state.linksVersion).padStart(64, "0"),
      requires_confirmation: linked,
      coverage: "registered_recurring_only",
      account_withdrawal_total_available: false,
      rules: {
        items: selected,
        total_count: rules.length,
        next_cursor: !ruleCursor && state.linksMore && rules.length > 1 ? rules[0]!.id : null,
      },
      obligations: { items: [], total_count: 0, next_cursor: null },
      cards: {
        items:
          kind === "account" && linked
            ? [
                {
                  id: uid(50),
                  version: 1,
                  issuer_name: sampleCard.issuer_name,
                  product_name: sampleCard.product_name,
                  alias: sampleCard.alias,
                  last_four: sampleCard.last_four,
                  ended_on: null,
                  active_for_closure: true,
                },
              ]
            : [],
        total_count: kind === "account" && linked ? 1 : 0,
        next_cursor: null,
      },
    };
  }
  async function handle(
    method: string,
    path: string,
    query = new URLSearchParams(),
    body: Record<string, any> = {},
    headers: Record<string, string> = {},
  ): Promise<Result | undefined> {
    if (path.startsWith("/api/v1/assets/") && method !== "GET" && body.ended_on) {
      const id = path.split("/")[4]!;
      const row = state.finance.assets.find((asset) => asset.id === id);
      if (!row) return error("NOT_FOUND", 404);
      state.writes.push({
        method,
        path,
        body: structuredClone(body),
        version: headers["if-match"],
      });
      if (headers["if-match"] !== `"${row.version}"`) return error("VERSION_CONFLICT");
      const account = state.finance.accounts.find((candidate) => candidate.asset_id === id);
      if (account && state.linksRequired) {
        if (!body.closure_ack) return error("PAYMENT_LINK_CONFIRMATION_REQUIRED");
        if (body.usage_digest !== String(state.linksVersion).padStart(64, "0"))
          return error("PAYMENT_LINKS_CHANGED");
      }
      const { closure_ack: _ack, usage_digest: _digest, ...input } = body;
      Object.assign(row, input, { status: "archived", version: row.version + 1 });
      if (account) {
        account.closed_on = body.ended_on;
        account.status = "closed";
        account.asset = structuredClone(row);
      }
      return response(row);
    }
    if (
      !/^\/api\/v1\/(income|cards|recurring-rules|obligations|settlements)(\/|$)/.test(path) &&
      !/\/payment-links$/.test(path)
    )
      return undefined;
    const parts = path.split("/");
    const domain = parts[3]!,
      id = parts[4],
      action = parts[5];
    if (method === "GET") {
      state.reads.push({ path, query });
      if (domain === "income" && action === "insurance-source")
        return response(
          state.insuranceSources.get(id!) ?? {
            record_id: id,
            payout_id: null,
            return_id: null,
            original_allocation_id: null,
            allocations: [],
          },
        );
      if (domain === "recurring-rules" && action === "insurance-link")
        return response(state.ruleInsuranceLinks.get(id!) ?? { rule_id: id, link: null });
      if (action === "payment-links")
        return response(usage(domain === "cards" ? "card" : "account", id!, query));
      if (domain === "income") {
        const rows = state.incomes.filter(
          (r) =>
            r.period_month === query.get("month") &&
            (!query.has("member_id") || r.member_id === query.get("member_id")) &&
            (!query.has("kind") || r.kind === query.get("kind")),
        );
        if (!id)
          return response(
            pageRows(
              rows
                .filter(
                  (r) =>
                    query.get("state") === "all" || r.state === (query.get("state") ?? "active"),
                )
                .map(current),
              query,
            ),
          );
        if (id === "summary") {
          const active = rows.filter((r) => r.state === "active");
          return response({
            period_month: query.get("month"),
            totals: totals(active),
            members: [...new Set(active.map((r) => r.member_id))].map((member_id) => ({
              member_id,
              totals: totals(active.filter((r) => r.member_id === member_id)),
            })),
          });
        }
        if (id === "duplicates") {
          const found = rows.filter(
            (r) => r.state === "active" && r.date_precision !== query.get("date_precision"),
          );
          return response({
            suspected: !!found.length,
            items: found.slice(0, 20).map(current),
            truncated: found.length > 20,
          });
        }
        const row = state.incomes.find((r) => r.id === id);
        if (!row) return error("NOT_FOUND", 404);
        if (action === "history") {
          const history = [...state.incomeHistory.get(id)!]
            .reverse()
            .filter((r) => !query.has("cursor") || r.version < Number(query.get("cursor")));
          const items = history.slice(0, state.pageSize);
          return response({
            items,
            next_cursor: history.length > items.length ? items.at(-1)!.version : null,
          });
        }
        return response(current(row));
      }
      if (domain === "cards") {
        if (id) {
          const row = state.cards.find((r) => r.id === id);
          return row ? response(row) : error("NOT_FOUND", 404);
        }
        return response(
          pageRows(
            state.cards.filter(
              (r) =>
                (query.get("status") === "all" || r.status === (query.get("status") ?? "active")) &&
                (!query.has("card_type") || r.card_type === query.get("card_type")) &&
                (!query.has("owner_member_id") ||
                  r.owner_member_id === query.get("owner_member_id")) &&
                (!query.has("settlement_account_id") ||
                  r.settlement_account_id === query.get("settlement_account_id")),
            ),
            query,
          ),
        );
      }
      if (domain === "recurring-rules") {
        if (!id) return response(pageRows(state.rules, query));
        const row = state.rules.find((r) => r.id === id);
        return row ? response(row) : error("NOT_FOUND", 404);
      }
      if (domain === "obligations") {
        if (id === "summary") {
          const expected = state.obligations.filter(
            (r) =>
              r.scheduled_date.startsWith(query.get("month")!) &&
              !r.skipped &&
              r.schedule_state === "active",
          );
          const actual = state.payments.filter(
            (p) => p.cash.state === "active" && p.cash.occurred_on!.startsWith(query.get("month")!),
          );
          return response({
            expected_known_krw: String(
              expected.reduce((n, r) => n + BigInt(r.expected_amount_krw ?? "0"), 0n),
            ),
            unknown_expected_count: expected.filter((r) => r.expected_amount_krw === null).length,
            actual_amount_krw: String(actual.reduce((n, p) => n + BigInt(p.cash.amount_krw), 0n)),
            consumption_krw: String(actual.reduce((n, p) => n + BigInt(p.consumption_krw), 0n)),
            principal_krw: String(actual.reduce((n, p) => n + BigInt(p.principal_krw), 0n)),
            asset_transfer_krw: String(
              actual.reduce((n, p) => n + BigInt(p.asset_transfer_krw), 0n),
            ),
            obligation_count: expected.length,
          });
        }
        if (!id)
          return response(
            pageRows(
              state.obligations.filter((r) => r.scheduled_date.startsWith(query.get("month")!)),
              query,
            ),
          );
        const row = state.obligations.find((r) => r.id === id);
        if (!row) return error("NOT_FOUND", 404);
        if (action === "settlements")
          return response(
            pageRows(
              state.payments.filter((p) => p.obligation_id === id),
              query,
            ),
          );
        if (action === "history") {
          const history = [...state.obligationHistory.get(id)!]
            .reverse()
            .filter((r) => !query.has("cursor") || r.version < Number(query.get("cursor")));
          const items = history.slice(0, state.pageSize);
          return response({
            items,
            next_cursor: history.length > items.length ? items.at(-1)!.version : null,
          });
        }
        return response(row);
      }
      return error("NOT_FOUND", 404);
    }
    const key = headers["idempotency-key"],
      version = headers["if-match"];
    state.writes.push({ method, path, body: structuredClone(body), key, version });
    const fingerprint = JSON.stringify([version, body]);
    const receiptKey = `${path}:${key}`;
    if (key && receipts.has(receiptKey)) {
      const previous = receipts.get(receiptKey)!;
      return previous.fingerprint === fingerprint
        ? structuredClone(previous.result)
        : error("IDEMPOTENCY_CONFLICT");
    }
    if (state.failure === "before" && (!state.failurePath || state.failurePath === path)) {
      state.failure = "";
      return { status: 0, body: null, abort: true };
    }
    const finish = (value: Result) => {
      if (key && value.status < 300)
        receipts.set(receiptKey, { fingerprint, result: structuredClone(value) });
      if (
        state.failure === "after" &&
        value.status < 300 &&
        (!state.failurePath || state.failurePath === path)
      ) {
        state.failure = "";
        return { status: 0, body: null, abort: true };
      }
      return value;
    };
    if (domain === "income") {
      if (id === "convert") {
        const sources = body.sources.map((source: { id: string }) =>
          state.incomes.find((r) => r.id === source.id),
        );
        if (
          sources.some(
            (r: S["CashResponse"] | undefined, i: number) =>
              !r || r.version !== body.sources[i].version,
          )
        )
          return error("VERSION_CONFLICT");
        const sum = (rows: { amount_krw: string }[]) =>
          rows.reduce((n, r) => n + BigInt(r.amount_krw), 0n);
        if (sum(sources) !== sum(body.replacements)) return error("CONVERSION_TOTAL_MISMATCH", 422);
        const convertedId = uid(state.nextId++);
        for (const row of sources) {
          row.state = "void";
          row.action = "convert_source";
          row.version++;
          row.reason = body.reason;
          row.conversion_id = convertedId;
          rememberIncome(row);
        }
        const replacements = body.replacements.map((input: Record<string, any>) => {
          const row = incomeRow(state.nextId++, {
            ...input,
            action: "convert_result",
            conversion_id: convertedId,
            reason: body.reason,
          });
          state.incomes.push(row);
          rememberIncome(row);
          return row;
        });
        return finish(
          response(
            {
              id: convertedId,
              version: 1,
              reason: body.reason,
              created_at: timestamp,
              sources: sources.map(receipt),
              replacements: replacements.map(receipt),
            },
            201,
          ),
        );
      }
      if (!id) {
        const mixed = state.incomes.some(
          (r) =>
            r.state === "active" &&
            r.member_id === body.member_id &&
            r.kind === body.kind &&
            r.period_month === body.period_month &&
            r.date_precision !== body.date_precision,
        );
        if (mixed && !body.duplicate_acknowledged) return error("INCOME_DUPLICATE_SUSPECTED");
        const row = incomeRow(state.nextId++, body);
        state.incomes.push(row);
        rememberIncome(row);
        const result = response(receipt(row), 201);
        if (state.staleReceipt) {
          state.staleReceipt = false;
          row.version++;
          row.note = "더 최근 합성 메모";
          row.action = "correct";
          rememberIncome(row);
        }
        return finish(result);
      }
      const row = state.incomes.find((r) => r.id === id);
      if (!row) return error("NOT_FOUND", 404);
      if (state.conflict && (!state.conflictPath || state.conflictPath === path)) {
        state.conflict = false;
        row.note = "배우자 합성 메모";
        row.version++;
        rememberIncome(row);
      }
      if (version !== `"${row.version}"`) return error("VERSION_CONFLICT");
      if (action === "returns") {
        const returned = state.incomes
          .filter((r) => r.reverses_id === id && r.state === "active")
          .reduce((n, r) => n + BigInt(r.amount_krw), 0n);
        if (returned + BigInt(body.amount_krw) > BigInt(row.amount_krw))
          return error("RETURN_EXCEEDS_ORIGINAL");
        const next = incomeRow(state.nextId++, {
          ...body,
          kind: "income_return",
          flow: "out",
          member_id: row.member_id,
          reverses_id: id,
          editable: false,
        });
        state.incomes.push(next);
        rememberIncome(next);
        return finish(response(receipt(next), 201));
      }
      if (action === "void") {
        if (!current(row).voidable) return error("INCOME_HAS_RETURNS");
        row.state = "void";
        row.action = "void";
        row.reason = body.reason;
        row.version++;
      } else {
        if (!current(row).editable) return error("INCOME_HAS_RETURNS");
        Object.assign(row, body, { version: row.version + 1, action: "correct" });
      }
      rememberIncome(row);
      return finish(response(receipt(row)));
    }
    if (domain === "cards") {
      if (!id) {
        const row: S["CardResponse"] = {
          ...structuredClone(sampleCard),
          ...body,
          id: uid(state.nextId++),
          masked_number: body.last_four ? `•••• ${body.last_four}` : null,
          status: body.ended_on ? "closed" : "active",
        };
        state.cards.push(row);
        return finish(response(row, 201));
      }
      const row = state.cards.find((r) => r.id === id);
      if (!row) return error("NOT_FOUND", 404);
      if (state.conflict && (!state.conflictPath || state.conflictPath === path)) {
        state.conflict = false;
        row.note = "배우자 합성 카드 메모";
        row.version++;
      }
      if (version !== `"${row.version}"`) return error("VERSION_CONFLICT");
      if (method === "DELETE") {
        if (state.rules.some((r) => r.versions.some((v) => v.card_id === id)))
          return error("CARD_IN_USE");
        state.cards = state.cards.filter((r) => r.id !== id);
        return response(null, 204);
      }
      if (body.ended_on && state.linksRequired) {
        if (!body.closure_ack) return error("PAYMENT_LINK_CONFIRMATION_REQUIRED");
        if (body.usage_digest !== String(state.linksVersion).padStart(64, "0"))
          return error("PAYMENT_LINKS_CHANGED");
      }
      const { closure_ack: _ack, usage_digest: _digest, ...input } = body;
      Object.assign(row, input, { version: row.version + 1 });
      row.status = row.ended_on ? "closed" : "active";
      row.masked_number = row.last_four ? `•••• ${row.last_four}` : null;
      return finish(response(row));
    }
    if (domain === "recurring-rules") {
      if (!id) {
        const row = ruleRow(state.nextId++, { ...body, id: uid(state.nextId++), reason: null });
        row.ended_on = body.effective_until ?? null;
        row.end_reason = body.end_reason ?? null;
        state.rules.push(row);
        return finish(response({ id: row.id, version: row.version }, 201));
      }
      const row = state.rules.find((r) => r.id === id);
      if (!row) return error("NOT_FOUND", 404);
      if (state.conflict && (!state.conflictPath || state.conflictPath === path)) {
        state.conflict = false;
        row.version++;
        row.versions.at(-1)!.note = "배우자 합성 규칙 메모";
      }
      if (version !== `"${row.version}"`) return error("VERSION_CONFLICT");
      if (method === "DELETE") {
        if (state.ruleInUse) return error("RULE_IN_USE");
        state.rules = state.rules.filter((r) => r.id !== id);
        return response(null, 204);
      }
      // Mirrors the server's _split_at/_revoke: a cutoff at or before a not-yet-started
      // version withdraws it.
      const cutoff: string = action === "end" ? body.effective_on : body.effective_from;
      const mockToday = "2025-02-20";
      if (row.ended_on && cutoff >= row.ended_on) return error("RULE_PERIOD_OVERLAP");
      const earlier = row.versions.filter((v) => v.effective_from < cutoff);
      const pending = row.versions.filter((v) => v.effective_from >= cutoff);
      if (!earlier.length || pending.some((v) => v.effective_from <= mockToday))
        return error("RULE_PERIOD_OVERLAP");
      if (pending.length && state.withdrawalBlocked) return error("OBLIGATION_HAS_PAYMENT");
      row.versions = earlier;
      row.versions.at(-1)!.effective_until = cutoff;
      if (action === "end") {
        row.ended_on = cutoff;
        row.end_reason = body.reason;
      } else
        row.versions.push({
          ...(body as S["RuleChange"]),
          id: uid(state.nextId++),
          created_at: timestamp,
          effective_until: row.ended_on,
        });
      row.version++;
      return finish(response({ id: row.id, version: row.version }));
    }
    if (domain === "obligations") {
      if (id === "generate")
        return finish(
          response(
            {
              id: uid(900),
              version: 1,
              items: state.obligations.map((r) => ({ id: r.id, version: r.version })),
            },
            201,
          ),
        );
      const row = state.obligations.find((r) => r.id === id);
      if (!row) return error("NOT_FOUND", 404);
      if (state.conflict && (!state.conflictPath || state.conflictPath === path)) {
        state.conflict = false;
        row.version++;
        row.note = "배우자 합성 회차 메모";
      }
      if (version !== `"${row.version}"`) return error("VERSION_CONFLICT");
      if (action === "settlements") {
        const amount = BigInt(body.amount_krw),
          principal = BigInt(body.principal_krw ?? "0"),
          interest = BigInt(body.interest_krw ?? "0");
        if (row.economic_type === "loan" && principal + interest !== amount)
          return error("INVALID_PAYMENT_SPLIT", 422);
        const cash = incomeRow(state.nextId++, {
          ...body,
          period_month: body.occurred_on.slice(0, 7),
          date_precision: "day",
          kind: "fixed_payment",
          flow: "out",
          member_id: null,
          editable: false,
          voidable: false,
        });
        const payment: S["SettlementResponse"] = {
          id: uid(state.nextId++),
          obligation_id: row.id,
          economic_type: row.economic_type,
          principal_krw: row.economic_type === "loan" ? String(principal) : "0",
          consumption_krw:
            row.economic_type === "expense"
              ? String(amount)
              : row.economic_type === "loan"
                ? String(interest)
                : "0",
          asset_transfer_krw: row.economic_type === "asset_transfer" ? String(amount) : "0",
          cash,
        };
        state.payments.push(payment);
        row.version++;
        refreshObligation(row);
        rememberObligation(row, "settle");
        return finish(response(payment, 201));
      }
      if (!action) row.scheduled_date = body.scheduled_date;
      if (action === "skip") row.skipped = true;
      if (action === "unskip") row.skipped = false;
      if (action === "complete") row.manually_completed = true;
      if (action === "reopen") row.manually_completed = false;
      row.manual_override =
        row.skipped || row.manually_completed || row.scheduled_date !== row.nominal_date;
      row.version++;
      refreshObligation(row);
      rememberObligation(
        row,
        (action as S["ObligationHistoryItem"]["action"] | undefined) ?? "reschedule",
        body.reason,
      );
      return finish(response({ id: row.id, version: row.version }));
    }
    if (domain === "settlements") {
      const payment = state.payments.find((p) => p.id === id);
      if (!payment) return error("NOT_FOUND", 404);
      if (version !== `"${payment.cash.version}"`) return error("VERSION_CONFLICT");
      payment.cash.state = "void";
      payment.cash.version++;
      payment.cash.reason = body.reason;
      const row = state.obligations.find((r) => r.id === payment.obligation_id)!;
      row.manually_completed = false;
      row.manual_override =
        row.skipped || row.manually_completed || row.scheduled_date !== row.nominal_date;
      row.version++;
      refreshObligation(row);
      rememberObligation(row, "void_settlement", body.reason);
      return finish(response(payment));
    }
    return error("NOT_FOUND", 404);
  }
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const result = await handle(
      request.method(),
      url.pathname,
      url.searchParams,
      request.method() === "GET" || !request.postData() ? {} : request.postDataJSON(),
      request.headers(),
    );
    if (!result) return route.fallback();
    if (result.abort) return route.abort("failed");
    if (result.status === 204) return route.fulfill({ status: 204 });
    return route.fulfill({ status: result.status, json: result.body });
  });
  return Object.assign(state, { handle, refreshObligation, rememberIncome, rememberObligation });
}
