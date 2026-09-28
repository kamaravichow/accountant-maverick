"""Shared helpers for deterministic tax arithmetic.

All money maths uses ``Decimal`` with ROUND_HALF_UP so results match how Indian
tax utilities and CA working papers round, never binary floats.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

Number = int | float | str | Decimal


def D(x: Number | None) -> Decimal:
    if x is None:
        return Decimal(0)
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def r2(x: Number) -> Decimal:
    """Round to paise."""
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r0(x: Number) -> Decimal:
    """Round to the nearest rupee."""
    return D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def round10(x: Number) -> Decimal:
    """Sec 288A (total income) / 288B (tax) of ITA 1961: round to nearest multiple of Rs 10
    (Rs 5 and above rounded up)."""
    x = D(x)
    return (x / 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 10


def floor100(x: Number) -> Decimal:
    """Rule 119A: amount for interest u/s 234A/B/C rounded down to a multiple of Rs 100."""
    x = D(x)
    if x <= 0:
        return Decimal(0)
    return (x / 100).quantize(Decimal("1"), rounding=ROUND_DOWN) * 100


def pct(x: Number) -> Decimal:
    return D(x) / 100


def months_or_part(start_exclusive: date, end_inclusive: date) -> int:
    """Number of months 'or part of a month' in the period that begins the day after
    ``start_exclusive`` and ends on ``end_inclusive`` (the counting rule used by
    sec 234A/234B/201(1A) of the Income-tax Act; a part month counts as a full month).
    """
    s = start_exclusive + timedelta(days=1)
    if end_inclusive < s:
        return 0
    months = (end_inclusive.year - s.year) * 12 + (end_inclusive.month - s.month)
    # the month starting on s's day-of-month is only "entered" if end has reached that day
    if end_inclusive.day >= s.day:
        months += 1
    return max(months, 1)


def calendar_months(start_inclusive: date, end_inclusive: date) -> int:
    """Calendar months touched by the period (the TRACES practice for sec 201(1A):
    deducted 30-Apr, paid 1-May = 2 months)."""
    if end_inclusive < start_inclusive:
        return 0
    return (end_inclusive.year - start_inclusive.year) * 12 + end_inclusive.month - start_inclusive.month + 1


def days_between(start_exclusive: date, end_inclusive: date) -> int:
    return max((end_inclusive - start_exclusive).days, 0)


def money(x: Number) -> float:
    """JSON friendly money value (2dp)."""
    return float(r2(x))


def to_date(x: Any) -> date:
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


class Trail:
    """Collects human readable working steps - an audit trail the accountant can verify."""

    def __init__(self) -> None:
        self.steps: list[str] = []

    def add(self, text: str) -> None:
        self.steps.append(text)

    def __call__(self, text: str) -> None:
        self.add(text)


def inr(x: Number) -> str:
    """Format in Indian digit grouping: 12,34,567.89"""
    x = r2(x)
    neg = x < 0
    s = f"{abs(x):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}Rs {whole}.{frac}"
