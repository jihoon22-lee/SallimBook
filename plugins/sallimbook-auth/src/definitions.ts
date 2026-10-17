import type { components, operations } from "../../../packages/api-client/src/schema";

/** Native UI owns all password/invitation/account-number input and tokens.
 * API origin is signed into the Android build; no host, credentials or auth URLs are arguments.
 * Business response types continue to come from the generated API client, not this contract.
 */
export type NativeAuthErrorCode =
  | "AUTH_UNAVAILABLE" | "AUTH_CANCELLED" | "ACCESS_DENIED" | "SESSION_EXPIRED"
  | "KEY_INVALIDATED" | "NETWORK_UNAVAILABLE" | "INVALID_REQUEST"
  | "AUTH_FAILED" | "REGISTRATION_FAILED" | "PASSKEYS_DISABLED" | "PASSKEY_REQUIRED"
  | "PASSKEY_CANCELLED" | "PASSKEY_FAILED" | "REAUTHENTICATION_REQUIRED" | "VERSION_CONFLICT" | "APP_LOCKED";

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

export type NativeAssetQuery = NonNullable<operations["listAssets"]["parameters"]["query"]>;
export type NativeAccountQuery = NonNullable<operations["listAccounts"]["parameters"]["query"]>;
export type NativeAccountCreate = Omit<components["schemas"]["AccountCreate"], "account_number">;
export type NativeAccountPatch = Omit<components["schemas"]["AccountPatch"], "account_number">;
export type NativeFinanceResponse<T> = { status: number; body: T | components["schemas"]["ErrorResponse"] | null };

