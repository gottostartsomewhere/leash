"""Leash: scoped, revocable, auditable spending authority for AI agents."""

from .engine import CHECKS, Context, Decision, evaluate
from .ledger import IllegalTransition, Ledger, LedgerError, OverCapture, UnknownCharge
from .models import (
    Attempt,
    Charge,
    ChargeState,
    CheckCode,
    CheckResult,
    Mandate,
    MandateStatus,
    Outcome,
    PayeeDirectory,
    Severity,
    Velocity,
    Verdict,
)
from .money import CurrencyMismatch, Money

__all__ = [
    "CHECKS",
    "Attempt",
    "Charge",
    "ChargeState",
    "CheckCode",
    "CheckResult",
    "Context",
    "CurrencyMismatch",
    "Decision",
    "IllegalTransition",
    "Ledger",
    "LedgerError",
    "Mandate",
    "MandateStatus",
    "Money",
    "Outcome",
    "OverCapture",
    "PayeeDirectory",
    "Severity",
    "UnknownCharge",
    "Velocity",
    "Verdict",
    "evaluate",
]
