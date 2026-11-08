"""A mandate, written in plain English.

The model drafts. It does not decide.

A person writes what they are willing to let an agent do, in their own
words. A model turns that into the same structured terms `POST /mandates`
takes, and lists what it had to assume and what it could not place. From
there the engine takes over: the draft goes through exactly the validation
a hand-written mandate does, is read for what it leaves open, and is
attacked by the red team, all before anyone signs it. Signing is a separate
request, made by the person, after reading all of that.

So a model that misreads "nothing over eighty" as eight hundred produces a
draft that says eight hundred in a table in front of the person who wrote
eighty, rather than a limit nobody looked at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .llm import Brain, BrainError
from .models import Mandate
from .money import Money
from .schemas import MandateIn, VelocityIn

#: The roots of the product taxonomy, as the catalogue slugs them. A mandate
#: scoped to a category the catalogue never returns refuses every real
#: product on the planet, which happened once with invented slugs, so the
#: model chooses from this list and nothing else.
CATEGORIES: tuple[str, ...] = (
    "animals-pet-supplies",
    "apparel-accessories",
    "arts-entertainment",
    "baby-toddler",
    "business-industrial",
    "cameras-optics",
    "electronics",
    "food-beverages-tobacco",
    "furniture",
    "hardware",
    "health-beauty",
    "home-garden",
    "luggage-bags",
    "media",
    "office-supplies",
    "software",
    "sporting-goods",
    "toys-games",
    "vehicles-parts",
)

DEFAULT_DAYS = 30

SYSTEM = f"""\
You turn a person's description of what an AI shopping agent may spend into \
structured terms. You do not decide anything: the person reads your draft \
and signs it or not, and a separate engine enforces it.

Answer with a single JSON object and nothing else: no comments, no prose. \
Use exactly these keys.

total: number. The most it may spend in all. Required.
per_purchase: number or null. A cap on any single purchase.
per_merchant: number or null. A cap on spending with any one merchant or shop.
categories: a list of category slugs, or null for any category.
max_purchases_per_minute: integer or null.
duration_days: number or null. How long the authority lasts.
assumptions: a list of strings. Anything you filled in that they did not say.
unclear: a list of strings. Anything they asked for that none of the keys \
above can express.

Category slugs you may use, and no others: {", ".join(CATEGORIES)}.

Rules:
- Amounts are US dollars as plain numbers: 80, not "$80".
- Never invent a limit the person did not ask for. A limit they did not
  mention is null.
- A period attached to the money is how long the authority lasts. $150 for
  the week means total 150 and duration_days 7; $500 a month means total
  500 and duration_days 30; a fortnight is 14 days.
- Map a thing they name to a slug only when it obviously belongs there
  (chairs are furniture, printer paper is office-supplies), and say so in
  assumptions. Otherwise put it in unclear.
- Categories are the finest scope there is. An exclusion inside a category,
  such as no alcohol within groceries, cannot be enforced. Put it in
  unclear, never in assumptions, because an assumption reads as a rule that
  will be enforced.
- Keep each assumption and each unclear item to one short sentence.\
"""


class DraftError(ValueError):
    """The words could not be turned into a mandate."""


class ModelUnavailable(DraftError):
    """The model could not be asked. Not the person's words: a 502, not a 422."""


@dataclass(frozen=True, slots=True)
class Draft:
    body: MandateIn
    assumptions: tuple[str, ...]
    unclear: tuple[str, ...]
    drafted_by: str


def _amount(reply: Mapping[str, Any], key: str) -> Decimal | None:
    value = reply.get(key)
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except InvalidOperation as exc:
        raise DraftError(f"{key} is not an amount: {value!r}") from exc
    if amount <= 0:
        raise DraftError(f"{key} has to be more than zero")
    return amount.quantize(Decimal("0.01"))


def _lines(reply: Mapping[str, Any], key: str) -> list[str]:
    raw = reply.get(key) or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip()[:200] for x in raw if str(x).strip()][:8]


