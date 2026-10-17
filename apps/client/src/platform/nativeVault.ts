import type { components, operations } from "@sallimbook/api-client";
import type { NativeAuthResult, NativeFinanceResponse, NativeVaultEntry } from "../../../../plugins/sallimbook-auth/src/definitions";
import { ApiError, type ApiErrorCode } from "./api";
import { hasNativeAuth, nativeAuthPlugin as plugin } from "./nativeAuth";

export type { NativeVaultEntry };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const fields: Record<string, string | null> = {
  manage: null, setup: null, "register-device": null, "change-password": null, recover: null, rotate: null,
  view: "cardId", edit: "cardId", purge: "cardId", "cvc-view": "cardId", "cvc-edit": "cardId", "cvc-delete": "cardId",
  share: "memberId", "revoke-member": "memberId", "accept-share": "offerId", "cancel-share": "offerId",
  "resume-rotation": "rotationId", "abort-rotation": "rotationId",
};
function entry(value: NativeVaultEntry): void {
  if (!value || typeof value !== "object" || !Object.hasOwn(fields, value.action)) throw new ApiError(422, "VALIDATION_ERROR");
  const field = fields[value.action];
  const keys = Object.keys(value);
  if (keys.length !== (field ? 2 : 1) || keys.some((key) => key !== "action" && key !== field)) throw new ApiError(422, "VALIDATION_ERROR");
  if (field && !uuid.test((value as unknown as Record<string, string>)[field] ?? "")) throw new ApiError(422, "VALIDATION_ERROR");
}
async function invoke<T>(operation: () => Promise<NativeAuthResult<T>>): Promise<T> {
  if (!hasNativeAuth()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
  let result: NativeAuthResult<T>;
  try { result = await operation(); } catch { throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE"); }
  if (result.ok) return result.value;
  const errors: Record<string, [number, ApiErrorCode]> = {
    APP_LOCKED: [0, "APP_LOCKED"], SESSION_EXPIRED: [401, "UNAUTHENTICATED"], ACCESS_DENIED: [403, "FORBIDDEN"],
    AUTH_CANCELLED: [0, "REQUEST_CANCELLED"], INVALID_REQUEST: [422, "VALIDATION_ERROR"], KEY_INVALIDATED: [401, "NATIVE_KEY_INVALIDATED"],
    NETWORK_UNAVAILABLE: [0, "NETWORK_UNAVAILABLE"], REAUTHENTICATION_REQUIRED: [403, "REAUTHENTICATION_REQUIRED"],
  };
  const [status, code] = errors[result.code] ?? ([0, "NATIVE_AUTH_UNAVAILABLE"] as const);
  throw new ApiError(status, code);
}
async function metadata<T>(operation: () => Promise<NativeAuthResult<NativeFinanceResponse<T>>>): Promise<T> {
  const result = await invoke(operation);
  if (result.status !== 200 || result.body == null) throw new ApiError(result.status, "FORBIDDEN");
  return result.body as T;
}
/** This adapter exposes safe status and native screens only. No web HTTP or storage fallback. */
export const nativeVault = {
  async open(options: NativeVaultEntry): Promise<{ status: "completed" | "cancelled" }> {
    entry(options);
    const result = await invoke(() => plugin.openVaultUI(options));
    if (!result || Object.keys(result).length !== 1 || !["completed", "cancelled"].includes(result.status)) throw new ApiError(403, "FORBIDDEN");
    return result;
  },
  getVaultStatus: (): Promise<components["schemas"]["VaultStatusResponse"]> => metadata(() => plugin.getVaultStatus()),
  listVaultShares: (options: { query?: NonNullable<operations["listVaultShares"]["parameters"]["query"]> } = {}): Promise<components["schemas"]["VaultShareListResponse"]> => {
    if (!options || typeof options !== "object" || Object.keys(options).some((key) => key !== "query")) throw new ApiError(422, "VALIDATION_ERROR");
    if (Object.hasOwn(options, "query")) {
      const query = options.query;
      if (!query || typeof query !== "object" || Object.keys(query).some((key) => key !== "cursor" && key !== "limit") ||
        query.cursor != null && (typeof query.cursor !== "string" || !uuid.test(query.cursor)) ||
        Object.hasOwn(query, "limit") && (!Number.isInteger(query.limit) || query.limit! < 1 || query.limit! > 200)) throw new ApiError(422, "VALIDATION_ERROR");
    }
    return metadata(() => plugin.listVaultShares(options));
  },
  getVaultRotation: (options: { rotationId: string }): Promise<components["schemas"]["VaultRotationResponse"]> => {
    if (!options || Object.keys(options).length !== 1 || typeof options.rotationId !== "string" || !uuid.test(options.rotationId)) throw new ApiError(422, "VALIDATION_ERROR");
    return metadata(() => plugin.getVaultRotation(options));
  },
};
