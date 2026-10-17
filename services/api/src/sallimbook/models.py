"""Explicit model registry for migrations; no dynamic import of arbitrary modules."""

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.models import Asset
from sallimbook.assets.month_models import AssetMonthRecord, AssetMonthRevision, AssetMonthValue
from sallimbook.cards.models import Card
from sallimbook.cashflow.models import CashRecord, CashRecordRevision, IncomeConversion
from sallimbook.core.audit import AuditEvent
from sallimbook.core.idempotency import IdempotencyRecord
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

__all__ = [
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
    "FinancialAccount",
    "Household",
    "HouseholdMember",
    "IncomeConversion",
    "IdempotencyRecord",
    "Invitation",
    "LoginThrottle",
    "RefreshToken",
    "RegisteredDevice",
    "StepUpGrant",
    "User",
]
