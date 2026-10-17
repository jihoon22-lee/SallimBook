import { createHash } from "node:crypto";
import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { mockHomecare } from "./homecare";
import { uid } from "./finance";
type S = components["schemas"];
export const bytes = Buffer.from("SYNTHETIC DOCUMENT FIXTURE ONLY");
export const digest = createHash("sha256").update(bytes).digest("hex");
const time = "2026-10-18T00:00:00Z";
const entity = (id: number) => ({ id: uid(id), household_id: uid(3), version: 1, created_at: time, updated_at: time, created_by_member_id: uid(2), updated_by_member_id: uid(2) });
export const documentRow = (id = 8000, patch: Partial<S["DocumentResponse"]> = {}): S["DocumentResponse"] => ({ ...entity(id), original_name: "합성 영수증.png", mime_type: "image/png", size_bytes: bytes.length, checksum_sha256: digest, state: "ready", pending_expires_at: "2099-01-01T00:00:00Z", stored_at: time, orphaned_at: null, deleted_at: null, active_link_count: 1, ...patch });
export const documentLink = (id = 8100, patch: Partial<S["DocumentLinkResponse"]> = {}): S["DocumentLinkResponse"] => ({ ...entity(id), document_id: uid(8000), target: { kind: "appliance", id: uid(100) }, active: true, ended_at: null, end_reason: null, ...patch });
export function documentsFixture() {
 const state = { documents: [documentRow()], links: [documentLink()], nextId: 9000, pageSize: 50, failure: "" as "" | "create-before" | "create-after" | "upload-before" | "upload-after" | "mutation-after", error: "", status: 422, conflict: false, delay: 0, writes: [] as { path: string; method: string; body: any; key?: string; version?: string; headers: Record<string, string>; bytes?: Buffer }[], reads: [] as { path: string; query: URLSearchParams }[] };
 type Result = { status: number; body: any; abort?: boolean; binary?: Buffer };
 const result = (body: any, status = 200): Result => ({ status, body: structuredClone(body) }); const error = (code: string, status = 409) => result({ error: { code, message: "UNTRUSTED_DOCUMENT_ERROR", request_id: "synthetic" } }, status);
 const receipts = new Map<string, { fingerprint: string; response: Result }>();
 function page<T extends { id: string }>(rows: T[], query: URLSearchParams) { const after = query.get("cursor"); const offset = after ? rows.findIndex((r) => r.id === after) + 1 : 0; const count = Math.min(state.pageSize, Number(query.get("limit") ?? 50)); const items = rows.slice(offset, offset + count); return { items, next_cursor: offset + items.length < rows.length ? items.at(-1)!.id : null }; }
 async function handle(method: string, path: string, query = new URLSearchParams(), body: any = {}, headers: Record<string, string> = {}, buffer?: Buffer): Promise<Result | undefined> {
   if (!/^\/api\/v1\/(documents|document-links)(\/|$)/.test(path)) return;
   const [, , , domain, id, action] = path.split("/"); const row = state.documents.find((r) => r.id === id); const link = state.links.find((r) => r.id === id);
   if (method === "GET") {
     state.reads.push({ path, query });
     if (!id) return result(page(state.documents.filter((r) => r.state !== "deleted" && (!query.has("target_kind") || state.links.some((l) => l.document_id === r.id && l.active && l.target.kind === query.get("target_kind") && l.target.id === query.get("target_id")))), query));
     if (!row) return error("NOT_FOUND", 404);
     if (action === "links") return result(page(state.links.filter((l) => l.document_id === id), query));
     if (action === "download") return row.state !== "ready" ? error("DOCUMENT_NOT_READY") : !row.active_link_count ? error("DOCUMENT_UNLINKED") : { status: 200, body: null, binary: bytes };
     return result(row);
   }
   const key = headers["idempotency-key"], version = headers["if-match"]; state.writes.push({ path, method, body: structuredClone(body), key, version, headers, bytes: buffer }); const fingerprint = JSON.stringify([path, method, body, version, buffer?.toString("hex")]); const receipt = `${path}:${key}`;
   if (receipts.has(receipt)) { const old = receipts.get(receipt)!; return old.fingerprint === fingerprint ? structuredClone(old.response) : error("IDEMPOTENCY_CONFLICT"); }
   const create = domain === "documents" && !id; const upload = action === "content";
   if (state.failure === (create ? "create-before" : upload ? "upload-before" : "none")) { state.failure = ""; return { status: 0, body: null, abort: true }; }
   if (state.error) return error(state.error, state.status);
   const finish = async (response: Result) => { receipts.set(receipt, { fingerprint, response }); if (state.delay) await new Promise((r) => setTimeout(r, state.delay)); if (state.failure === (create ? "create-after" : upload ? "upload-after" : "mutation-after")) { state.failure = ""; return { status: 0, body: null, abort: true }; } return response; };
   if (create) { const created = documentRow(state.nextId++, { ...body, state: "pending", stored_at: null }); delete (created as any).target; delete (created as any).contains_no_card_data; state.documents.push(created); state.links.push(documentLink(state.nextId++, { document_id: created.id, target: body.target })); return finish(result({ id: created.id, version: created.version }, 201)); }
   const source = domain === "document-links" && !id ? state.documents.find((r) => r.id === body.document_id) : domain === "document-links" ? state.documents.find((r) => r.id === link?.document_id) : row;
   if (!source) return error("NOT_FOUND", 404); const versioned = domain === "document-links" && id ? link : source;
   if (!versioned) return error("NOT_FOUND", 404); if (state.conflict) { state.conflict = false; versioned.version++; }
   if (version !== `"${versioned.version}"`) return error("VERSION_CONFLICT");
   if (upload) { if (!buffer || buffer.length !== source.size_bytes || createHash("sha256").update(buffer).digest("hex") !== source.checksum_sha256) return error("DOCUMENT_CONTENT_MISMATCH", 422); source.state = "ready"; source.stored_at = time; source.version++; return finish(result({ id: source.id, version: source.version })); }
   if (domain === "document-links" && !id) { if (state.links.some((l) => l.document_id === source.id && l.active && l.target.id === body.target.id && l.target.kind === body.target.kind)) return error("DOCUMENT_ALREADY_LINKED"); const created = documentLink(state.nextId++, { document_id: source.id, target: body.target }); state.links.push(created); source.active_link_count++; source.orphaned_at = null; source.version++; return finish(result({ id: created.id, version: 1 }, 201)); }
   if (action === "end" && link) { if (!link.active) return error("DOCUMENT_LINK_ENDED"); link.active = false; link.end_reason = body.reason; link.ended_at = time; link.version++; source.active_link_count--; source.version++; if (!source.active_link_count) source.orphaned_at = time; return finish(result({ id: link.id, version: link.version })); }
   if (action === "delete") { source.state = "deleted"; source.deleted_at = time; source.version++; source.active_link_count = 0; for (const l of state.links.filter((l) => l.document_id === source.id && l.active)) { l.active = false; l.end_reason = body.reason; l.ended_at = time; l.version++; } return finish(result({ id: source.id, version: source.version })); }
   return error("NOT_FOUND", 404);
 }
 return Object.assign(state, { handle });
}
export async function mockDocuments(page: Page) {
 const homecare = await mockHomecare(page); const state = documentsFixture();
 await page.route(/\/api\/v1\/(documents|document-links)(\/|\?|$)/, async (route) => { const request = route.request(); const url = new URL(request.url()); const binary = request.method() === "PUT"; const response = await state.handle(request.method(), url.pathname, url.searchParams, binary ? {} : request.postDataJSON() ?? {}, request.headers(), binary ? request.postDataBuffer() ?? undefined : undefined); if (!response) return route.fallback(); if (response.abort) return route.abort("failed"); if (response.binary) return route.fulfill({ status: response.status, body: response.binary, headers: { "Content-Type": "image/png", "Cache-Control": "no-store", "Content-Disposition": "attachment; filename=synthetic.png" } }); return route.fulfill({ status: response.status, json: response.body, headers: { "Cache-Control": "no-store" } }); });
 return Object.assign(state, { homecare });
}