export interface SallimBookAuth {
  /** Safe status only. Unlock is controlled exclusively by the native screen. */
  getAppLock(): Promise<NativeAuthResult<{ locked: boolean }>>;
  lockApp(): Promise<NativeAuthResult<{ locked: true }>>;
  addListener(event: "appLockChanged", listener: (state: { locked: boolean }) => void): Promise<{ remove(): Promise<void> }>;
  getSession(): Promise<NativeAuthResult<NativeSessionState>>;
  loginUI(): Promise<NativeAuthResult<{ status: "authenticated" | "cancelled" }>>;
  /** Confirms the current account password without creating another device or session. */
  reauthenticateUI(): Promise<NativeAuthResult<{ status: "authenticated" | "cancelled" }>>;
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
  listAssets(options: { query?: NativeAssetQuery }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetListResponse"]>>>;
  getAsset(options: { assetId: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetResponse"]>>>;
  createAsset(options: { input: components["schemas"]["AssetCreate"] }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetResponse"]>>>;
  updateAsset(options: { assetId: string; input: components["schemas"]["AssetPatch"]; ifMatch: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetResponse"]>>>;
  archiveAsset(options: { assetId: string; input: components["schemas"]["AssetArchive"]; ifMatch: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetResponse"]>>>;
  deleteAsset(options: { assetId: string; ifMatch: string }): Promise<NativeAuthResult<NativeFinanceResponse<null>>>;
  listAccounts(options: { query?: NativeAccountQuery }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AccountListResponse"]>>>;
  getAccount(options: { accountId: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AccountResponse"]>>>;
  createAccount(options: { input: NativeAccountCreate }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AccountResponse"]>>>;
  updateAccount(options: { accountId: string; input: NativeAccountPatch; ifMatch: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AccountResponse"]>>>;
  getAssetMonth(options: { month: string; query?: NonNullable<operations["getAssetMonth"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthResponse"]>>>;
  getAssetMonthRevision(options: { month: string; revisionNo: number; query?: NonNullable<operations["getAssetMonthRevision"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthResponse"]>>>;
  listAssetMonthRevisions(options: { month: string; query?: NonNullable<operations["listAssetMonthRevisions"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthHistoryResponse"]>>>;
  createAssetMonthDraft(options: { month: string; input: components["schemas"]["MonthDraft"]; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthReference"]>>>;
  updateAssetMonthValue(options: { month: string; assetId: string; input: components["schemas"]["MonthValueUpdate"]; ifMatch: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthValueResult"]>>>;
  synchronizeAssetMonthScope(options: { month: string; input: components["schemas"]["MonthScopeSync"]; ifMatch: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthReference"]>>>;
  confirmAssetMonth(options: { month: string; input: components["schemas"]["MonthConfirm"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthReference"]>>>;
  reopenAssetMonth(options: { month: string; input: components["schemas"]["MonthReopen"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthReference"]>>>;
  listIncome(options: { query: NonNullable<operations["listIncome"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["IncomeListResponse"]>>>;
  incomeSummary(options: { query: NonNullable<operations["incomeSummary"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["IncomeSummaryResponse"]>>>;
  incomeDuplicateCandidates(options: { query: NonNullable<operations["incomeDuplicateCandidates"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["DuplicateResponse"]>>>;
  getIncome(options: { recordId: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  incomeHistory(options: { recordId: string; query?: NonNullable<operations["incomeHistory"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["IncomeHistoryResponse"]>>>;
  createIncome(options: { input: components["schemas"]["IncomeCreate"]; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  correctIncome(options: { recordId: string; input: components["schemas"]["IncomePatch"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  voidIncome(options: { recordId: string; input: components["schemas"]["IncomeVoid"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  returnIncome(options: { recordId: string; input: components["schemas"]["IncomeReturn"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  convertIncomePrecision(options: { input: components["schemas"]["IncomeConvert"]; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ConversionResponse"]>>>;
  listCards(options: { query?: NonNullable<operations["listCards"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardListResponse"]>>>;
  getCard(options: { cardId: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardResponse"]>>>;
  createCard(options: { input: components["schemas"]["CardCreate"] }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardResponse"]>>>;
  updateCard(options: { cardId: string; input: components["schemas"]["CardPatch"]; ifMatch: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardResponse"]>>>;
  archiveCard(options: { cardId: string; input: components["schemas"]["CardArchive"]; ifMatch: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardResponse"]>>>;
  deleteCard(options: { cardId: string; ifMatch: string }): Promise<NativeAuthResult<NativeFinanceResponse<null>>>;
  getAssetComparison(options: { query: operations["getAssetComparison"]["parameters"]["query"] }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetComparisonResponse"]>>>;
  getAssetTrends(options: { query: operations["getAssetTrends"]["parameters"]["query"] }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetTrendResponse"]>>>;
  listObligations(options: { query: NonNullable<operations["listObligations"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ObligationListResponse"]>>>;
  generateObligations(options: { input: components["schemas"]["GenerateObligations"]; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["GenerationResponse"]>>>;
  fixedCostSummary(options: { query: NonNullable<operations["fixedCostSummary"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["FixedSummaryResponse"]>>>;
  getObligation(options: { obligationId: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ObligationResponse"]>>>;
  rescheduleObligation(options: { obligationId: string; input: components["schemas"]["ObligationReschedule"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  completeObligation(options: { obligationId: string; input: components["schemas"]["ObligationAction"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  obligationHistory(options: { obligationId: string; query?: NonNullable<operations["obligationHistory"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ObligationHistoryResponse"]>>>;
  reopenObligation(options: { obligationId: string; input: components["schemas"]["ObligationAction"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  listObligationSettlements(options: { obligationId: string; query?: NonNullable<operations["listObligationSettlements"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["SettlementListResponse"]>>>;
  settleObligation(options: { obligationId: string; input: components["schemas"]["SettlementCreate"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["SettlementResponse"]>>>;
  skipObligation(options: { obligationId: string; input: components["schemas"]["ObligationAction"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  unskipObligation(options: { obligationId: string; input: components["schemas"]["ObligationAction"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  listRecurringRules(options: { query?: NonNullable<operations["listRecurringRules"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["RuleListResponse"]>>>;
  createRecurringRule(options: { input: components["schemas"]["RuleCreate"]; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  getRecurringRule(options: { ruleId: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["RuleResponse"]>>>;
  changeRecurringRule(options: { ruleId: string; input: components["schemas"]["RuleChange"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  endRecurringRule(options: { ruleId: string; input: components["schemas"]["RuleEnd"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  voidFixedSettlement(options: { settlementId: string; input: components["schemas"]["ObligationAction"]; ifMatch: string; idempotencyKey: string }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["SettlementResponse"]>>>;
  getCardPaymentLinks(options: { resourceId: operations["getCardPaymentLinks"]["parameters"]["path"]["resource_id"]; query?: NonNullable<operations["getCardPaymentLinks"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["PaymentLinksResponse"]>>>;
  getAccountPaymentLinks(options: { resourceId: operations["getAccountPaymentLinks"]["parameters"]["path"]["resource_id"]; query?: NonNullable<operations["getAccountPaymentLinks"]["parameters"]["query"]> }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["PaymentLinksResponse"]>>>;
  /** Number plaintext and ciphertext never appear in arguments or return values. */
  editAccountNumberUI(options: { accountId: string; ifMatch: string }): Promise<NativeAuthResult<{ status: "saved" | "deleted" | "cancelled" }>>;
  showAccountNumberUI(options: { accountId: string }): Promise<NativeAuthResult<{ status: "completed" | "cancelled" }>>;
  showAccountNumberWithPasskeyUI(options: { accountId: string }): Promise<NativeAuthResult<{ status: "completed" | "cancelled" }>>;
  logout(): Promise<NativeAuthResult<{ status: "signedOut"; serverRevoked: boolean }>>;
  request(options: NativeMetadataRequest): Promise<NativeAuthResult<{ status: number; body: NativeJson }>>;
}
