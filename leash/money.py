"""Money as whole minor units.

No float ever touches an amount in this codebase. Every amount is an integer
count of the currency's minor unit and carries its currency with it, so adding
INR to USD raises instead of quietly producing a number that looks fine.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Final, Iterable

# Currencies whose minor unit is not 1/100. Everything else gets the default.
_EXPONENTS: Final[dict[str, int]] = {
    "BHD": 3,
    "CLP": 0,
    "ISK": 0,
    "JOD": 3,
    "JPY": 0,
    "KRW": 0,
    "KWD": 3,
    "OMR": 3,
    "TND": 3,
    "VND": 0,
}
_DEFAULT_EXPONENT: Final[int] = 2


def exponent(currency: str) -> int:
    """Number of decimal places in `currency`."""
    return _EXPONENTS.get(currency.upper(), _DEFAULT_EXPONENT)


class CurrencyMismatch(ValueError):
    """Two amounts in different currencies met."""


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount. `minor` is paise, cents, fils, whatever the unit is."""

    minor: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.minor, bool) or not isinstance(self.minor, int):
            raise TypeError("minor must be a whole number of minor units")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError(f"not an ISO-4217 code: {self.currency!r}")
        object.__setattr__(self, "currency", self.currency.upper())

    # -- construction ----------------------------------------------------

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(0, currency)

    @classmethod
    def from_major(cls, amount: Decimal | int | str, currency: str) -> "Money":
        """Build from a human-facing amount: `Money.from_major("49.99", "USD")`.

        Rounds half-up at the currency's precision, which is what a person
        reading a price expects and what the processor will do anyway.
        """
        scale = Decimal(10) ** exponent(currency)
        quantised = (Decimal(str(amount)) * scale).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
        return cls(int(quantised), currency)

    @classmethod
    def sum(cls, amounts: Iterable["Money"], currency: str) -> "Money":
        """Total of `amounts`, with `currency` fixing the result of an empty sum."""
        total = cls.zero(currency)
        for amount in amounts:
            total = total + amount
        return total

    # -- arithmetic ------------------------------------------------------

    def _same(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency} and {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.minor - other.minor, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.minor, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._same(other)
        return self.minor < other.minor

    def __le__(self, other: "Money") -> bool:
        self._same(other)
        return self.minor <= other.minor

    def __gt__(self, other: "Money") -> bool:
        self._same(other)
        return self.minor > other.minor

    def __ge__(self, other: "Money") -> bool:
        self._same(other)
        return self.minor >= other.minor

    # -- presentation ----------------------------------------------------

    @property
    def major(self) -> Decimal:
        """The amount as a decimal, for display and for JSON."""
        return Decimal(self.minor).scaleb(-exponent(self.currency))

    def clamped(self) -> "Money":
        """This amount, or zero if it is negative. Headroom is never negative."""
        return self if self.minor > 0 else Money.zero(self.currency)

    def __str__(self) -> str:
        return f"{self.major:.{exponent(self.currency)}f} {self.currency}"

    def __repr__(self) -> str:
        return f"Money({self.minor!r}, {self.currency!r})"
