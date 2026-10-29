from __future__ import annotations

from decimal import Decimal

import pytest

from leash.money import CurrencyMismatch, Money, exponent


def test_major_amounts_round_half_up_at_the_currency_precision():
    assert Money.from_major("49.995", "USD").minor == 5000
    assert Money.from_major("49.994", "USD").minor == 4999


def test_a_currency_with_no_minor_unit_keeps_whole_numbers():
    assert exponent("JPY") == 0
    assert Money.from_major(1500, "JPY").minor == 1500
    assert str(Money(1500, "JPY")) == "1500 JPY"


def test_a_three_decimal_currency_is_handled():
    assert Money.from_major("1.234", "KWD").minor == 1234


def test_currencies_do_not_mix():
    with pytest.raises(CurrencyMismatch):
        Money(100, "USD") + Money(100, "INR")

    with pytest.raises(CurrencyMismatch):
        Money(100, "USD") < Money(100, "INR")


def test_comparing_money_to_a_bare_number_is_an_error():
    with pytest.raises(TypeError):
        Money(100, "USD") + 100


def test_codes_are_normalised():
    assert Money(100, "usd").currency == "USD"


def test_a_bad_code_is_rejected():
    with pytest.raises(ValueError):
        Money(100, "DOLLARS")


def test_amounts_are_whole_minor_units():
    with pytest.raises(TypeError):
        Money(10.5, "USD")  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        Money(True, "USD")  # type: ignore[arg-type]


def test_an_empty_sum_still_knows_its_currency():
    assert Money.sum([], "INR") == Money(0, "INR")


def test_headroom_never_goes_negative():
    assert (Money(50, "USD") - Money(80, "USD")).clamped() == Money(0, "USD")


def test_the_major_value_is_exact():
    assert Money(4999, "USD").major == Decimal("49.99")
    assert str(Money(4999, "USD")) == "49.99 USD"
