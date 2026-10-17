import type { components } from "@sallimbook/api-client";
import type {
  NativeAccountCreate, NativeAccountPatch, NativeAccountQuery, NativeAssetQuery,
  NativeAuthResult, NativeFinanceResponse, SallimBookAuth,
} from "../../../../plugins/sallimbook-auth/src/definitions";
import { ApiError, apiErrorCode } from "./api";
import { hasNativeAuth, nativeAuthPlugin as plugin } from "./nativeAuth";

async function invoke<T>(action: () => Promise<NativeAuthResult<T>>): Promise<T> {
  if (!hasNativeAuth()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
  let result: NativeAuthResult<T>;
  try { result = await action(); }
  catch { throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE"); }
  if (result.ok) return result.value;
  switch (result.code) {
    case "APP_LOCKED": throw new ApiError(0, "APP_LOCKED");
    case "SESSION_EXPIRED": throw new ApiError(401, "UNAUTHENTICATED");
    case "KEY_INVALIDATED": throw new ApiError(401, "NATIVE_KEY_INVALIDATED");
    case "ACCESS_DENIED": throw new ApiError(403, "FORBIDDEN");
    case "AUTH_CANCELLED": throw new ApiError(0, "REQUEST_CANCELLED");
    case "INVALID_REQUEST": throw new ApiError(422, "VALIDATION_ERROR");
    case "REAUTHENTICATION_REQUIRED": throw new ApiError(403, "REAUTHENTICATION_REQUIRED");
    case "VERSION_CONFLICT": throw new ApiError(409, "VERSION_CONFLICT");
    case "NETWORK_UNAVAILABLE": throw new ApiError(0, "NETWORK_UNAVAILABLE");
    case "PASSKEYS_DISABLED": throw new ApiError(0, "PASSKEYS_DISABLED");
    case "PASSKEY_REQUIRED": throw new ApiError(409, "PASSKEY_REQUIRED");
    case "PASSKEY_CANCELLED": throw new ApiError(0, "PASSKEY_CANCELLED");
    case "PASSKEY_FAILED": throw new ApiError(0, "PASSKEY_FAILED");
    default: throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
  }
}

async function metadata<T>(action: () => Promise<NativeAuthResult<NativeFinanceResponse<T>>>): Promise<T> {
  const result = await invoke(action);
  if (result.status < 200 || result.status >= 300) {
    const error = result.body as components["schemas"]["ErrorResponse"] | null;
    throw new ApiError(result.status, apiErrorCode(error?.error?.code, result.status));
  }
  return result.body as T;
}

function metadataOnly(input: NativeAccountCreate | NativeAccountPatch): void {
  // Reject accidental use of the web number form before invoking the native bridge.
  if (Object.hasOwn(input, "account_number")) throw new ApiError(422, "VALIDATION_ERROR");
}

/** Tokenless, generated-schema metadata operations. No URL, bearer token or raw body API. */
export const nativeFinance = {
  listAssets: (query: NativeAssetQuery = {}) => metadata(() => plugin.listAssets({ query })),
  getAsset: (assetId: string) => metadata(() => plugin.getAsset({ assetId })),
  createAsset: (input: components["schemas"]["AssetCreate"]) => metadata(() => plugin.createAsset({ input })),
  updateAsset: (assetId: string, input: components["schemas"]["AssetPatch"], ifMatch: string) => metadata(() => plugin.updateAsset({ assetId, input, ifMatch })),
  archiveAsset: (assetId: string, input: components["schemas"]["AssetArchive"], ifMatch: string) => metadata(() => plugin.archiveAsset({ assetId, input, ifMatch })),
  deleteAsset: (assetId: string, ifMatch: string) => metadata(() => plugin.deleteAsset({ assetId, ifMatch })),
  listAccounts: (query: NativeAccountQuery = {}) => metadata(() => plugin.listAccounts({ query })),
  getAccount: (accountId: string) => metadata(() => plugin.getAccount({ accountId })),
  createAccount: (input: NativeAccountCreate) => { metadataOnly(input); return metadata(() => plugin.createAccount({ input })); },
  updateAccount: (accountId: string, input: NativeAccountPatch, ifMatch: string) => { metadataOnly(input); return metadata(() => plugin.updateAccount({ accountId, input, ifMatch })); },
  getAssetMonth: (options: Parameters<SallimBookAuth["getAssetMonth"]>[0]) => metadata(() => plugin.getAssetMonth(options)),
  getAssetMonthRevision: (options: Parameters<SallimBookAuth["getAssetMonthRevision"]>[0]) => metadata(() => plugin.getAssetMonthRevision(options)),
  listAssetMonthRevisions: (options: Parameters<SallimBookAuth["listAssetMonthRevisions"]>[0]) => metadata(() => plugin.listAssetMonthRevisions(options)),
  createAssetMonthDraft: (options: Parameters<SallimBookAuth["createAssetMonthDraft"]>[0]) => metadata(() => plugin.createAssetMonthDraft(options)),
  updateAssetMonthValue: (options: Parameters<SallimBookAuth["updateAssetMonthValue"]>[0]) => metadata(() => plugin.updateAssetMonthValue(options)),
  synchronizeAssetMonthScope: (options: Parameters<SallimBookAuth["synchronizeAssetMonthScope"]>[0]) => metadata(() => plugin.synchronizeAssetMonthScope(options)),
  confirmAssetMonth: (options: Parameters<SallimBookAuth["confirmAssetMonth"]>[0]) => metadata(() => plugin.confirmAssetMonth(options)),
  reopenAssetMonth: (options: Parameters<SallimBookAuth["reopenAssetMonth"]>[0]) => metadata(() => plugin.reopenAssetMonth(options)),
  listIncome: (options: Parameters<SallimBookAuth["listIncome"]>[0]) => metadata(() => plugin.listIncome(options)),
  incomeSummary: (options: Parameters<SallimBookAuth["incomeSummary"]>[0]) => metadata(() => plugin.incomeSummary(options)),
  incomeDuplicateCandidates: (options: Parameters<SallimBookAuth["incomeDuplicateCandidates"]>[0]) => metadata(() => plugin.incomeDuplicateCandidates(options)),
  getIncome: (options: Parameters<SallimBookAuth["getIncome"]>[0]) => metadata(() => plugin.getIncome(options)),
  incomeHistory: (options: Parameters<SallimBookAuth["incomeHistory"]>[0]) => metadata(() => plugin.incomeHistory(options)),
  createIncome: (options: Parameters<SallimBookAuth["createIncome"]>[0]) => metadata(() => plugin.createIncome(options)),
  correctIncome: (options: Parameters<SallimBookAuth["correctIncome"]>[0]) => metadata(() => plugin.correctIncome(options)),
  voidIncome: (options: Parameters<SallimBookAuth["voidIncome"]>[0]) => metadata(() => plugin.voidIncome(options)),
  returnIncome: (options: Parameters<SallimBookAuth["returnIncome"]>[0]) => metadata(() => plugin.returnIncome(options)),
  convertIncomePrecision: (options: Parameters<SallimBookAuth["convertIncomePrecision"]>[0]) => metadata(() => plugin.convertIncomePrecision(options)),
  editAccountNumber: (options: { accountId: string; ifMatch: string }) => invoke(() => plugin.editAccountNumberUI(options)),
  showAccountNumber: (options: { accountId: string }) => invoke(() => plugin.showAccountNumberUI(options)),
  showAccountNumberWithPasskey: (options: { accountId: string }) => invoke(() => plugin.showAccountNumberWithPasskeyUI(options)),
};
