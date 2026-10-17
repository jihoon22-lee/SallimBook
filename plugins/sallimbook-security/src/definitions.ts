/** Safe bridge contract. Secret entry, decryption and display stay in native UI.
 * No arbitrary URLs, credentials, ciphertext or plaintext secret values cross this interface.
 * Native implementations must enforce session, household, foreground and user-action checks.
 */
export type SecurityErrorCode =
  | "AUTH_CANCELLED" | "AUTH_UNAVAILABLE" | "AUTH_LOCKED_OUT"
  | "KEY_INVALIDATED" | "VAULT_NOT_ENROLLED" | "SESSION_EXPIRED"
  | "ACCESS_DENIED" | "CIPHER_INVALID" | "NETWORK_UNAVAILABLE" | "UNSUPPORTED_PLATFORM";

export type SecurityResult<T> = { ok: true; value: T } | { ok: false; code: SecurityErrorCode };

export interface SecurityCapabilities {
  platform: "android" | "web" | "unsupported";
  available: boolean;
  supportedBiometrics: ("fingerprint" | "face" | "iris")[];
  /** null means the platform has not been queried by an implemented native module. */
  deviceSecure: boolean | null;
  vaultEnrolled: boolean | null;
  localCvcSupported: boolean;
}

export interface CardReference { cardId: string }

export interface SallimBookSecurity {
  getCapabilities(): Promise<SecurityResult<SecurityCapabilities>>;
  openCardSecretEditor(options: CardReference & { mode: "create" | "edit" }): Promise<SecurityResult<
    { status: "saved"; cardId: string; lastFour: string; version: number } | { status: "cancelled" }
  >>;
  showCardSecrets(options: CardReference & { includeLocalCvc: boolean }): Promise<SecurityResult<{ status: "completed" | "cancelled" | "expired" }>>;
  editLocalCvc(options: CardReference): Promise<SecurityResult<{ status: "saved" | "cancelled" }>>;
  deleteLocalCvc(options: CardReference): Promise<SecurityResult<{ status: "deleted" | "notFound" }>>;
  enrollDeviceVault(): Promise<SecurityResult<{ status: "enrolled" | "cancelled" }>>;
  lockVault(): Promise<SecurityResult<{ status: "locked" }>>;
  forgetDeviceVault(): Promise<SecurityResult<{ status: "forgotten" }>>;
}
