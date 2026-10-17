import type { components, operations } from "@sallimbook/api-client";
import type { NativeAuthResult, NativeFinanceResponse } from "../../../../plugins/sallimbook-auth/src/definitions";
import { ApiError, apiErrorCode } from "./api";
import { hasNativeAuth, nativeAuthPlugin as plugin } from "./nativeAuth";

export type NativeAuditQuery = NonNullable<operations["listAuditEvents"]["parameters"]["query"]>;
export type NativeAuditPage = components["schemas"]["AuditListResponse"];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const stamp = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;
function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) && Object.getPrototypeOf(value) === Object.prototype;
}
function request(options: { query?: NativeAuditQuery }): { query?: NativeAuditQuery } {
  const invalid = () => { throw new ApiError(422, "VALIDATION_ERROR"); };
  if (!object(options) || Object.keys(options).some((key) => key !== "query")) return invalid();
  if (!Object.hasOwn(options, "query")) return {};
  const query = options.query;
  if (!object(query) || Object.keys(query).some((key) => !["limit", "cursor", "entity_type", "entity_id", "actor_member_id", "action", "since", "until"].includes(key))) return invalid();
  if (Object.hasOwn(query, "limit") && (!Number.isInteger(query.limit) || query.limit! < 1 || query.limit! > 200)) return invalid();
  for (const key of ["cursor", "entity_type", "entity_id", "actor_member_id", "action", "since", "until"] as const) {
    const value = query[key];
    if (value === undefined || value === null) continue;
    if (typeof value !== "string") return invalid();
    if (key === "cursor" ? value.length > 1024 || !/^[A-Za-z0-9_-]+$/.test(value)
      : key === "entity_id" || key === "actor_member_id" ? !uuid.test(value)
      : key === "since" || key === "until" ? !stamp.test(value) || Number.isNaN(Date.parse(value))
      : !/^[a-z][a-z0-9_]{0,39}$/.test(value)) return invalid();
  }
  return { query: { ...query } };
}

/** Current-household metadata only. The native module owns bearer tokens and the fixed URL. */
export const nativeAudit = {
  async list(options: { query?: NativeAuditQuery } = {}): Promise<NativeAuditPage> {
    const safe = request(options);
    if (!hasNativeAuth()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
    let result: NativeAuthResult<NativeFinanceResponse<NativeAuditPage>>;
    try { result = await plugin.listAuditEvents(safe); }
    catch { throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE"); }
    if (!result.ok) {
      switch (result.code) {
        case "APP_LOCKED": throw new ApiError(0, "APP_LOCKED");
        case "SESSION_EXPIRED": throw new ApiError(401, "UNAUTHENTICATED");
        case "KEY_INVALIDATED": throw new ApiError(401, "NATIVE_KEY_INVALIDATED");
        case "ACCESS_DENIED": throw new ApiError(403, "FORBIDDEN");
        case "AUTH_CANCELLED": throw new ApiError(0, "REQUEST_CANCELLED");
        case "INVALID_REQUEST": throw new ApiError(422, "VALIDATION_ERROR");
        case "NETWORK_UNAVAILABLE": throw new ApiError(0, "NETWORK_UNAVAILABLE");
        default: throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
      }
    }
    const response = result.value;
    if (response.status !== 200) {
      const error = response.body as components["schemas"]["ErrorResponse"] | null;
      throw new ApiError(response.status, apiErrorCode(error?.error?.code, response.status));
    }
    const page: unknown = response.body;
    if (!page || !object(page) || Object.keys(page).length !== 2 || !Array.isArray(page.items) ||
      page.items.length > (safe.query?.limit ?? 50) || !(page.next_cursor === null || typeof page.next_cursor === "string" && /^[A-Za-z0-9_-]{1,1024}$/.test(page.next_cursor))) {
      throw new ApiError(403, "FORBIDDEN");
    }
    return page as NativeAuditPage;
  },
};
