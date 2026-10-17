import { Capacitor } from "@capacitor/core";
import { createApiClient } from "@sallimbook/api-client";
import type { components } from "@sallimbook/api-client";

// The generated client includes credentials and disables response caching. Keep the same origin.
export const apiClient = createApiClient();

const knownCodes = [
  "APP_LOCKED",
  "UNAUTHENTICATED", "REAUTHENTICATION_REQUIRED", "CSRF_FAILED", "FORBIDDEN",
  "ORIGIN_REJECTED", "WRONG_AUTH_TRANSPORT", "AMBIGUOUS_AUTH", "RATE_LIMITED",
  "HOUSEHOLD_FULL", "LOGIN_UNAVAILABLE", "INVALID_INVITATION", "REGISTRATION_CONFLICT",
  "VERSION_REQUIRED", "INVALID_VERSION", "VERSION_CONFLICT", "NOT_FOUND",
  "VALIDATION_ERROR", "JSON_REQUIRED", "NETWORK_UNAVAILABLE", "REQUEST_FAILED",
  "REQUEST_CANCELLED", "NATIVE_AUTH_UNAVAILABLE", "ALREADY_AUTHENTICATED", "NATIVE_KEY_INVALIDATED",
  "PASSKEY_UNSUPPORTED", "PASSKEY_CANCELLED", "PASSKEY_EXPIRED", "PASSKEY_FAILED",
  "PASSKEY_CONFIGURATION_INVALID", "PASSKEY_VERIFICATION_FAILED", "PASSKEY_REQUIRED",
  "CREDENTIAL_UNAVAILABLE", "STEP_UP_REQUIRED", "PASSKEYS_DISABLED",
  "REAUTHENTICATION_FAILED", "OWNER_UNAVAILABLE", "INVALID_ASSET", "ASSET_IN_USE", "ASSET_KIND_IN_USE",
  "FINANCIAL_ASSET_REQUIRED", "ASSET_ALREADY_LINKED", "INVALID_ACCOUNT", "ACCOUNT_NUMBER_NOT_SET",
  "FIELD_ENCRYPTION_UNAVAILABLE", "ACCOUNT_NUMBER_UNAVAILABLE", "INVALID_ACCOUNT_DATES",
  "INVALID_IDEMPOTENCY_KEY", "IDEMPOTENCY_CONFLICT", "OPERATION_IN_PROGRESS",
  "MONTH_NOT_FOUND", "MONTH_ALREADY_EXISTS", "MONTH_CONFIRMED",
  "MONTH_NOT_CONFIRMED", "REVISION_CONFLICT", "VALUE_CONFLICT",
  "INVALID_AS_OF_DATE", "NO_CARRIED_VALUE", "MONTH_SCOPE_CHANGED",
  "MONTH_UNVERIFIED", "AS_OF_DATE_ACK_REQUIRED", "SCOPE_ACK_REQUIRED",
  "INVALID_PAGE_SIZE", "TOTAL_OUT_OF_RANGE", "INVALID_OCCURRED_DATE",
  "ACCOUNT_UNAVAILABLE", "MEMBER_UNAVAILABLE", "INCOME_HAS_RETURNS",
  "INVALID_CASH_KIND", "MEMBER_REQUIRED", "INVALID_REVERSAL",
  "RETURN_EXCEEDS_ORIGINAL", "SOURCE_DOMAIN_REQUIRED", "INCOME_VOID",
  "INCOME_DUPLICATE_SUSPECTED", "INVALID_INCOME", "INVALID_CONVERSION",
  "CONVERSION_TOTAL_MISMATCH", "INCOMPLETE_CONVERSION", "AMOUNT_OUT_OF_RANGE",
  "INVALID_CARD", "INVALID_CARD_DATES", "CARD_IN_USE", "PAYMENT_LINK_CONFIRMATION_REQUIRED", "PAYMENT_LINKS_CHANGED",
  "INVALID_COMPARISON_RANGE", "INVALID_COMPARISON_FILTERS", "INVALID_TREND_RANGE",
  "LOAN_UNAVAILABLE", "CARD_UNAVAILABLE", "RULE_PERIOD_OVERLAP", "PAST_RULE_CHANGE",
  "GENERATION_TOO_LARGE", "OBLIGATION_SUPERSEDED", "OBLIGATION_HAS_PAYMENT",
  "INVALID_OBLIGATION_STATE", "ACTUAL_PAYMENT_REQUIRED", "OBLIGATION_CLOSED", "INVALID_PAYMENT_SPLIT",
] as const;

export type ApiErrorCode = typeof knownCodes[number];

/** Deliberately retains no response body, submitted value or server-provided error message. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;

  constructor(status: number, code: ApiErrorCode) {
    super(code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function isNativeAuthUnavailable(): boolean {
  return Capacitor.isNativePlatform() && (Capacitor.getPlatform() !== "android" || !Capacitor.isPluginAvailable("SallimBookAuth"));
}

export function requireWebAuth(): void {
  if (Capacitor.isNativePlatform()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
}

export function apiErrorCode(received: unknown, status: number): ApiErrorCode {
  return knownCodes.find((known) => known === received) ?? (status === 401 ? "UNAUTHENTICATED" : "REQUEST_FAILED");
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof DOMException && error.name === "AbortError") return new ApiError(0, "REQUEST_CANCELLED");
  return new ApiError(0, error instanceof TypeError ? "NETWORK_UNAVAILABLE" : "REQUEST_FAILED");
}

export type ApiResult<T> = {
  data?: T;
  error?: components["schemas"]["ErrorResponse"];
  response: Response;
};

export async function requestApi<T>(request: () => Promise<ApiResult<T>>): Promise<T> {
  try {
    const result = await request();
    if (!result.response.ok) {
      const received = result.error?.error?.code;
      const code = apiErrorCode(received, result.response.status);
      throw new ApiError(result.response.status, code);
    }
    return result.data as T;
  } catch (error) {
    throw toApiError(error);
  }
}
