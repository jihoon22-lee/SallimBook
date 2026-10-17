/** Account-auth bridge only. Native UI owns all password/invitation input and tokens.
 * API origin is signed into the Android build; no host, credentials or auth URLs are arguments.
 * Business response types continue to come from the generated API client, not this contract.
 */
export type NativeAuthErrorCode =
  | "AUTH_UNAVAILABLE" | "AUTH_CANCELLED" | "ACCESS_DENIED" | "SESSION_EXPIRED"
  | "KEY_INVALIDATED" | "NETWORK_UNAVAILABLE" | "INVALID_REQUEST"
  | "AUTH_FAILED" | "REGISTRATION_FAILED" | "PASSKEYS_DISABLED" | "PASSKEY_REQUIRED"
  | "PASSKEY_CANCELLED" | "PASSKEY_FAILED" | "REAUTHENTICATION_REQUIRED";

export type NativeAuthResult<T> = { ok: true; value: T } | { ok: false; code: NativeAuthErrorCode };
export type NativeJson = null | boolean | number | string | NativeJson[] | { [key: string]: NativeJson };

export interface NativeSessionState {
  available: boolean;
  authenticated: boolean;
}

export interface NativeMetadataRequest {
  /** Only GET /me, /household/members, /devices, /auth/passkeys and DELETE /devices/{UUID}. */
  method: "GET" | "DELETE";
  path: string;
  /** Required strong version tag for DELETE. Arbitrary headers/bodies are never accepted. */
  ifMatch?: string;
}

export interface SallimBookAuth {
  getSession(): Promise<NativeAuthResult<NativeSessionState>>;
  loginUI(): Promise<NativeAuthResult<{ status: "authenticated" | "cancelled" }>>;
  /** Accepts the invitation in native UI; sign-in is a separate action. */
  acceptInvitationUI(): Promise<NativeAuthResult<{ status: "accepted" | "cancelled" }>>;
  /** Intended login and the generated invitation secret are handled/displayed only in native UI. */
  createInvitationUI(): Promise<NativeAuthResult<{ status: "created" | "cancelled" }>>;
  /** Native Credential Manager owns all challenge, response, device binding and token data. */
  passkeyLoginUI(): Promise<NativeAuthResult<{ status: "authenticated" | "cancelled" }>>;
  registerPasskeyUI(): Promise<NativeAuthResult<{ status: "registered" | "cancelled" }>>;
  revokePasskeyUI(options: { credentialId: string; ifMatch: string }): Promise<NativeAuthResult<{ status: "revoked" | "cancelled" }>>;
  /** Scope and target are fixed internally; no reusable step-up grant crosses the bridge. */
  revokeDeviceUI(options: { deviceId: string; ifMatch: string }): Promise<NativeAuthResult<{ status: "revoked" | "cancelled" }>>;
  createInvitationWithPasskeyUI(): Promise<NativeAuthResult<{ status: "created" | "cancelled" }>>;
  logout(): Promise<NativeAuthResult<{ status: "signedOut"; serverRevoked: boolean }>>;
  request(options: NativeMetadataRequest): Promise<NativeAuthResult<{ status: number; body: NativeJson }>>;
}
