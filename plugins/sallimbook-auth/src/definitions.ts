import type { components, operations } from "../../../packages/api-client/src/schema";

/** Native UI owns all password/invitation/account-number input and tokens.
 * API origin is signed into the Android build; no host, credentials or auth URLs are arguments.
 * Business response types continue to come from the generated API client, not this contract.
 */
export type NativeAuthErrorCode =
  | "SETUP_UNAVAILABLE"
  | "SETUP_COMPLETE"
  | "INVALID_CONNECTION_CODE"
  | "HOUSEHOLD_FULL"
  | "RATE_LIMITED"
  | "REGISTRATION_CONFLICT"
  | "LOGIN_UNAVAILABLE"
  | "VALIDATION_ERROR"
  | "AUTH_UNAVAILABLE"
  | "AUTH_CANCELLED"
  | "ACCESS_DENIED"
  | "SESSION_EXPIRED"
  | "KEY_INVALIDATED"
  | "NETWORK_UNAVAILABLE"
  | "INVALID_REQUEST"
  | "AUTH_FAILED"
  | "REGISTRATION_FAILED"
  | "PASSKEYS_DISABLED"
  | "PASSKEY_REQUIRED"
  | "PASSKEY_CANCELLED"
  | "PASSKEY_FAILED"
  | "REAUTHENTICATION_REQUIRED"
  | "VERSION_CONFLICT"
  | "APP_LOCKED";

export type NativeAuthResult<T> = { ok: true; value: T } | { ok: false; code: NativeAuthErrorCode };
export type NativeJson =
  null | boolean | number | string | NativeJson[] | { [key: string]: NativeJson };

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
export type NativeFinanceResponse<T> = {
  status: number;
  body: T | components["schemas"]["ErrorResponse"] | null;
};

/** IDs and an action only; every protected input and result is native-owned. */
export type NativeVaultEntry =
  | { action: "manage" | "setup" | "register-device" | "change-password" | "recover" | "rotate" }
  | { action: "view" | "edit" | "purge" | "cvc-view" | "cvc-edit" | "cvc-delete"; cardId: string }
  | { action: "share" | "revoke-member"; memberId: string }
  | { action: "accept-share" | "cancel-share"; offerId: string }
  | { action: "resume-rotation" | "abort-rotation"; rotationId: string };

