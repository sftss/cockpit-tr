"""Value of the portfolio day by day, since the first transaction.

For each day: quantity held of each line, times the last known price in euros.
Two details matter:

* Published price histories are adjusted for splits and bonus issues, so the
  quantities held before such an event are restated the same way. Without it,
  a 10-for-1 split would make the past look ten times smaller.
* A line with no known price yet on a given day is counted at its cost, and
  the share of the total valued that way is reported, so the curve never
  silently mixes prices and costs.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from .money import SHARE_EPSILON, ZERO, dec, money
from .portfolio import SHARE_CATEGORIES, Row, chronological

RESTATING = {"SPLIT", "BONUS_ISSUE"}


@dataclass
class _Track:
    """Quantity and cost of one line after each of its movements."""

    days: list[str] = field(default_factory=list)
    shares: list[Decimal] = field(default_factory=list)
    costs: list[Decimal] = field(default_factory=list)

    def at(self, day: str) -> tuple[Decimal, Decimal]:
        index = bisect_right(self.days, day) - 1
        return (self.shares[index], self.costs[index]) if index >= 0 else (ZERO, ZERO)


def _tracks(rows: Iterable[Row]) -> tuple[dict[tuple[str, str], _Track], list[tuple[str, Decimal]]]:
    tracks: dict[tuple[str, str], _Track] = {}
    state: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
    flows: list[tuple[str, Decimal]] = []  # (day, net amount invested that day)

    for row in chronological(rows):
        isin = str(row["isin"] or "")
        if not isin or str(row["category"]) not in SHARE_CATEGORIES:
            continue
        key = (str(row["account_id"]), isin)
        held, cost = state.get(key, (ZERO, ZERO))
        track = tracks.setdefault(key, _Track())
        kind, day = str(row["type"]), str(row["date"])
        quantity, value = abs(dec(row["shares"])), abs(dec(row["amount"]))

        if kind == "BUY":
            held, cost = held + quantity, cost + value
            flows.append((day, value))
        elif kind == "SELL":
            released = cost if held - quantity < SHARE_EPSILON else cost * quantity / held
            held, cost = held - quantity, cost - released
            flows.append((day, -value))
            if held < SHARE_EPSILON:
                held, cost = ZERO, ZERO
        else:
            delta = dec(row["shares"])
            if kind in RESTATING and held > SHARE_EPSILON:
                factor = (held + delta) / held
                track.shares = [past * factor for past in track.shares]
            held += delta

        state[key] = (held, cost)
        if track.days and track.days[-1] == day:
            track.shares[-1], track.costs[-1] = held, cost
        else:
            track.days.append(day)
            track.shares.append(held)
            track.costs.append(cost)
    return tracks, flows


def history(
    rows: Iterable[Row], prices: Mapping[str, list[tuple[str, Decimal]]], until: str
) -> dict:
    """Daily value, split by account, with the net amount invested so far.

    `prices` gives, per ISIN, (day, price in euros) sorted by day.
    """
    tracks, flows = _tracks(rows)
    if not tracks:
        return {"points": [], "unpriced": []}

    first = min(track.days[0] for track in tracks.values())
    days = sorted(
        {day for track in tracks.values() for day in track.days}
        | {day for series in prices.values() for day, _ in series if first <= day <= until}
    )
    price_days = {isin: [day for day, _ in series] for isin, series in prices.items()}
    flows.sort()

    points, flow_index, invested = [], 0, ZERO
    for day in days:
        while flow_index < len(flows) and flows[flow_index][0] <= day:
            invested += flows[flow_index][1]
            flow_index += 1
        total, at_cost = ZERO, ZERO
        accounts: dict[str, Decimal] = {}
        for (account, isin), track in tracks.items():
            held, cost = track.at(day)
            if held < SHARE_EPSILON:
                continue
            index = bisect_right(price_days.get(isin, []), day) - 1
            if index >= 0:
                value = held * prices[isin][index][1]
            else:
                value = cost
                at_cost += cost
            total += value
            accounts[account] = accounts.get(account, ZERO) + value
        points.append(
            {
                "date": day,
                "value": money(total),
                "invested": money(invested),
                "at_cost": money(at_cost),
                "accounts": {name: money(value) for name, value in sorted(accounts.items())},
            }
        )

    unpriced = sorted({isin for (_, isin) in tracks if not prices.get(isin)})
    return {"points": points, "unpriced": unpriced}
