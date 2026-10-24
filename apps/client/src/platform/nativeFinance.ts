import type { components } from "@sallimbook/api-client";
import type {
  NativeAccountCreate,
  NativeAccountPatch,
  NativeAccountQuery,
  NativeAssetQuery,
  NativeAuthResult,
  NativeFinanceResponse,
  SallimBookAuth,
} from "../../../../plugins/sallimbook-auth/src/definitions";
import { ApiError, apiErrorCode } from "./api";
import { hasNativeAuth, nativeAuthPlugin as plugin } from "./nativeAuth";

async function invoke<T>(action: () => Promise<NativeAuthResult<T>>): Promise<T> {
  if (!hasNativeAuth()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
  let result: NativeAuthResult<T>;
  try {
    result = await action();
  } catch {
    throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
  }
  if (result.ok) return result.value;
  switch (result.code) {
    case "APP_LOCKED":
      throw new ApiError(0, "APP_LOCKED");
    case "SESSION_EXPIRED":
      throw new ApiError(401, "UNAUTHENTICATED");
    case "KEY_INVALIDATED":
      throw new ApiError(401, "NATIVE_KEY_INVALIDATED");
    case "ACCESS_DENIED":
      throw new ApiError(403, "FORBIDDEN");
    case "AUTH_CANCELLED":
      throw new ApiError(0, "REQUEST_CANCELLED");
    case "INVALID_REQUEST":
      throw new ApiError(422, "VALIDATION_ERROR");
    case "REAUTHENTICATION_REQUIRED":
      throw new ApiError(403, "REAUTHENTICATION_REQUIRED");
    case "VERSION_CONFLICT":
      throw new ApiError(409, "VERSION_CONFLICT");
    case "NETWORK_UNAVAILABLE":
      throw new ApiError(0, "NETWORK_UNAVAILABLE");
    case "PASSKEYS_DISABLED":
      throw new ApiError(0, "PASSKEYS_DISABLED");
    case "PASSKEY_REQUIRED":
      throw new ApiError(409, "PASSKEY_REQUIRED");
    case "PASSKEY_CANCELLED":
      throw new ApiError(0, "PASSKEY_CANCELLED");
    case "PASSKEY_FAILED":
      throw new ApiError(0, "PASSKEY_FAILED");
    default:
      throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
  }
}

async function metadata<T>(
  action: () => Promise<NativeAuthResult<NativeFinanceResponse<T>>>,
): Promise<T> {
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
  listHouseholdPeople: (options: Parameters<SallimBookAuth["listHouseholdPeople"]>[0]) =>
    metadata(() => plugin.listHouseholdPeople(options)),
  createHouseholdPerson: (options: Parameters<SallimBookAuth["createHouseholdPerson"]>[0]) =>
    metadata(() => plugin.createHouseholdPerson(options)),
  updateHouseholdPerson: (options: Parameters<SallimBookAuth["updateHouseholdPerson"]>[0]) =>
    metadata(() => plugin.updateHouseholdPerson(options)),

  deleteAppliance: (options: Parameters<SallimBookAuth["deleteAppliance"]>[0]) =>
    metadata(() => plugin.deleteAppliance(options)),
  deleteConsumable: (options: Parameters<SallimBookAuth["deleteConsumable"]>[0]) =>
    metadata(() => plugin.deleteConsumable(options)),
  deleteApplianceConsumable: (
    options: Parameters<SallimBookAuth["deleteApplianceConsumable"]>[0],
  ) => metadata(() => plugin.deleteApplianceConsumable(options)),
  createDocumentLink: (options: Parameters<SallimBookAuth["createDocumentLink"]>[0]) =>
    metadata(() => plugin.createDocumentLink(options)),
  endDocumentLink: (options: Parameters<SallimBookAuth["endDocumentLink"]>[0]) =>
    metadata(() => plugin.endDocumentLink(options)),
  listDocuments: (options: Parameters<SallimBookAuth["listDocuments"]>[0]) =>
    metadata(() => plugin.listDocuments(options)),
  getDocument: (options: Parameters<SallimBookAuth["getDocument"]>[0]) =>
    metadata(() => plugin.getDocument(options)),
  deleteDocument: (options: Parameters<SallimBookAuth["deleteDocument"]>[0]) =>
    metadata(() => plugin.deleteDocument(options)),
  listDocumentLinks: (options: Parameters<SallimBookAuth["listDocumentLinks"]>[0]) =>
    metadata(() => plugin.listDocumentLinks(options)),
  uploadDocument: (options: Parameters<SallimBookAuth["uploadDocumentUI"]>[0]) =>
    invoke(() => plugin.uploadDocumentUI(options)),
  downloadDocument: (options: Parameters<SallimBookAuth["downloadDocumentUI"]>[0]) =>
    invoke(() => plugin.downloadDocumentUI(options)),
  listApplianceConsumables: (options: Parameters<SallimBookAuth["listApplianceConsumables"]>[0]) =>
    metadata(() => plugin.listApplianceConsumables(options)),
  createApplianceConsumable: (
    options: Parameters<SallimBookAuth["createApplianceConsumable"]>[0],
  ) => metadata(() => plugin.createApplianceConsumable(options)),
  getApplianceConsumable: (options: Parameters<SallimBookAuth["getApplianceConsumable"]>[0]) =>
    metadata(() => plugin.getApplianceConsumable(options)),
  updateApplianceConsumable: (
    options: Parameters<SallimBookAuth["updateApplianceConsumable"]>[0],
  ) => metadata(() => plugin.updateApplianceConsumable(options)),
  listConsumableReplacements: (
    options: Parameters<SallimBookAuth["listConsumableReplacements"]>[0],
  ) => metadata(() => plugin.listConsumableReplacements(options)),
  createConsumableReplacement: (
    options: Parameters<SallimBookAuth["createConsumableReplacement"]>[0],
  ) => metadata(() => plugin.createConsumableReplacement(options)),
  getConsumableReplacement: (options: Parameters<SallimBookAuth["getConsumableReplacement"]>[0]) =>
    metadata(() => plugin.getConsumableReplacement(options)),
  cancelConsumableReplacement: (
    options: Parameters<SallimBookAuth["cancelConsumableReplacement"]>[0],
  ) => metadata(() => plugin.cancelConsumableReplacement(options)),
  listAppliances: (options: Parameters<SallimBookAuth["listAppliances"]>[0]) =>
    metadata(() => plugin.listAppliances(options)),
  createAppliance: (options: Parameters<SallimBookAuth["createAppliance"]>[0]) =>
    metadata(() => plugin.createAppliance(options)),
  getAppliance: (options: Parameters<SallimBookAuth["getAppliance"]>[0]) =>
    metadata(() => plugin.getAppliance(options)),
  updateAppliance: (options: Parameters<SallimBookAuth["updateAppliance"]>[0]) =>
    metadata(() => plugin.updateAppliance(options)),
  listConsumables: (options: Parameters<SallimBookAuth["listConsumables"]>[0]) =>
    metadata(() => plugin.listConsumables(options)),
  createConsumable: (options: Parameters<SallimBookAuth["createConsumable"]>[0]) =>
    metadata(() => plugin.createConsumable(options)),
  getConsumable: (options: Parameters<SallimBookAuth["getConsumable"]>[0]) =>
    metadata(() => plugin.getConsumable(options)),
  updateConsumable: (options: Parameters<SallimBookAuth["updateConsumable"]>[0]) =>
    metadata(() => plugin.updateConsumable(options)),
  listStockMovements: (options: Parameters<SallimBookAuth["listStockMovements"]>[0]) =>
    metadata(() => plugin.listStockMovements(options)),
  createStockMovement: (options: Parameters<SallimBookAuth["createStockMovement"]>[0]) =>
    metadata(() => plugin.createStockMovement(options)),
  getStockMovement: (options: Parameters<SallimBookAuth["getStockMovement"]>[0]) =>
    metadata(() => plugin.getStockMovement(options)),
  cancelStockMovement: (options: Parameters<SallimBookAuth["cancelStockMovement"]>[0]) =>
    metadata(() => plugin.cancelStockMovement(options)),
  getHomecareStatus: (options: Parameters<SallimBookAuth["getHomecareStatus"]>[0]) =>
    metadata(() => plugin.getHomecareStatus(options)),
  listAssets: (query: NativeAssetQuery = {}) => metadata(() => plugin.listAssets({ query })),
  getAsset: (assetId: string) => metadata(() => plugin.getAsset({ assetId })),
  createAsset: (input: components["schemas"]["AssetCreate"]) =>
    metadata(() => plugin.createAsset({ input })),
  updateAsset: (assetId: string, input: components["schemas"]["AssetPatch"], ifMatch: string) =>
    metadata(() => plugin.updateAsset({ assetId, input, ifMatch })),
  archiveAsset: (assetId: string, input: components["schemas"]["AssetArchive"], ifMatch: string) =>
    metadata(() => plugin.archiveAsset({ assetId, input, ifMatch })),
  deleteAsset: (assetId: string, ifMatch: string) =>
    metadata(() => plugin.deleteAsset({ assetId, ifMatch })),
  listAccounts: (query: NativeAccountQuery = {}) => metadata(() => plugin.listAccounts({ query })),
  getAccount: (accountId: string) => metadata(() => plugin.getAccount({ accountId })),
  createAccount: (input: NativeAccountCreate) => {
    metadataOnly(input);
    return metadata(() => plugin.createAccount({ input }));
  },
  updateAccount: (accountId: string, input: NativeAccountPatch, ifMatch: string) => {
    metadataOnly(input);
    return metadata(() => plugin.updateAccount({ accountId, input, ifMatch }));
  },
  deleteAccount: (accountId: string, ifMatch: string) =>
    metadata(() => plugin.deleteAccount({ accountId, ifMatch })),
  getAssetMonth: (options: Parameters<SallimBookAuth["getAssetMonth"]>[0]) =>
    metadata(() => plugin.getAssetMonth(options)),
  getAssetMonthRevision: (options: Parameters<SallimBookAuth["getAssetMonthRevision"]>[0]) =>
    metadata(() => plugin.getAssetMonthRevision(options)),
  listAssetMonthRevisions: (options: Parameters<SallimBookAuth["listAssetMonthRevisions"]>[0]) =>
    metadata(() => plugin.listAssetMonthRevisions(options)),
  createAssetMonthDraft: (options: Parameters<SallimBookAuth["createAssetMonthDraft"]>[0]) =>
    metadata(() => plugin.createAssetMonthDraft(options)),
  updateAssetMonthValue: (options: Parameters<SallimBookAuth["updateAssetMonthValue"]>[0]) =>
    metadata(() => plugin.updateAssetMonthValue(options)),
  synchronizeAssetMonthScope: (
    options: Parameters<SallimBookAuth["synchronizeAssetMonthScope"]>[0],
  ) => metadata(() => plugin.synchronizeAssetMonthScope(options)),
  confirmAssetMonth: (options: Parameters<SallimBookAuth["confirmAssetMonth"]>[0]) =>
    metadata(() => plugin.confirmAssetMonth(options)),
  reopenAssetMonth: (options: Parameters<SallimBookAuth["reopenAssetMonth"]>[0]) =>
    metadata(() => plugin.reopenAssetMonth(options)),
  carryPreviousAssetMonth: (options: Parameters<SallimBookAuth["carryPreviousAssetMonth"]>[0]) =>
    metadata(() => plugin.carryPreviousAssetMonth(options)),
  listIncome: (options: Parameters<SallimBookAuth["listIncome"]>[0]) =>
    metadata(() => plugin.listIncome(options)),
  incomeSummary: (options: Parameters<SallimBookAuth["incomeSummary"]>[0]) =>
    metadata(() => plugin.incomeSummary(options)),
  incomeDuplicateCandidates: (
    options: Parameters<SallimBookAuth["incomeDuplicateCandidates"]>[0],
  ) => metadata(() => plugin.incomeDuplicateCandidates(options)),
  getIncome: (options: Parameters<SallimBookAuth["getIncome"]>[0]) =>
    metadata(() => plugin.getIncome(options)),
  incomeHistory: (options: Parameters<SallimBookAuth["incomeHistory"]>[0]) =>
    metadata(() => plugin.incomeHistory(options)),
  createIncome: (options: Parameters<SallimBookAuth["createIncome"]>[0]) =>
    metadata(() => plugin.createIncome(options)),
  correctIncome: (options: Parameters<SallimBookAuth["correctIncome"]>[0]) =>
    metadata(() => plugin.correctIncome(options)),
  voidIncome: (options: Parameters<SallimBookAuth["voidIncome"]>[0]) =>
    metadata(() => plugin.voidIncome(options)),
  returnIncome: (options: Parameters<SallimBookAuth["returnIncome"]>[0]) =>
    metadata(() => plugin.returnIncome(options)),
  convertIncomePrecision: (options: Parameters<SallimBookAuth["convertIncomePrecision"]>[0]) =>
    metadata(() => plugin.convertIncomePrecision(options)),
  listCards: (options: Parameters<SallimBookAuth["listCards"]>[0]) =>
    metadata(() => plugin.listCards(options)),
  getCard: (options: Parameters<SallimBookAuth["getCard"]>[0]) =>
    metadata(() => plugin.getCard(options)),
  createCard: (options: Parameters<SallimBookAuth["createCard"]>[0]) =>
    metadata(() => plugin.createCard(options)),
  updateCard: (options: Parameters<SallimBookAuth["updateCard"]>[0]) =>
    metadata(() => plugin.updateCard(options)),
  archiveCard: (options: Parameters<SallimBookAuth["archiveCard"]>[0]) =>
    metadata(() => plugin.archiveCard(options)),
  deleteCard: (options: Parameters<SallimBookAuth["deleteCard"]>[0]) =>
    metadata(() => plugin.deleteCard(options)),
  getAssetComparison: (options: Parameters<SallimBookAuth["getAssetComparison"]>[0]) =>
    metadata(() => plugin.getAssetComparison(options)),
  getAssetTrends: (options: Parameters<SallimBookAuth["getAssetTrends"]>[0]) =>
    metadata(() => plugin.getAssetTrends(options)),
  listObligations: (options: Parameters<SallimBookAuth["listObligations"]>[0]) =>
    metadata(() => plugin.listObligations(options)),
  generateObligations: (options: Parameters<SallimBookAuth["generateObligations"]>[0]) =>
    metadata(() => plugin.generateObligations(options)),
  fixedCostSummary: (options: Parameters<SallimBookAuth["fixedCostSummary"]>[0]) =>
    metadata(() => plugin.fixedCostSummary(options)),
  getObligation: (options: Parameters<SallimBookAuth["getObligation"]>[0]) =>
    metadata(() => plugin.getObligation(options)),
  rescheduleObligation: (options: Parameters<SallimBookAuth["rescheduleObligation"]>[0]) =>
    metadata(() => plugin.rescheduleObligation(options)),
  completeObligation: (options: Parameters<SallimBookAuth["completeObligation"]>[0]) =>
    metadata(() => plugin.completeObligation(options)),
  obligationHistory: (options: Parameters<SallimBookAuth["obligationHistory"]>[0]) =>
    metadata(() => plugin.obligationHistory(options)),
  reopenObligation: (options: Parameters<SallimBookAuth["reopenObligation"]>[0]) =>
    metadata(() => plugin.reopenObligation(options)),
  listObligationSettlements: (
    options: Parameters<SallimBookAuth["listObligationSettlements"]>[0],
  ) => metadata(() => plugin.listObligationSettlements(options)),
  settleObligation: (options: Parameters<SallimBookAuth["settleObligation"]>[0]) =>
    metadata(() => plugin.settleObligation(options)),
  skipObligation: (options: Parameters<SallimBookAuth["skipObligation"]>[0]) =>
    metadata(() => plugin.skipObligation(options)),
  unskipObligation: (options: Parameters<SallimBookAuth["unskipObligation"]>[0]) =>
    metadata(() => plugin.unskipObligation(options)),
  listRecurringRules: (options: Parameters<SallimBookAuth["listRecurringRules"]>[0]) =>
    metadata(() => plugin.listRecurringRules(options)),
  createRecurringRule: (options: Parameters<SallimBookAuth["createRecurringRule"]>[0]) =>
    metadata(() => plugin.createRecurringRule(options)),
  getRecurringRule: (options: Parameters<SallimBookAuth["getRecurringRule"]>[0]) =>
    metadata(() => plugin.getRecurringRule(options)),
  changeRecurringRule: (options: Parameters<SallimBookAuth["changeRecurringRule"]>[0]) =>
    metadata(() => plugin.changeRecurringRule(options)),
  endRecurringRule: (options: Parameters<SallimBookAuth["endRecurringRule"]>[0]) =>
    metadata(() => plugin.endRecurringRule(options)),
  deleteRecurringRule: (options: Parameters<SallimBookAuth["deleteRecurringRule"]>[0]) =>
    metadata(() => plugin.deleteRecurringRule(options)),
  voidFixedSettlement: (options: Parameters<SallimBookAuth["voidFixedSettlement"]>[0]) =>
    metadata(() => plugin.voidFixedSettlement(options)),
  getCardPaymentLinks: (options: Parameters<SallimBookAuth["getCardPaymentLinks"]>[0]) =>
    metadata(() => plugin.getCardPaymentLinks(options)),
  getAccountPaymentLinks: (options: Parameters<SallimBookAuth["getAccountPaymentLinks"]>[0]) =>
    metadata(() => plugin.getAccountPaymentLinks(options)),
  listInsuranceCases: (options: Parameters<SallimBookAuth["listInsuranceCases"]>[0]) =>
    metadata(() => plugin.listInsuranceCases(options)),
  createInsuranceCase: (options: Parameters<SallimBookAuth["createInsuranceCase"]>[0]) =>
    metadata(() => plugin.createInsuranceCase(options)),
  getInsuranceCase: (options: Parameters<SallimBookAuth["getInsuranceCase"]>[0]) =>
    metadata(() => plugin.getInsuranceCase(options)),
  updateInsuranceCase: (options: Parameters<SallimBookAuth["updateInsuranceCase"]>[0]) =>
    metadata(() => plugin.updateInsuranceCase(options)),
  medicalNodeSummary: (options: Parameters<SallimBookAuth["medicalNodeSummary"]>[0]) =>
    metadata(() => plugin.medicalNodeSummary(options)),
  insuranceCaseSummary: (options: Parameters<SallimBookAuth["insuranceCaseSummary"]>[0]) =>
    metadata(() => plugin.insuranceCaseSummary(options)),
  listInsuranceClaims: (options: Parameters<SallimBookAuth["listInsuranceClaims"]>[0]) =>
    metadata(() => plugin.listInsuranceClaims(options)),
  createInsuranceClaim: (options: Parameters<SallimBookAuth["createInsuranceClaim"]>[0]) =>
    metadata(() => plugin.createInsuranceClaim(options)),
  getInsuranceClaim: (options: Parameters<SallimBookAuth["getInsuranceClaim"]>[0]) =>
    metadata(() => plugin.getInsuranceClaim(options)),
  updateInsuranceClaim: (options: Parameters<SallimBookAuth["updateInsuranceClaim"]>[0]) =>
    metadata(() => plugin.updateInsuranceClaim(options)),
  insuranceClaimHistory: (options: Parameters<SallimBookAuth["insuranceClaimHistory"]>[0]) =>
    metadata(() => plugin.insuranceClaimHistory(options)),
  listMedicalExpenses: (options: Parameters<SallimBookAuth["listMedicalExpenses"]>[0]) =>
    metadata(() => plugin.listMedicalExpenses(options)),
  createMedicalExpense: (options: Parameters<SallimBookAuth["createMedicalExpense"]>[0]) =>
    metadata(() => plugin.createMedicalExpense(options)),
  getMedicalExpense: (options: Parameters<SallimBookAuth["getMedicalExpense"]>[0]) =>
    metadata(() => plugin.getMedicalExpense(options)),
  correctMedicalExpense: (options: Parameters<SallimBookAuth["correctMedicalExpense"]>[0]) =>
    metadata(() => plugin.correctMedicalExpense(options)),
  medicalExpenseHistory: (options: Parameters<SallimBookAuth["medicalExpenseHistory"]>[0]) =>
    metadata(() => plugin.medicalExpenseHistory(options)),
  listMedicalRefunds: (options: Parameters<SallimBookAuth["listMedicalRefunds"]>[0]) =>
    metadata(() => plugin.listMedicalRefunds(options)),
  createMedicalRefund: (options: Parameters<SallimBookAuth["createMedicalRefund"]>[0]) =>
    metadata(() => plugin.createMedicalRefund(options)),
  voidMedicalExpense: (options: Parameters<SallimBookAuth["voidMedicalExpense"]>[0]) =>
    metadata(() => plugin.voidMedicalExpense(options)),
  getMedicalRefund: (options: Parameters<SallimBookAuth["getMedicalRefund"]>[0]) =>
    metadata(() => plugin.getMedicalRefund(options)),
  correctMedicalRefund: (options: Parameters<SallimBookAuth["correctMedicalRefund"]>[0]) =>
    metadata(() => plugin.correctMedicalRefund(options)),
  medicalRefundHistory: (options: Parameters<SallimBookAuth["medicalRefundHistory"]>[0]) =>
    metadata(() => plugin.medicalRefundHistory(options)),
  voidMedicalRefund: (options: Parameters<SallimBookAuth["voidMedicalRefund"]>[0]) =>
    metadata(() => plugin.voidMedicalRefund(options)),
  getPayoutAllocation: (options: Parameters<SallimBookAuth["getPayoutAllocation"]>[0]) =>
    metadata(() => plugin.getPayoutAllocation(options)),
  linkPayoutAllocation: (options: Parameters<SallimBookAuth["linkPayoutAllocation"]>[0]) =>
    metadata(() => plugin.linkPayoutAllocation(options)),
  payoutAllocationHistory: (options: Parameters<SallimBookAuth["payoutAllocationHistory"]>[0]) =>
    metadata(() => plugin.payoutAllocationHistory(options)),
  listInsurancePayouts: (options: Parameters<SallimBookAuth["listInsurancePayouts"]>[0]) =>
    metadata(() => plugin.listInsurancePayouts(options)),
  createInsurancePayout: (options: Parameters<SallimBookAuth["createInsurancePayout"]>[0]) =>
    metadata(() => plugin.createInsurancePayout(options)),
  getInsurancePayout: (options: Parameters<SallimBookAuth["getInsurancePayout"]>[0]) =>
    metadata(() => plugin.getInsurancePayout(options)),
  correctInsurancePayout: (options: Parameters<SallimBookAuth["correctInsurancePayout"]>[0]) =>
    metadata(() => plugin.correctInsurancePayout(options)),
  insurancePayoutHistory: (options: Parameters<SallimBookAuth["insurancePayoutHistory"]>[0]) =>
    metadata(() => plugin.insurancePayoutHistory(options)),
  listInsuranceReturns: (options: Parameters<SallimBookAuth["listInsuranceReturns"]>[0]) =>
    metadata(() => plugin.listInsuranceReturns(options)),
  createInsuranceReturn: (options: Parameters<SallimBookAuth["createInsuranceReturn"]>[0]) =>
    metadata(() => plugin.createInsuranceReturn(options)),
  voidInsurancePayout: (options: Parameters<SallimBookAuth["voidInsurancePayout"]>[0]) =>
    metadata(() => plugin.voidInsurancePayout(options)),
  getInsuranceReturn: (options: Parameters<SallimBookAuth["getInsuranceReturn"]>[0]) =>
    metadata(() => plugin.getInsuranceReturn(options)),
  correctInsuranceReturn: (options: Parameters<SallimBookAuth["correctInsuranceReturn"]>[0]) =>
    metadata(() => plugin.correctInsuranceReturn(options)),
  insuranceReturnHistory: (options: Parameters<SallimBookAuth["insuranceReturnHistory"]>[0]) =>
    metadata(() => plugin.insuranceReturnHistory(options)),
  voidInsuranceReturn: (options: Parameters<SallimBookAuth["voidInsuranceReturn"]>[0]) =>
    metadata(() => plugin.voidInsuranceReturn(options)),
  insuranceCaseHistory: (options: Parameters<SallimBookAuth["insuranceCaseHistory"]>[0]) =>
    metadata(() => plugin.insuranceCaseHistory(options)),
  listMedicalNodes: (options: Parameters<SallimBookAuth["listMedicalNodes"]>[0]) =>
    metadata(() => plugin.listMedicalNodes(options)),
  createMedicalNode: (options: Parameters<SallimBookAuth["createMedicalNode"]>[0]) =>
    metadata(() => plugin.createMedicalNode(options)),
  deleteInsuranceCase: (options: Parameters<SallimBookAuth["deleteInsuranceCase"]>[0]) =>
    metadata(() => plugin.deleteInsuranceCase(options)),
  deleteInsurancePolicy: (options: Parameters<SallimBookAuth["deleteInsurancePolicy"]>[0]) =>
    metadata(() => plugin.deleteInsurancePolicy(options)),
  deleteMedicalNode: (options: Parameters<SallimBookAuth["deleteMedicalNode"]>[0]) =>
    metadata(() => plugin.deleteMedicalNode(options)),
  getMedicalNode: (options: Parameters<SallimBookAuth["getMedicalNode"]>[0]) =>
    metadata(() => plugin.getMedicalNode(options)),
  updateMedicalNode: (options: Parameters<SallimBookAuth["updateMedicalNode"]>[0]) =>
    metadata(() => plugin.updateMedicalNode(options)),
  listInsurancePolicies: (options: Parameters<SallimBookAuth["listInsurancePolicies"]>[0]) =>
    metadata(() => plugin.listInsurancePolicies(options)),
  createInsurancePolicy: (options: Parameters<SallimBookAuth["createInsurancePolicy"]>[0]) => {
    if (Object.hasOwn(options.input, "policy_number")) throw new ApiError(422, "VALIDATION_ERROR");
    return metadata(() => plugin.createInsurancePolicy(options));
  },
  getInsurancePolicy: (options: Parameters<SallimBookAuth["getInsurancePolicy"]>[0]) =>
    metadata(() => plugin.getInsurancePolicy(options)),
  updateInsurancePolicy: (options: Parameters<SallimBookAuth["updateInsurancePolicy"]>[0]) => {
    if (Object.hasOwn(options.input, "policy_number")) throw new ApiError(422, "VALIDATION_ERROR");
    return metadata(() => plugin.updateInsurancePolicy(options));
  },
  listInsuranceCoverages: (options: Parameters<SallimBookAuth["listInsuranceCoverages"]>[0]) =>
    metadata(() => plugin.listInsuranceCoverages(options)),
  createInsuranceCoverage: (options: Parameters<SallimBookAuth["createInsuranceCoverage"]>[0]) =>
    metadata(() => plugin.createInsuranceCoverage(options)),
  updateInsuranceCoverage: (options: Parameters<SallimBookAuth["updateInsuranceCoverage"]>[0]) =>
    metadata(() => plugin.updateInsuranceCoverage(options)),
  listPolicyPremiumLinks: (options: Parameters<SallimBookAuth["listPolicyPremiumLinks"]>[0]) =>
    metadata(() => plugin.listPolicyPremiumLinks(options)),
  createPolicyPremiumLink: (options: Parameters<SallimBookAuth["createPolicyPremiumLink"]>[0]) =>
    metadata(() => plugin.createPolicyPremiumLink(options)),
  updatePolicyPremiumLink: (options: Parameters<SallimBookAuth["updatePolicyPremiumLink"]>[0]) =>
    metadata(() => plugin.updatePolicyPremiumLink(options)),
  editInsurancePolicyNumber: (options: { policyId: string; ifMatch: string }) =>
    invoke(() => plugin.editInsurancePolicyNumberUI(options)),
  showInsurancePolicyNumber: (options: { policyId: string }) =>
    invoke(() => plugin.showInsurancePolicyNumberUI(options)),
  editAccountNumber: (options: { accountId: string; ifMatch: string }) =>
    invoke(() => plugin.editAccountNumberUI(options)),
  showAccountNumber: (options: { accountId: string }) =>
    invoke(() => plugin.showAccountNumberUI(options)),
  showAccountNumberWithPasskey: (options: { accountId: string }) =>
    invoke(() => plugin.showAccountNumberWithPasskeyUI(options)),
};
