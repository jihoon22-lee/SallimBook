"""Explicit model registry for migrations; no dynamic import of arbitrary modules."""

from sallimbook.identity.models import Household

__all__ = ["Household"]
