"""Explicit model registry for migrations; no dynamic import of arbitrary modules."""

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.models import Asset
from sallimbook.assets.month_models import AssetMonthRecord, AssetMonthRevision, AssetMonthValue
from sallimbook.cards.models import Card
from sallimbook.cashflow.models import CashRecord, CashRecordRevision, IncomeConversion
from sallimbook.cashflow.recurring_models import (
    FixedSettlement,
    ObligationGeneration,
    ObligationGenerationItem,
    ObligationRevision,
    RecurringRule,
    RecurringRuleVersion,
    ScheduledObligation,
)
from sallimbook.core.audit import AuditEvent
from sallimbook.core.idempotency import IdempotencyRecord
from sallimbook.documents.models import Document, DocumentLink, DocumentStorageReservation
from sallimbook.homecare.models import (
    Appliance,
    ApplianceConsumable,
    Consumable,
    ConsumableReplacement,
    StockMovement,
)
from sallimbook.identity.auth_models import (
    AuthSession,
    HouseholdMember,
    Invitation,
    LoginThrottle,
    RefreshToken,
    RegisteredDevice,
    User,
)
from sallimbook.identity.models import Household
from sallimbook.identity.passkeys.models import AuthChallenge, AuthCredential, StepUpGrant
from sallimbook.identity.people_models import HouseholdPerson
from sallimbook.insurance.event_models import (
    ClaimExpense,
    ClaimRevisionExpense,
    InsuranceClaim,
    InsuranceClaimRevision,
    InsurancePayout,
    InsuranceReturn,
    MedicalExpense,
    MedicalExpenseLine,
    MedicalRefund,
    PayoutAllocation,
    PayoutAllocationRevision,
)
from sallimbook.insurance.models import (
    InsuranceCase,
    InsuranceCaseRevision,
    InsuranceCoverage,
    InsurancePolicy,
    MedicalNode,
    PolicyPremiumLink,
)
from sallimbook.vault.models import (
    CardSecretEnvelope,
    VaultKeyCheck,
    VaultMembership,
    VaultMemberWrapping,
    VaultNonceReservation,
    VaultRecoveryWrapping,
    VaultRotationCard,
    VaultRotationMember,
    VaultShareOffer,
    VaultState,
    VaultVersion,
)

__all__ = [
    "CardSecretEnvelope",
    "VaultKeyCheck",
    "VaultMemberWrapping",
    "VaultMembership",
    "VaultNonceReservation",
    "VaultRecoveryWrapping",
    "VaultRotationCard",
    "VaultRotationMember",
    "VaultShareOffer",
    "VaultState",
    "VaultVersion",
    "Appliance",
    "Consumable",
    "ApplianceConsumable",
    "StockMovement",
    "ConsumableReplacement",
    "MedicalExpense",
    "MedicalExpenseLine",
    "MedicalRefund",
    "InsuranceClaim",
    "ClaimExpense",
    "InsuranceClaimRevision",
    "ClaimRevisionExpense",
    "InsurancePayout",
    "PayoutAllocation",
    "PayoutAllocationRevision",
    "InsuranceReturn",
    "InsurancePolicy",
    "InsuranceCoverage",
    "PolicyPremiumLink",
    "InsuranceCase",
    "InsuranceCaseRevision",
    "MedicalNode",
    "Asset",
    "AssetMonthRecord",
    "AssetMonthRevision",
    "AssetMonthValue",
    "AuditEvent",
    "AuthChallenge",
    "AuthCredential",
    "AuthSession",
    "Card",
    "CashRecord",
    "CashRecordRevision",
    "Document",
    "DocumentLink",
    "DocumentStorageReservation",
    "FinancialAccount",
    "FixedSettlement",
    "Household",
    "HouseholdPerson",
    "HouseholdMember",
    "IncomeConversion",
    "IdempotencyRecord",
    "Invitation",
    "LoginThrottle",
    "ObligationGeneration",
    "ObligationGenerationItem",
    "ObligationRevision",
    "RecurringRule",
    "RecurringRuleVersion",
    "RefreshToken",
    "RegisteredDevice",
    "ScheduledObligation",
    "StepUpGrant",
    "User",
]
