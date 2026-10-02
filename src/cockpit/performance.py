"""Performance of the portfolio, set against a benchmark.

The value of a portfolio moves for two reasons: prices change, and money comes
in or goes out. Only the first is performance. Each day's change is therefore
measured with that day's purchases counted in before it and that day's sales
counted back in after it, and the daily changes are chained. This is the
time-weighted return: it does not depend on when money was added.

Order fees and dividends received are left out, as in the value curve.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from decimal import Decimal

ZERO = Decimal(0)


def portfolio_index(points: Sequence[dict]) -> list[Decimal]:
    """Chained daily changes of the portfolio, starting from 1 before the first day."""
    index, previous = Decimal(1), ZERO
    result = []
    for point in points:
        value = Decimal(str(point["value"]))
        base = previous + Decimal(str(point["bought"]))
        if base > 0:
            index *= (value + Decimal(str(point["sold"]))) / base
        result.append(index)
        previous = value
    return result


def series(points: Sequence[dict], benchmark: Sequence[tuple[str, Decimal]]) -> list[dict]:
    """For each day: the portfolio's index and the benchmark's last known price
    (None before its first one). The screen rebases both on the period it shows."""
    days = [day for day, _ in benchmark]
    result = []
    for point, index in zip(points, portfolio_index(points), strict=True):
        position = bisect_right(days, point["date"]) - 1
        result.append(
            {
                "date": point["date"],
                "portfolio": float(index),
                "benchmark": float(benchmark[position][1]) if position >= 0 else None,
            }
        )
    return result
