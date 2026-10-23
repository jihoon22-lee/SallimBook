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
  /**
   * An ordinary save that finds the session ended keeps its screen and asks to sign in again.
   * `clearOnExpiry` is for operations holding sensitive in-memory state (exports, vault,
   * document attachments):
   * the session ends and the screen is replaced by the sign-in prompt.
   */
  write<T>(
    web: ((client: WriteClient) => Promise<ApiResult<T>>) | undefined,
    native?: () => Promise<T>,
    proof?: ScopeProof,
    options?: { clearOnExpiry?: boolean },
  ): Promise<T>;
}
