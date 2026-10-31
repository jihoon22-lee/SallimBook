import type {
  NativeAuthResult,
  NativeStoredCardEntry,
} from "../../../../plugins/sallimbook-auth/src/definitions";
import { ApiError, type ApiErrorCode } from "./api";
import { hasNativeAuth, nativeAuthPlugin } from "./nativeAuth";

export type { NativeStoredCardEntry };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** IDs in, safe completion status out. All card inputs and reveal responses stay native. */
export const nativeStoredCards = {
  async open(options: NativeStoredCardEntry): Promise<{ status: "completed" | "cancelled" }> {
    if (
      !options ||
      typeof options !== "object" ||
      Object.keys(options).length !== 2 ||
      Object.keys(options).some((key) => key !== "action" && key !== "cardId") ||
      !["view", "edit", "delete"].includes(options.action) ||
      typeof options.cardId !== "string" ||
      !uuid.test(options.cardId)
    )
      throw new ApiError(422, "VALIDATION_ERROR");
    if (!hasNativeAuth()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
    let result: NativeAuthResult<{ status: "completed" | "cancelled" }>;
    try {
      result = await nativeAuthPlugin.openCardDetailsUI(options);
    } catch {
      throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
    }
    if (!result.ok) {
      const errors: Record<string, [number, ApiErrorCode]> = {
        APP_LOCKED: [0, "APP_LOCKED"],
        SESSION_EXPIRED: [401, "UNAUTHENTICATED"],
        ACCESS_DENIED: [403, "FORBIDDEN"],
        INVALID_REQUEST: [422, "VALIDATION_ERROR"],
        VERSION_CONFLICT: [409, "VERSION_CONFLICT"],
        AUTH_CANCELLED: [0, "REQUEST_CANCELLED"],
        NETWORK_UNAVAILABLE: [0, "NETWORK_UNAVAILABLE"],
      };
      const [status, code] = errors[result.code] ?? [0, "NATIVE_AUTH_UNAVAILABLE"];
      throw new ApiError(status, code);
    }
    const value = result.value;
    if (
      !value ||
      Object.keys(value).length !== 1 ||
      !["completed", "cancelled"].includes(value.status)
    )
      throw new ApiError(403, "FORBIDDEN");
    return value;
  },
};
