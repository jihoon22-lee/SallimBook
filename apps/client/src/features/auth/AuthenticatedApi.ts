import type { createApiClient, components } from "@sallimbook/api-client";
import type { ApiResult } from "../../platform/api";

type Client = ReturnType<typeof createApiClient>;
export type ReadClient = Pick<Client, "GET">;
export type WriteClient = Pick<Client, "POST" | "PATCH" | "PUT" | "DELETE">;
export type ScopeProof = {
  purpose: Extract<
    components["schemas"]["StepUpPurpose"],
    "household.invite" | "device.revoke" | "account.reveal" | "data.export"
  >;
  targetId: string;
  signal: AbortSignal;
};

/** Domain code selects a generated operation, never receives CSRF/session/grant values. */
export interface AuthenticatedApi {
  read<T>(
    web: ((client: ReadClient) => Promise<ApiResult<T>>) | undefined,
    native?: () => Promise<T>,
  ): Promise<T>;
  write<T>(
    web: ((client: WriteClient) => Promise<ApiResult<T>>) | undefined,
    native?: () => Promise<T>,
    proof?: ScopeProof,
  ): Promise<T>;
}
