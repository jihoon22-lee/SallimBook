import type { components } from "@sallimbook/api-client";
import { readableSelection } from "./exportScope";
import type { NativeAuthResult } from "../../../../plugins/sallimbook-auth/src/definitions";
import { ApiError, type ApiErrorCode } from "./api";
import { hasNativeAuth, nativeAuthPlugin as plugin } from "./nativeAuth";

type ExportRequest = components["schemas"]["ExportRequest"];
type ExportStatus = { status: "exported" | "cancelled" };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
function object(value: unknown): value is Record<string, unknown> {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value))
  );
}
function selection(options: { input: ExportRequest }): { input: ExportRequest } {
  if (
    !object(options) ||
    Object.keys(options).length !== 1 ||
    !object(options.input) ||
    Object.keys(options.input).some(
      (key) => key !== "formats" && key !== "document_ids" && key !== "readable",
    )
  )
    throw new ApiError(422, "VALIDATION_ERROR");
  const formats = options.input.formats === undefined ? ["json", "csv"] : options.input.formats;
  const documents = options.input.document_ids === undefined ? [] : options.input.document_ids;
  const readable =
    options.input.readable == null ? undefined : readableSelection(options.input.readable);
  if (
    !Array.isArray(formats) ||
    (formats.length < 1 && !readable) ||
    formats.length > 2 ||
    formats.some((format) => format !== "json" && format !== "csv") ||
    new Set(formats).size !== formats.length ||
    !Array.isArray(documents) ||
    documents.length > 10 ||
    documents.some((id) => typeof id !== "string" || !uuid.test(id)) ||
    new Set(documents).size !== documents.length
  )
    throw new ApiError(422, "VALIDATION_ERROR");
  return {
    input: {
      formats: [...formats] as ("json" | "csv")[],
      document_ids: [...documents],
      ...(readable ? { readable } : {}),
    },
  };
}

/** Opens a native confirmation/reauthentication/SAF flow. Never exposes a URL, path, token or file bytes. */
export const nativeExports = {
  async export(options: { input: ExportRequest }): Promise<ExportStatus> {
    const snapshot = selection(options);
    if (!hasNativeAuth()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
    let result: NativeAuthResult<ExportStatus>;
    try {
      result = await plugin.exportArchiveUI(snapshot);
    } catch {
      throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
    }
    if (!result.ok) {
      const errors: Record<string, [number, ApiErrorCode]> = {
        APP_LOCKED: [0, "APP_LOCKED"],
        SESSION_EXPIRED: [401, "UNAUTHENTICATED"],
        ACCESS_DENIED: [403, "FORBIDDEN"],
        AUTH_FAILED: [403, "REAUTHENTICATION_FAILED"],
        KEY_INVALIDATED: [401, "NATIVE_KEY_INVALIDATED"],
        AUTH_CANCELLED: [0, "REQUEST_CANCELLED"],
        INVALID_REQUEST: [422, "VALIDATION_ERROR"],
        NETWORK_UNAVAILABLE: [0, "NETWORK_UNAVAILABLE"],
        REAUTHENTICATION_REQUIRED: [403, "REAUTHENTICATION_REQUIRED"],
      };
      const [status, code] = errors[result.code] ?? ([0, "NATIVE_AUTH_UNAVAILABLE"] as const);
      throw new ApiError(status, code);
    }
    if (
      !object(result.value) ||
      Object.keys(result.value).length !== 1 ||
      !["exported", "cancelled"].includes(result.value.status)
    )
      throw new ApiError(403, "FORBIDDEN");
    return { status: result.value.status };
  },
};