export interface SallimBookAuth {
  /** First-account availability only; no setup secret or operator token crosses the bridge. */
  getSetupStatus(): Promise<NativeAuthResult<components["schemas"]["SetupStatusResponse"]>>;
  /** Native UI owns name/password/confirmation and installs the resulting session. */
  createHousehold(): Promise<NativeAuthResult<{ status: "authenticated" | "cancelled" }>>;
  /** Native UI additionally owns the eight-digit connection code. */
  connectHousehold(): Promise<NativeAuthResult<{ status: "authenticated" | "cancelled" }>>;
  /** Generated connection code is displayed only on the native protected screen. */
  createConnectionCode(): Promise<NativeAuthResult<{ status: "created" | "cancelled" }>>;
  listAuditEvents(options: {
    query?: NonNullable<operations["listAuditEvents"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AuditListResponse"]>>>;
  openVaultUI(
    options: NativeVaultEntry,
  ): Promise<NativeAuthResult<{ status: "completed" | "cancelled" }>>;
  getVaultStatus(): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["VaultStatusResponse"]>>
  >;
  listVaultShares(options: {
    query?: NonNullable<operations["listVaultShares"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["VaultShareListResponse"]>>
  >;
  getVaultRotation(options: {
    rotationId: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["VaultRotationResponse"]>>
  >;
  deleteAppliance(options: {
    applianceId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<null>>>;
  deleteConsumable(options: {
    consumableId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<null>>>;
  deleteApplianceConsumable(options: {
    linkId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<null>>>;
  /** File bytes/URIs stay in native UI; createDocument is deliberately not a bridge command. */
  createDocumentLink(options: {
    input: components["schemas"]["DocumentLinkCreate"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["DocumentMutationReference"]>>
  >;
  endDocumentLink(options: {
    linkId: string;
    input: components["schemas"]["DocumentReason"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["DocumentMutationReference"]>>
  >;
  listDocuments(options: {
    query?: NonNullable<operations["listDocuments"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["DocumentListResponse"]>>
  >;
  getDocument(options: {
    documentId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["DocumentResponse"]>>>;
  deleteDocument(options: {
    documentId: string;
    input: components["schemas"]["DocumentReason"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["DocumentMutationReference"]>>
  >;
  listDocumentLinks(options: {
    documentId: string;
    query?: NonNullable<operations["listDocumentLinks"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["DocumentLinkListResponse"]>>
  >;
  uploadDocumentUI(options: {
    target: components["schemas"]["DocumentTarget"];
  }): Promise<NativeAuthResult<{ status: "uploaded" | "cancelled" }>>;
  downloadDocumentUI(options: {
    documentId: string;
  }): Promise<NativeAuthResult<{ status: "downloaded" | "cancelled" }>>;
  exportArchiveUI(options: {
    input: components["schemas"]["ExportRequest"];
  }): Promise<NativeAuthResult<{ status: "exported" | "cancelled" }>>;
  /** Homecare metadata; stock If-Match and immutable receipt versions belong to the consumable. */
  listApplianceConsumables(options: {
    query?: NonNullable<operations["listApplianceConsumables"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<
      NativeFinanceResponse<components["schemas"]["ApplianceConsumableListResponse"]>
    >
  >;
  createApplianceConsumable(options: {
    input: components["schemas"]["ApplianceConsumableCreate"];
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ApplianceConsumableResponse"]>>
  >;
  getApplianceConsumable(options: {
    linkId: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ApplianceConsumableResponse"]>>
  >;
  updateApplianceConsumable(options: {
    linkId: string;
    input: components["schemas"]["ApplianceConsumablePatch"];
    ifMatch: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ApplianceConsumableResponse"]>>
  >;
  listConsumableReplacements(options: {
    linkId: string;
    query?: NonNullable<operations["listConsumableReplacements"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ReplacementListResponse"]>>
  >;
  createConsumableReplacement(options: {
    linkId: string;
    input: components["schemas"]["ReplacementCreate"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["StockMutationReference"]>>
  >;
  getConsumableReplacement(options: {
    linkId: string;
    replacementId: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ReplacementResponse"]>>
  >;
  cancelConsumableReplacement(options: {
    linkId: string;
    replacementId: string;
    input: components["schemas"]["StockCancellation"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["StockMutationReference"]>>
  >;
  listAppliances(options: {
    query?: NonNullable<operations["listAppliances"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ApplianceListResponse"]>>
  >;
  createAppliance(options: {
    input: components["schemas"]["ApplianceInput"];
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ApplianceResponse"]>>>;
  getAppliance(options: {
    applianceId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ApplianceResponse"]>>>;
  updateAppliance(options: {
    applianceId: string;
    input: components["schemas"]["AppliancePatch"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ApplianceResponse"]>>>;
  listConsumables(options: {
    query?: NonNullable<operations["listConsumables"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ConsumableListResponse"]>>
  >;
  createConsumable(options: {
    input: components["schemas"]["ConsumableInput"];
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ConsumableResponse"]>>>;
  getConsumable(options: {
    consumableId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ConsumableResponse"]>>>;
  updateConsumable(options: {
    consumableId: string;
    input: components["schemas"]["ConsumablePatch"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ConsumableResponse"]>>>;
  listStockMovements(options: {
    consumableId: string;
    query?: NonNullable<operations["listStockMovements"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["StockMovementListResponse"]>>
  >;
  createStockMovement(options: {
    consumableId: string;
    input: components["schemas"]["StockMovementCreate"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["StockMutationReference"]>>
  >;
  getStockMovement(options: {
    consumableId: string;
    movementId: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["StockMovementResponse"]>>
  >;
  cancelStockMovement(options: {
    consumableId: string;
    movementId: string;
    input: components["schemas"]["StockCancellation"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["StockMutationReference"]>>
  >;
  getHomecareStatus(options: {
    query?: NonNullable<operations["getHomecareStatus"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["HomecareStatusResponse"]>>
  >;
  /** Safe status only. Unlock is controlled exclusively by the native screen. */
  getAppLock(): Promise<NativeAuthResult<{ locked: boolean }>>;
  lockApp(): Promise<NativeAuthResult<{ locked: true }>>;
  addListener(
    event: "appLockChanged",
    listener: (state: { locked: boolean }) => void,
  ): Promise<{ remove(): Promise<void> }>;
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
  revokePasskeyUI(options: {
    credentialId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<{ status: "revoked" | "cancelled" }>>;
  /** Scope and target are fixed internally; no reusable step-up grant crosses the bridge. */
  revokeDeviceUI(options: {
    deviceId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<{ status: "revoked" | "cancelled" }>>;
  createInvitationWithPasskeyUI(): Promise<NativeAuthResult<{ status: "created" | "cancelled" }>>;
  listAssets(options: {
    query?: NativeAssetQuery;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetListResponse"]>>>;
  getAsset(options: {
    assetId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetResponse"]>>>;
  createAsset(options: {
    input: components["schemas"]["AssetCreate"];
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetResponse"]>>>;
  updateAsset(options: {
    assetId: string;
    input: components["schemas"]["AssetPatch"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetResponse"]>>>;
  archiveAsset(options: {
    assetId: string;
    input: components["schemas"]["AssetArchive"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetResponse"]>>>;
  deleteAsset(options: {
    assetId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<null>>>;
  listAccounts(options: {
    query?: NativeAccountQuery;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["AccountListResponse"]>>
  >;
  getAccount(options: {
    accountId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AccountResponse"]>>>;
  createAccount(options: {
    input: NativeAccountCreate;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AccountResponse"]>>>;
  updateAccount(options: {
    accountId: string;
    input: NativeAccountPatch;
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AccountResponse"]>>>;
  getAssetMonth(options: {
    month: string;
    query?: NonNullable<operations["getAssetMonth"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthResponse"]>>>;
  getAssetMonthRevision(options: {
    month: string;
    revisionNo: number;
    query?: NonNullable<operations["getAssetMonthRevision"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthResponse"]>>>;
  listAssetMonthRevisions(options: {
    month: string;
    query?: NonNullable<operations["listAssetMonthRevisions"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthHistoryResponse"]>>
  >;
  createAssetMonthDraft(options: {
    month: string;
    input: components["schemas"]["MonthDraft"];
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthReference"]>>>;
  updateAssetMonthValue(options: {
    month: string;
    assetId: string;
    input: components["schemas"]["MonthValueUpdate"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthValueResult"]>>>;
  synchronizeAssetMonthScope(options: {
    month: string;
    input: components["schemas"]["MonthScopeSync"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthReference"]>>>;
  confirmAssetMonth(options: {
    month: string;
    input: components["schemas"]["MonthConfirm"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthReference"]>>>;
  reopenAssetMonth(options: {
    month: string;
    input: components["schemas"]["MonthReopen"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthReference"]>>>;
  carryPreviousAssetMonth(options: {
    month: string;
    input: components["schemas"]["MonthCarryPrevious"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MonthReference"]>>>;
  listIncome(options: {
    query: NonNullable<operations["listIncome"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["IncomeListResponse"]>>>;
  incomeSummary(options: {
    query: NonNullable<operations["incomeSummary"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["IncomeSummaryResponse"]>>
  >;
  incomeDuplicateCandidates(options: {
    query: NonNullable<operations["incomeDuplicateCandidates"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["DuplicateResponse"]>>>;
  getIncome(options: {
    recordId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  incomeHistory(options: {
    recordId: string;
    query?: NonNullable<operations["incomeHistory"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["IncomeHistoryResponse"]>>
  >;
  createIncome(options: {
    input: components["schemas"]["IncomeCreate"];
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  correctIncome(options: {
    recordId: string;
    input: components["schemas"]["IncomePatch"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  voidIncome(options: {
    recordId: string;
    input: components["schemas"]["IncomeVoid"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  returnIncome(options: {
    recordId: string;
    input: components["schemas"]["IncomeReturn"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CashResponse"]>>>;
  convertIncomePrecision(options: {
    input: components["schemas"]["IncomeConvert"];
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ConversionResponse"]>>>;
  listCards(options: {
    query?: NonNullable<operations["listCards"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardListResponse"]>>>;
  getCard(options: {
    cardId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardResponse"]>>>;
  createCard(options: {
    input: components["schemas"]["CardCreate"];
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardResponse"]>>>;
  updateCard(options: {
    cardId: string;
    input: components["schemas"]["CardPatch"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardResponse"]>>>;
  archiveCard(options: {
    cardId: string;
    input: components["schemas"]["CardArchive"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CardResponse"]>>>;
  deleteCard(options: {
    cardId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<null>>>;
  getAssetComparison(options: {
    query: operations["getAssetComparison"]["parameters"]["query"];
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetComparisonResponse"]>>
  >;
  getAssetTrends(options: {
    query: operations["getAssetTrends"]["parameters"]["query"];
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AssetTrendResponse"]>>>;
  listObligations(options: {
    query: NonNullable<operations["listObligations"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ObligationListResponse"]>>
  >;
  generateObligations(options: {
    input: components["schemas"]["GenerateObligations"];
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["GenerationResponse"]>>>;
  fixedCostSummary(options: {
    query: NonNullable<operations["fixedCostSummary"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["FixedSummaryResponse"]>>
  >;
  getObligation(options: {
    obligationId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ObligationResponse"]>>>;
  rescheduleObligation(options: {
    obligationId: string;
    input: components["schemas"]["ObligationReschedule"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  completeObligation(options: {
    obligationId: string;
    input: components["schemas"]["ObligationAction"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  obligationHistory(options: {
    obligationId: string;
    query?: NonNullable<operations["obligationHistory"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ObligationHistoryResponse"]>>
  >;
  reopenObligation(options: {
    obligationId: string;
    input: components["schemas"]["ObligationAction"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  listObligationSettlements(options: {
    obligationId: string;
    query?: NonNullable<operations["listObligationSettlements"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["SettlementListResponse"]>>
  >;
  settleObligation(options: {
    obligationId: string;
    input: components["schemas"]["SettlementCreate"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["SettlementResponse"]>>>;
  skipObligation(options: {
    obligationId: string;
    input: components["schemas"]["ObligationAction"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  unskipObligation(options: {
    obligationId: string;
    input: components["schemas"]["ObligationAction"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  listRecurringRules(options: {
    query?: NonNullable<operations["listRecurringRules"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["RuleListResponse"]>>>;
  createRecurringRule(options: {
    input: components["schemas"]["RuleCreate"];
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  getRecurringRule(options: {
    ruleId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["RuleResponse"]>>>;
  changeRecurringRule(options: {
    ruleId: string;
    input: components["schemas"]["RuleChange"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  endRecurringRule(options: {
    ruleId: string;
    input: components["schemas"]["RuleEnd"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["MutationReference"]>>>;
  voidFixedSettlement(options: {
    settlementId: string;
    input: components["schemas"]["ObligationAction"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["SettlementResponse"]>>>;
  getCardPaymentLinks(options: {
    resourceId: operations["getCardPaymentLinks"]["parameters"]["path"]["resource_id"];
    query?: NonNullable<operations["getCardPaymentLinks"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["PaymentLinksResponse"]>>
  >;
  getAccountPaymentLinks(options: {
    resourceId: operations["getAccountPaymentLinks"]["parameters"]["path"]["resource_id"];
    query?: NonNullable<operations["getAccountPaymentLinks"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["PaymentLinksResponse"]>>
  >;
  listInsuranceCases(options: {
    query?: NonNullable<operations["listInsuranceCases"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CaseListResponse"]>>>;
  createInsuranceCase(options: {
    input: components["schemas"]["CaseInput"];
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CaseResponse"]>>>;
  getInsuranceCase(options: {
    caseId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CaseResponse"]>>>;
  updateInsuranceCase(options: {
    caseId: string;
    input: components["schemas"]["CasePatch"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CaseResponse"]>>>;
  medicalNodeSummary(options: {
    caseId: string;
    nodeId: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["NodeSummaryResponse"]>>
  >;
  insuranceCaseSummary(options: {
    caseId: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["CaseSummaryResponse"]>>
  >;
  listInsuranceClaims(options: {
    query?: NonNullable<operations["listInsuranceClaims"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ClaimListResponse"]>>>;
  createInsuranceClaim(options: {
    input: components["schemas"]["ClaimCreate"];
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ClaimResponse"]>>>;
  getInsuranceClaim(options: {
    claimId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ClaimResponse"]>>>;
  updateInsuranceClaim(options: {
    claimId: string;
    input: components["schemas"]["ClaimPatch"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ClaimResponse"]>>>;
  insuranceClaimHistory(options: {
    claimId: string;
    query?: NonNullable<operations["insuranceClaimHistory"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ClaimHistoryResponse"]>>
  >;
  listMedicalExpenses(options: {
    query?: NonNullable<operations["listMedicalExpenses"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["ExpenseListResponse"]>>
  >;
  createMedicalExpense(options: {
    input: components["schemas"]["ExpenseCreate"];
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  getMedicalExpense(options: {
    resourceId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ExpenseResponse"]>>>;
  correctMedicalExpense(options: {
    resourceId: string;
    input: components["schemas"]["ExpenseCorrection"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  medicalExpenseHistory(options: {
    resourceId: string;
    query?: NonNullable<operations["medicalExpenseHistory"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventCashHistoryResponse"]>>
  >;
  listMedicalRefunds(options: {
    resourceId: string;
    query?: NonNullable<operations["listMedicalRefunds"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["RefundListResponse"]>>>;
  createMedicalRefund(options: {
    resourceId: string;
    input: components["schemas"]["RefundCreate"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  voidMedicalExpense(options: {
    resourceId: string;
    input: components["schemas"]["EventReason"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  getMedicalRefund(options: {
    resourceId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["RefundResponse"]>>>;
  correctMedicalRefund(options: {
    resourceId: string;
    input: components["schemas"]["RefundCreate"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  medicalRefundHistory(options: {
    resourceId: string;
    query?: NonNullable<operations["medicalRefundHistory"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventCashHistoryResponse"]>>
  >;
  voidMedicalRefund(options: {
    resourceId: string;
    input: components["schemas"]["EventReason"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  getPayoutAllocation(options: {
    allocationId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["AllocationResponse"]>>>;
  linkPayoutAllocation(options: {
    allocationId: string;
    input: components["schemas"]["AllocationLinkPatch"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  payoutAllocationHistory(options: {
    allocationId: string;
    query?: NonNullable<operations["payoutAllocationHistory"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["AllocationHistoryResponse"]>>
  >;
  listInsurancePayouts(options: {
    query?: NonNullable<operations["listInsurancePayouts"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["PayoutListResponse"]>>>;
  createInsurancePayout(options: {
    input: components["schemas"]["PayoutCreate"];
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  getInsurancePayout(options: {
    resourceId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["PayoutResponse"]>>>;
  correctInsurancePayout(options: {
    resourceId: string;
    input: components["schemas"]["PayoutCorrection"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  insurancePayoutHistory(options: {
    resourceId: string;
    query?: NonNullable<operations["insurancePayoutHistory"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventCashHistoryResponse"]>>
  >;
  listInsuranceReturns(options: {
    resourceId: string;
    query?: NonNullable<operations["listInsuranceReturns"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ReturnListResponse"]>>>;
  createInsuranceReturn(options: {
    resourceId: string;
    input: components["schemas"]["ReturnCreate"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  voidInsurancePayout(options: {
    resourceId: string;
    input: components["schemas"]["EventReason"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  getInsuranceReturn(options: {
    resourceId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["ReturnResponse"]>>>;
  correctInsuranceReturn(options: {
    resourceId: string;
    input: components["schemas"]["ReturnCreate"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  insuranceReturnHistory(options: {
    resourceId: string;
    query?: NonNullable<operations["insuranceReturnHistory"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventCashHistoryResponse"]>>
  >;
  voidInsuranceReturn(options: {
    resourceId: string;
    input: components["schemas"]["EventReason"];
    ifMatch: string;
    idempotencyKey: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["EventReference"]>>>;
  insuranceCaseHistory(options: {
    caseId: string;
    query?: NonNullable<operations["insuranceCaseHistory"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["CaseHistoryResponse"]>>
  >;
  listMedicalNodes(options: {
    caseId: string;
    query?: NonNullable<operations["listMedicalNodes"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["MedicalNodeListResponse"]>>
  >;
  createMedicalNode(options: {
    caseId: string;
    input: components["schemas"]["MedicalNodeInput"];
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["MedicalNodeResponse"]>>
  >;
  deleteMedicalNode(options: {
    caseId: string;
    nodeId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<null>>>;
  getMedicalNode(options: {
    caseId: string;
    nodeId: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["MedicalNodeResponse"]>>
  >;
  updateMedicalNode(options: {
    caseId: string;
    nodeId: string;
    input: components["schemas"]["MedicalNodePatch"];
    ifMatch: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["MedicalNodeResponse"]>>
  >;
  listInsurancePolicies(options: {
    query?: NonNullable<operations["listInsurancePolicies"]["parameters"]["query"]>;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["PolicyListResponse"]>>>;
  createInsurancePolicy(options: {
    input: Omit<components["schemas"]["PolicyCreate"], "policy_number">;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["PolicyResponse"]>>>;
  getInsurancePolicy(options: {
    policyId: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["PolicyResponse"]>>>;
  updateInsurancePolicy(options: {
    policyId: string;
    input: Omit<components["schemas"]["PolicyPatch"], "policy_number">;
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["PolicyResponse"]>>>;
  listInsuranceCoverages(options: {
    policyId: string;
    query?: NonNullable<operations["listInsuranceCoverages"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["CoverageListResponse"]>>
  >;
  createInsuranceCoverage(options: {
    policyId: string;
    input: components["schemas"]["CoverageInput"];
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CoverageResponse"]>>>;
  updateInsuranceCoverage(options: {
    policyId: string;
    coverageId: string;
    input: components["schemas"]["CoveragePatch"];
    ifMatch: string;
  }): Promise<NativeAuthResult<NativeFinanceResponse<components["schemas"]["CoverageResponse"]>>>;
  listPolicyPremiumLinks(options: {
    policyId: string;
    query?: NonNullable<operations["listPolicyPremiumLinks"]["parameters"]["query"]>;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["PremiumLinkListResponse"]>>
  >;
  createPolicyPremiumLink(options: {
    policyId: string;
    input: components["schemas"]["PremiumLinkCreate"];
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["PremiumLinkResponse"]>>
  >;
  updatePolicyPremiumLink(options: {
    policyId: string;
    linkId: string;
    input: components["schemas"]["PremiumLinkPatch"];
    ifMatch: string;
  }): Promise<
    NativeAuthResult<NativeFinanceResponse<components["schemas"]["PremiumLinkResponse"]>>
  >;
  /** Number plaintext and ciphertext never appear in arguments or return values. */
  editInsurancePolicyNumberUI(options: {
    policyId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<{ status: "saved" | "deleted" | "cancelled" }>>;
  showInsurancePolicyNumberUI(options: {
    policyId: string;
  }): Promise<NativeAuthResult<{ status: "completed" | "cancelled" }>>;
  editAccountNumberUI(options: {
    accountId: string;
    ifMatch: string;
  }): Promise<NativeAuthResult<{ status: "saved" | "deleted" | "cancelled" }>>;
  showAccountNumberUI(options: {
    accountId: string;
  }): Promise<NativeAuthResult<{ status: "completed" | "cancelled" }>>;
  showAccountNumberWithPasskeyUI(options: {
    accountId: string;
  }): Promise<NativeAuthResult<{ status: "completed" | "cancelled" }>>;
  logout(): Promise<NativeAuthResult<{ status: "signedOut"; serverRevoked: boolean }>>;
  request(
    options: NativeMetadataRequest,
  ): Promise<NativeAuthResult<{ status: number; body: NativeJson }>>;
}
