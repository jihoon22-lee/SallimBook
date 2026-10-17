"""Explicit model registry for migrations; no dynamic import of arbitrary modules."""

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
    "AuthChallenge",
    "AuthCredential",
    "AuthSession",
    "Household",
    "HouseholdMember",
    "IdempotencyRecord",
    "Invitation",
    "LoginThrottle",
    "RefreshToken",
    "RegisteredDevice",
    "StepUpGrant",
    "User",
]
