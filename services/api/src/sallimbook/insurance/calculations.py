"""Aggregate actual sources, never claim joins or explanatory receipt lines.

All records passed here must already belong to the authorized household. The
caller supplies a complete source graph for the requested calculation. This
module does not select reporting periods, persist records, or prove atomicity.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sallimbook.core.types import krw_string
from sallimbook.insurance.schemas import BenefitType

type Money = int | Decimal


def _positive(value: Money) -> int:
    amount = int(krw_string(value))
    if amount <= 0:
        raise ValueError("Actual cash and allocation amounts must be positive")
    return amount


def _ids(*values: str):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("Source and relation IDs must be nonempty strings")


@dataclass(frozen=True)
class MedicalPayment:
    id: str
    case_id: str
    amount_krw: Money

    def __post_init__(self):
        _ids(self.id, self.case_id)
        _positive(self.amount_krw)


@dataclass(frozen=True)
class MedicalRefund:
    id: str
    payment_id: str
    amount_krw: Money

    def __post_init__(self):
        _ids(self.id, self.payment_id)
        _positive(self.amount_krw)


@dataclass(frozen=True)
class Allocation:
    id: str
    case_id: str
    amount_krw: Money
    benefit_type: BenefitType
    claim_id: str | None = None

    def __post_init__(self):
        _ids(self.id, self.case_id)
        _positive(self.amount_krw)
        if self.claim_id is not None:
            _ids(self.claim_id)
        if self.benefit_type not in {"reimbursement", "fixed", "other"}:
            raise ValueError("Unknown benefit type")


@dataclass(frozen=True)
class Payout:
    id: str
    amount_krw: Money
    allocations: tuple[Allocation, ...]

    def __post_init__(self):
        _ids(self.id)
        amount = _positive(self.amount_krw)
        object.__setattr__(self, "allocations", tuple(self.allocations))
        if not all(isinstance(row, Allocation) for row in self.allocations):
            raise ValueError("Payouts require typed allocations")
        if len({row.id for row in self.allocations}) != len(self.allocations):
            raise ValueError("An allocation cannot be repeated in a payout")
        if sum(_positive(row.amount_krw) for row in self.allocations) != amount:
            raise ValueError("Allocation total must equal the actual receipt")


@dataclass(frozen=True)
class InsuranceReturn:
    id: str
    payout_id: str
    allocation_id: str
    amount_krw: Money

    def __post_init__(self):
        _ids(self.id, self.payout_id, self.allocation_id)
        _positive(self.amount_krw)


def _unique[T](records: Iterable[T], record_type: type[T]) -> dict[str, T]:
    sources = {}
    for record in records:
        if not isinstance(record, record_type):
            raise ValueError("Typed source records are required")
        previous = sources.get(record.id)
        if previous is not None and previous != record:
            raise ValueError("Conflicting data for a repeated source ID")
        sources[record.id] = record
    return sources


@dataclass(frozen=True)
class CaseBalance:
    medical_paid_krw: int
    medical_refunded_krw: int
    net_medical_krw: int
    insurance_received_krw: int
    insurance_returned_krw: int
    net_received_krw: int
    net_burden_krw: int
    net_reimbursement_krw: int
    net_fixed_krw: int
    net_other_krw: int


@dataclass(frozen=True)
class InsuranceSummary:
    cases: dict[str, CaseBalance]
    actual_receipts_krw: int
    actual_returns_krw: int
    net_receipts_krw: int


def insurance_summary(
    payments: Iterable[MedicalPayment],
    payouts: Iterable[Payout],
    *,
    refunds: Iterable[MedicalRefund] = (),
    returns: Iterable[InsuranceReturn] = (),
) -> InsuranceSummary:
    """Deduplicate original IDs and total costs and allocations separately.

    Identical projected sources count once; conflicting copies are errors. This
    is aggregation deduplication, not an implementation of write idempotency.
    Claim links and receipt detail lines are intentionally not monetary inputs.
    """
    payment_sources = _unique(payments, MedicalPayment)
    payout_sources = _unique(payouts, Payout)
    refund_sources = _unique(refunds, MedicalRefund)
    return_sources = _unique(returns, InsuranceReturn)
    balances: dict[str, dict[str, int]] = {}

    def case(case_id: str) -> dict[str, int]:
        return balances.setdefault(
            case_id,
            {
                "paid": 0,
                "refunded": 0,
                "received": 0,
                "returned": 0,
                "reimbursement": 0,
                "fixed": 0,
                "other": 0,
            },
        )

    for payment in payment_sources.values():
        case(payment.case_id)["paid"] += _positive(payment.amount_krw)
    refunded_by_payment: dict[str, int] = {}
    for refund in refund_sources.values():
        payment = payment_sources.get(refund.payment_id)
        if payment is None:
            raise ValueError("Refund references an unknown medical payment")
        amount = _positive(refund.amount_krw)
        refunded_by_payment[payment.id] = refunded_by_payment.get(payment.id, 0) + amount
        if refunded_by_payment[payment.id] > _positive(payment.amount_krw):
            raise ValueError("Cumulative medical refunds exceed the original payment")
        case(payment.case_id)["refunded"] += amount

    allocations: dict[str, tuple[str, Allocation]] = {}
    for payout in payout_sources.values():
        for allocation in payout.allocations:
            if allocation.id in allocations:
                raise ValueError("An allocation ID belongs to exactly one payout")
            allocations[allocation.id] = (payout.id, allocation)
            amount = _positive(allocation.amount_krw)
            case(allocation.case_id)["received"] += amount
            case(allocation.case_id)[allocation.benefit_type] += amount
    returned_by_allocation: dict[str, int] = {}
    for returned in return_sources.values():
        original = allocations.get(returned.allocation_id)
        if original is None or original[0] != returned.payout_id:
            raise ValueError("Return must reference its original payout and allocation")
        allocation = original[1]
        amount = _positive(returned.amount_krw)
        total = returned_by_allocation.get(allocation.id, 0) + amount
        if total > _positive(allocation.amount_krw):
            raise ValueError("Cumulative returns exceed the original allocation")
        returned_by_allocation[allocation.id] = total
        case(allocation.case_id)["returned"] += amount
        case(allocation.case_id)[allocation.benefit_type] -= amount

    cases = {}
    for case_id, values in balances.items():
        medical = values["paid"] - values["refunded"]
        received = values["received"] - values["returned"]
        result = [
            values["paid"],
            values["refunded"],
            medical,
            values["received"],
            values["returned"],
            received,
            medical - received,
            values["reimbursement"],
            values["fixed"],
            values["other"],
        ]
        cases[case_id] = CaseBalance(*(int(krw_string(value)) for value in result))
    receipts = sum(_positive(p.amount_krw) for p in payout_sources.values())
    returned = sum(_positive(r.amount_krw) for r in return_sources.values())
    return InsuranceSummary(
        cases,
        int(krw_string(receipts)),
        int(krw_string(returned)),
        int(krw_string(receipts - returned)),
    )
