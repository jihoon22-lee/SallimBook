import type { Page, Route } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockFinance, uid } from "./finance";
import { ownedPreview } from "../../src/features/assets/months/model";
type Month = components["schemas"]["MonthResponse"];
type Row = components["schemas"]["MonthValueResponse"];
export function total(rows: Row[]): components["schemas"]["MonthTotals"] {
  const included = rows.filter((row) => row.inclusion_status === "included");
  const sum = (kind: string) => {
    const subset = included.filter((row) => row.kind === kind);
    return subset.some((row) => row.owned_amount_krw === null)
      ? null
      : subset.reduce((value, row) => value + BigInt(row.owned_amount_krw!), 0n).toString();
  };
  const assets = sum("asset");
  const liabilities = sum("liability");
  const missing = included.filter((row) => row.verification_state === "missing").length;
  const carried = included.filter((row) => row.verification_state === "carried_unconfirmed").length;
  return {
    assets_krw: assets,
    liabilities_krw: liabilities,
    net_assets_krw:
      assets === null || liabilities === null
        ? null
        : (BigInt(assets) - BigInt(liabilities)).toString(),
    item_count: included.length,
    verified_count: included.length - missing - carried,
    missing_count: missing,
    carried_count: carried,
    provisional: missing + carried > 0,
  };
}
export async function mockMonths(page: Page) {
  const finance = await mockFinance(page);
  finance.assets[2]!.status = "active";
  finance.assets[2]!.ended_on = null;
  finance.assets[2]!.archived_at = null;
  finance.assets[1]!.inclusion_status = "excluded";
  const rows: Row[] = finance.assets.map((asset, index) => ({
    id: uid(100 + index),
    asset_id: asset.id,
    name: asset.name,
    kind: asset.kind,
    category: asset.category,
    ownership_kind: asset.ownership_kind,
    owner_member_id: asset.owner_member_id ?? null,
    household_share: asset.household_share ?? "1",
    amount_basis: asset.amount_basis,
    inclusion_status: asset.inclusion_status ?? "included",
    started_on: asset.started_on,
    ended_on: asset.ended_on ?? null,
    source_asset_version: asset.version,
    input_amount_krw: index === 0 ? "1001" : null,
    owned_amount_krw: index === 0 ? "501" : null,
    as_of_date: null,
    verification_state: index === 0 ? "carried_unconfirmed" : "missing",
    origin: index === 0 ? "carried" : "manual",
    origin_revision_id: index === 0 ? uid(90) : null,
    change_reason: null,
    version: 1,
  }));
  const initial: Month = {
    month: "2025-02",
    revision_id: uid(91),
    revision_no: 1,
    version: 1,
    state: "draft",
    previous_revision_id: null,
    reopened_reason: null,
    confirmed_at: null,
    confirmed_by_member_id: null,
    created_at: "2025-02-01T00:00:00Z",
    scope_stale: false,
    values: rows,
    totals: total(rows),
    next_cursor: null,
  };
  const previous: Month = {
    ...structuredClone(initial),
    month: "2025-01",
    revision_id: uid(90),
    state: "confirmed",
    confirmed_at: "2025-01-31T12:00:00Z",
    confirmed_by_member_id: uid(2),
    values: rows.map((row, index) => ({
      ...row,
      id: uid(200 + index),
      input_amount_krw: row.kind === "liability" ? "300" : row.input_amount_krw,
      owned_amount_krw: row.kind === "liability" ? "150" : row.owned_amount_krw,
      verification_state: row.inclusion_status === "included" ? "verified" : "missing",
      as_of_date: row.inclusion_status === "included" ? "2025-01-31" : null,
    })),
  };
  previous.totals = total(previous.values);
  const state = {
    finance,
    record: structuredClone(initial) as Month | null,
    previous: previous as Month | null,
    revisions: [] as Month[],
    writes: [] as {
      operation: string;
      body: Record<string, unknown>;
      version?: string;
      key?: string;
    }[],
    reads: [] as string[],
    writeFailure: "" as "" | "before" | "after",
    writeDelay: 0,
    pageSize: 200,
    mutateBetweenPages: false,
    scopeAckRequired: false,
    nextRevision: 300,
  };
  const completed = new Map<
    string,
    { fingerprint: string; reference: components["schemas"]["MonthReference"] }
  >();
  const fail = (route: Route, status: number, code: string) =>
    route.fulfill({
      status,
      json: { error: { code, message: "UNTRUSTED_MONTH_ERROR", request_id: "synthetic" } },
    });
  const reference = (record: Month) => ({
    month: record.month,
    revision_id: record.revision_id,
    revision_no: record.revision_no,
    version: record.version,
  });
  await page.route("**/api/v1/asset-months/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const parts = url.pathname.split("/");
    const month = parts[4]!;
    const operation = parts[5] ?? "get";
    if (method === "GET") {
      state.reads.push(`${month}:${operation}:${parts[6] ?? ""}`);
      const current =
        month === "2025-01" ? state.previous : month === "2025-02" ? state.record : null;
      if (!current) return fail(route, 404, "MONTH_NOT_FOUND");
      if (operation === "revisions" && !parts[6]) {
        const all = month === "2025-01" ? [current] : [...state.revisions, current];
        return route.fulfill({
          json: {
            items: [...all].reverse().map((item) => ({
              ...reference(item),
              state: item.state,
              previous_revision_id: item.previous_revision_id,
              reopened_reason: item.reopened_reason,
              confirmed_at: item.confirmed_at,
              created_at: item.created_at,
            })),
            next_cursor: null,
          },
        });
      }
      const selected =
        operation === "revisions"
          ? [...state.revisions, current].find((item) => item.revision_no === Number(parts[6]))
          : current;
      if (!selected) return fail(route, 404, "NOT_FOUND");
      const sorted = [...selected.values].sort((a, b) => a.asset_id.localeCompare(b.asset_id));
      const after = url.searchParams.get("cursor");
      const index = after ? sorted.findIndex((row) => row.asset_id === after) + 1 : 0;
      if (after && state.mutateBetweenPages) {
        state.mutateBetweenPages = false;
        selected.version++;
      }
      const subset = sorted.slice(index, index + state.pageSize);
      const next = index + state.pageSize < sorted.length ? subset.at(-1)!.asset_id : null;
      return route.fulfill({
        json: { ...selected, values: subset, totals: total(selected.values), next_cursor: next },
      });
    }
    const body = request.postDataJSON();
    const version = request.headers()["if-match"];
    const key = request.headers()["idempotency-key"];
    state.writes.push({ operation, body, version, key });
    if (request.headers()["x-csrf-token"] !== `synthetic-finance-csrf-${finance.csrfCalls}`)
      return fail(route, 403, "CSRF_FAILED");
    if (state.writeFailure === "before") {
      state.writeFailure = "";
      return route.abort("failed");
    }
    const fingerprint = JSON.stringify([month, body, version]);
    const idempotent = ["draft", "confirm", "reopen"].includes(operation);
    if (idempotent && !key) return fail(route, 400, "INVALID_IDEMPOTENCY_KEY");
    const existing = completed.get(`${operation}:${key}`);
    if (existing)
      return existing.fingerprint === fingerprint
        ? route.fulfill({ status: operation === "confirm" ? 200 : 201, json: existing.reference })
        : fail(route, 409, "IDEMPOTENCY_CONFLICT");
    if (operation === "draft") {
      if (state.record) return fail(route, 409, "MONTH_ALREADY_EXISTS");
      const next = structuredClone(initial);
      next.values = next.values.map((row) => {
        const source = body.copy_previous
          ? state.previous?.values.find(
              (item) => item.asset_id === row.asset_id && item.amount_basis === row.amount_basis,
            )
          : null;
        return {
          ...row,
          input_amount_krw: source?.input_amount_krw ?? null,
          owned_amount_krw: source?.owned_amount_krw ?? null,
          verification_state:
            source?.input_amount_krw !== null && source?.input_amount_krw !== undefined
              ? "carried_unconfirmed"
              : "missing",
          as_of_date: null,
          origin:
            source?.input_amount_krw !== null && source?.input_amount_krw !== undefined
              ? "carried"
              : "manual",
        };
      });
      next.totals = total(next.values);
      state.record = next;
    } else {
      const current = state.record;
      if (!current) return fail(route, 404, "MONTH_NOT_FOUND");
      if (body.revision_id !== current.revision_id) return fail(route, 409, "REVISION_CONFLICT");
      if (operation === "values") {
        if (current.state === "confirmed") return fail(route, 409, "MONTH_CONFIRMED");
        const row = current.values.find((item) => item.asset_id === parts[6]);
        if (!row) return fail(route, 404, "NOT_FOUND");
        if (body.value_id !== row.id) return fail(route, 409, "VALUE_CONFLICT");
        if (version !== `"${row.version}"`) return fail(route, 409, "VERSION_CONFLICT");
        if (
          body.unchanged &&
          (row.verification_state !== "carried_unconfirmed" || row.input_amount_krw === null)
        )
          return fail(route, 422, "NO_CARRIED_VALUE");
        if (!body.unchanged) {
          row.input_amount_krw = body.input_amount_krw;
          row.origin = "manual";
          row.origin_revision_id = null;
        }
        row.owned_amount_krw =
          row.input_amount_krw === null
            ? null
            : ownedPreview(row.input_amount_krw, row.household_share, row.amount_basis);
        row.as_of_date = body.as_of_date ?? null;
        row.change_reason = body.change_reason ?? null;
        row.verification_state = row.input_amount_krw === null ? "missing" : "verified";
        row.version++;
        current.version++;
        current.totals = total(current.values);
        return route.fulfill({
          json: { value: row, revision_version: current.version, totals: current.totals },
        });
      }
      if (version !== `"${current.version}"`) return fail(route, 409, "VERSION_CONFLICT");
      if (operation === "confirm") {
        if (current.state === "confirmed") return fail(route, 409, "MONTH_CONFIRMED");
        if (current.state === "draft" && current.scope_stale)
          return fail(route, 409, "MONTH_SCOPE_CHANGED");
        if (total(current.values).provisional) return fail(route, 409, "MONTH_UNVERIFIED");
        if (
          current.values.some(
            (row) => row.inclusion_status === "included" && row.as_of_date !== "2025-02-28",
          ) &&
          !body.acknowledge_non_month_end_dates
        )
          return fail(route, 409, "AS_OF_DATE_ACK_REQUIRED");
        if (state.scopeAckRequired && !body.acknowledge_scope_change)
          return fail(route, 409, "SCOPE_ACK_REQUIRED");
        current.state = "confirmed";
        current.confirmed_at = "2025-02-28T12:00:00Z";
        current.confirmed_by_member_id = uid(2);
        current.version++;
      } else if (operation === "reopen") {
        if (current.state !== "confirmed") return fail(route, 409, "MONTH_NOT_CONFIRMED");
        state.revisions.push(structuredClone(current));
        state.record = {
          ...structuredClone(current),
          revision_id: uid(state.nextRevision++),
          revision_no: current.revision_no + 1,
          version: 1,
          state: "reopened",
          previous_revision_id: current.revision_id,
          reopened_reason: body.reason,
          confirmed_at: null,
          confirmed_by_member_id: null,
          values: current.values.map((row) => ({
            ...row,
            id: uid(state.nextRevision++),
            version: 1,
          })),
        };
      } else if (operation === "sync-scope") {
        if (current.state === "confirmed") return fail(route, 409, "MONTH_CONFIRMED");
        for (const row of current.values) {
          const asset = finance.assets.find((item) => item.id === row.asset_id);
          if (!asset) continue;
          const basisChanged = row.amount_basis !== asset.amount_basis;
          const changed =
            basisChanged ||
            row.household_share !== asset.household_share ||
            row.name !== asset.name ||
            row.inclusion_status !== asset.inclusion_status;
          Object.assign(row, {
            name: asset.name,
            household_share: asset.household_share,
            amount_basis: asset.amount_basis,
            inclusion_status: asset.inclusion_status,
            source_asset_version: asset.version,
          });
          if (changed) {
            if (basisChanged) row.input_amount_krw = null;
            row.owned_amount_krw =
              row.input_amount_krw === null
                ? null
                : ownedPreview(row.input_amount_krw, row.household_share, row.amount_basis);
            row.as_of_date = null;
            row.verification_state =
              row.input_amount_krw === null ? "missing" : "carried_unconfirmed";
            row.version++;
          }
        }
        current.scope_stale = false;
        current.version++;
        current.totals = total(current.values);
      } else return fail(route, 404, "NOT_FOUND");
    }
    const result = reference(state.record!);
    if (idempotent) completed.set(`${operation}:${key}`, { fingerprint, reference: result });
    if (state.writeDelay) await new Promise((resolve) => setTimeout(resolve, state.writeDelay));
    if (state.writeFailure === "after") {
      state.writeFailure = "";
      return route.abort("failed");
    }
    return route.fulfill({
      status: ["draft", "reopen"].includes(operation) ? 201 : 200,
      json: result,
    });
  });
  return state;
}
export function verifyAll(record: Month, date = "2025-02-28") {
  for (const row of record.values) {
    if (row.inclusion_status !== "included") continue;
    row.input_amount_krw ??= "0";
    row.owned_amount_krw ??= "0";
    row.verification_state = "verified";
    row.as_of_date = date;
  }
  record.totals = total(record.values);
}