async def draft(text: str, brain: Brain, *, agent_id: str = "agent_procurement") -> Draft:
    """Ask the model for terms, then hold its answer to the same rules as a person's."""
    # Twice, because a model in JSON mode now and then produces something the
    # provider rejects as invalid JSON, which deserves one more try before it
    # becomes an error in front of the person.
    reply: Mapping[str, Any] | None = None
    for attempt in range(2):
        try:
            reply = await brain.think(system=SYSTEM, user=text.strip())
            break
        except BrainError as exc:
            if attempt == 1:
                raise ModelUnavailable(f"the model could not be reached: {exc}") from exc
    assert reply is not None

    total = _amount(reply, "total")
    if total is None:
        raise DraftError("the draft has no total. Say how much it may spend in all.")

    assumptions = _lines(reply, "assumptions")
    unclear = _lines(reply, "unclear")

    categories: list[str] | None = None
    asked = reply.get("categories")
    if isinstance(asked, list) and asked:
        known = [str(c).strip().lower() for c in asked if str(c).strip().lower() in CATEGORIES]
        strays = [str(c) for c in asked if str(c).strip().lower() not in CATEGORIES]
        for stray in strays:
            unclear.append(f"{stray!r} is not a category the catalogue uses, so it was left out.")
        categories = sorted(set(known)) or None

    days = reply.get("duration_days")
    try:
        days = float(days) if days not in (None, "") else None
    except (TypeError, ValueError):
        days = None
    if days is None or days <= 0:
        days = DEFAULT_DAYS
        assumptions.append(f"No end date was given, so it lasts {DEFAULT_DAYS} days.")

    pace = reply.get("max_purchases_per_minute")
    try:
        pace = int(pace) if pace not in (None, "") else None
    except (TypeError, ValueError):
        pace = None

    try:
        body = MandateIn(
            agent_id=agent_id,
            total_limit=total,
            currency="USD",
            duration_hours=days * 24,
            per_item_limit=_amount(reply, "per_purchase"),
            per_payee_limit=_amount(reply, "per_merchant"),
            allowed_categories=categories,
            velocity=VelocityIn(window_seconds=60, max_count=pace) if pace and pace > 0 else None,
            structuring_window_seconds=900,
        )
    except ValueError as exc:
        raise DraftError(f"the draft does not make a valid mandate: {exc}") from exc

    return Draft(
        body=body,
        assumptions=tuple(assumptions),
        unclear=tuple(unclear),
        drafted_by=getattr(brain, "name", "model"),
    )


@dataclass(frozen=True, slots=True)
class Exposure:
    """One line of "the worst an agent could do inside this"."""

    label: str
    value: str
    loose: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "value": self.value, "loose": self.loose, "note": self.note}


def exposure(m: Mandate) -> list[Exposure]:
    """Read a mandate for what it leaves open.

    Deterministic, and deliberately blunt. It does not judge whether the
    terms are sensible, only says in money what each one permits at worst,
    and marks the ones that are missing, because a missing cap is the line
    most people do not notice they left out.
    """
    total = m.total_limit
    item = m.per_item_limit
    payee = m.per_payee_limit
    out: list[Exposure] = []

    out.append(
        Exposure("Largest single purchase", str(item), note="")
        if item is not None
        else Exposure(
            "Largest single purchase",
            str(total),
            loose=True,
            note="No per-purchase cap, so one purchase could spend all of it.",
        )
    )

    out.append(
        Exposure("Most with one merchant", str(payee))
        if payee is not None
        else Exposure(
            "Most with one merchant",
            str(total),
            loose=True,
            note="No per-merchant cap, so it could all go to one place.",
        )
    )

    v = m.velocity
    if v is not None and v.max_count:
        ceiling = item if item is not None else total
        burst = Money(min(ceiling.minor * v.max_count, total.minor), total.currency)
        if v.max_amount is not None:
            burst = Money(min(burst.minor, v.max_amount.minor), total.currency)
        out.append(Exposure("Most in one minute", str(burst), note=f"{v.max_count} purchases at most"))
    else:
        out.append(
            Exposure(
                "Most in one minute",
                str(total),
                loose=True,
                note="No pace limit, so it could all go at once.",
            )
        )

    if m.allowed_categories:
        out.append(Exposure("Categories", ", ".join(sorted(m.allowed_categories))))
    else:
        out.append(Exposure("Categories", "anything", loose=True, note="No category limit."))

    out.append(
        Exposure(
            "Split purchases",
            "caught",
            note=(
                f"Grouped by merchant across their addresses for "
                f"{m.structuring_window_seconds // 60} minutes. Always on."
            ),
        )
    )

    # A length, not a date. The date would be UTC while the screen shows local
    # time, so a week drafted late in the evening in India read as expiring
    # a day before the rail said it did. And rounded, not floored: a week
    # checked a second after drafting is still a week, not six days.
    days = max(round((m.ends_at - datetime.now(timezone.utc)).total_seconds() / 86400), 0)
    out.append(
        Exposure(
            "Expires",
            "in 1 day" if days == 1 else f"in {days} days",
            note="After that it can't spend anything.",
        )
    )
    return out
