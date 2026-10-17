import type { Page, Route } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
export const uid = (value: number) => `00000000-0000-4000-8000-${String(value).padStart(12, "0")}`;
export const members: components["schemas"]["MemberResponse"][] = [
  { user_id: uid(1), member_id: uid(2), household_id: uid(3), display_name: "합성 구성원 하나", role: "owner" },
  { user_id: uid(4), member_id: uid(5), household_id: uid(3), display_name: "합성 구성원 둘", role: "member" },
];
export const jointAsset: components["schemas"]["AssetResponse"] = {
  id: uid(10), household_id: uid(3), name: "합성 공동 주택", kind: "asset", category: "real_estate", ownership_kind: "joint", owner_member_id: null,
  household_share: "0.5", amount_basis: "whole", inclusion_status: "included", started_on: "2025-01-01", ended_on: null, note: null,
  status: "active", archived_at: null, created_by_member_id: uid(2), updated_by_member_id: uid(2), created_at: "2026-10-17T00:00:00Z", updated_at: "2026-10-17T00:00:00Z", version: 1,
};

export async function mockFinance(page: Page) {
  const state = {
    assets: [structuredClone(jointAsset), { ...jointAsset, id: uid(11), name: "합성 개인 금융 자산", category: "financial", ownership_kind: "individual", owner_member_id: uid(5), household_share: "1", amount_basis: "owned" }, { ...jointAsset, id: uid(12), name: "합성 종료 대출", kind: "liability", category: "loan", status: "archived", ended_on: "2026-01-01", archived_at: "2026-01-02T00:00:00Z" }] as components["schemas"]["AssetResponse"][],
    queries: [] as URLSearchParams[], creates: [] as components["schemas"]["AssetCreate"][], patches: [] as { version: string; body: components["schemas"]["AssetPatch"] }[], archives: [] as string[],
    conflictOnce: false, archiveConflictOnce: false, listFailure: false, membersFailure: false, mutationCsrfOnce: false, csrfCalls: 0, signedIn: true,
    pageSize: 50, rejectMutation: false,
  };
  const error = (route: Route, status: number, code: string) => route.fulfill({ status, json: { error: { code, message: "UNTRUSTED_FINANCE_ERROR", request_id: "synthetic" } } });
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url()); const path = url.pathname; const method = route.request().method();
    if (path === "/api/v1/me") return state.signedIn ? route.fulfill({ json: members[0] }) : error(route, 401, "UNAUTHENTICATED");
    if (path === "/api/v1/auth/web/csrf") { state.csrfCalls++; return route.fulfill({ json: { csrf_token: `synthetic-finance-csrf-${state.csrfCalls}` } }); }
    if (path === "/api/v1/household/members") return state.membersFailure ? error(route, 503, "UNAVAILABLE") : route.fulfill({ json: members });
    if (method !== "GET") {
      if (state.mutationCsrfOnce) { state.mutationCsrfOnce = false; return error(route, 403, "CSRF_FAILED"); }
      if (route.request().headers()["x-csrf-token"] !== `synthetic-finance-csrf-${state.csrfCalls}`) return error(route, 403, "CSRF_FAILED");
      if (state.rejectMutation) return error(route, 503, "UNAVAILABLE");
    }
    if (path === "/api/v1/assets" && method === "GET") {
      state.queries.push(url.searchParams);
      if (state.listFailure) return error(route, 503, "UNAVAILABLE");
      if (url.searchParams.get("owner_member_id") === uid(999)) return error(route, 404, "NOT_FOUND");
      const selected = state.assets.filter((asset) => ["kind", "category", "ownership_kind", "owner_member_id", "inclusion_status"].every((key) => !url.searchParams.has(key) || asset[key as keyof typeof asset] === url.searchParams.get(key)))
        .filter((asset) => (url.searchParams.get("status") ?? "active") === "all" || asset.status === (url.searchParams.get("status") ?? "active"));
      const offset = url.searchParams.has("cursor") ? 1 : 0;
      return route.fulfill({ json: { items: selected.slice(offset, offset + state.pageSize), next_cursor: selected.length > offset + state.pageSize ? selected[offset]!.id : null } });
    }
    if (path === "/api/v1/assets" && method === "POST") {
      const input = route.request().postDataJSON() as components["schemas"]["AssetCreate"];
      state.creates.push(input);
      const value = { ...jointAsset, ...input, id: uid(20 + state.creates.length), status: input.ended_on ? "archived" as const : "active" as const };
      state.assets.push(value);
      return route.fulfill({ status: 201, json: value });
    }
    if (path.startsWith("/api/v1/assets/")) {
      const id = path.split("/")[4]; const asset = state.assets.find((value) => value.id === id);
      if (!asset) return error(route, 404, "NOT_FOUND");
      if (method === "GET") return route.fulfill({ json: asset });
      if (method === "PATCH") {
        const body = route.request().postDataJSON() as components["schemas"]["AssetPatch"];
        const version = route.request().headers()["if-match"] ?? ""; state.patches.push({ version, body });
        if (state.conflictOnce) { state.conflictOnce = false; asset.version++; asset.name = "합성 서버 변경 이름"; asset.note = "합성 다른 편집자의 메모"; }
        if (version !== `"${asset.version}"`) return error(route, 409, "VERSION_CONFLICT");
        Object.assign(asset, body, { version: asset.version + 1 });
        asset.status = asset.ended_on ? "archived" : "active";
        return route.fulfill({ json: asset });
      }
      if (method === "POST" && path.endsWith("/archive")) {
        const version = route.request().headers()["if-match"] ?? ""; state.archives.push(version);
        if (state.archiveConflictOnce) { state.archiveConflictOnce = false; asset.version++; }
        if (version !== `"${asset.version}"`) return error(route, 409, "VERSION_CONFLICT");
        asset.ended_on = route.request().postDataJSON().ended_on;
        asset.status = "archived"; asset.version++;
        return route.fulfill({ json: asset });
      }
    }
    return error(route, 404, "NOT_FOUND");
  });
  return state;
}
