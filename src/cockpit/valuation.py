"""Value of the portfolio day by day, since the first transaction.

For each day: quantity held of each line, times the last known price in euros.
Two details matter:

* Published price histories are adjusted for splits and bonus issues, so the
  quantities held before such an event are restated the same way. Without it,
  a 10-for-1 split would make the past look ten times smaller. A line held
  through the event is restated from the export, which records the shares
  received. A line already closed has no trace of it in the export: it is
  restated from the splits the price source publishes.
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


Splits = Mapping[str, list[tuple[str, Decimal]]]  # ISIN -> (day, new shares per old share)


def _restate_closed_lines(tracks: dict[tuple[str, str], _Track], splits: Splits) -> None:
    """Apply the splits that happened while a line held nothing.

    When shares were held on the day of the split, the export has its own row
    for it and the quantities are already restated: applying the published
    ratio as well would count the split twice.
    """
    for (_, isin), track in tracks.items():
        for day, ratio in sorted(splits.get(isin, [])):
            if track.at(day)[0] > SHARE_EPSILON:
                continue
            track.shares = [
                past * ratio if past_day < day else past
                for past_day, past in zip(track.days, track.shares, strict=True)
            ]


def _tracks(
    rows: Iterable[Row], splits: Splits | None = None
) -> tuple[dict[tuple[str, str], _Track], list[tuple[str, Decimal]]]:
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
    if splits:
        _restate_closed_lines(tracks, splits)
    return tracks, flows


def history(
    rows: Iterable[Row],
    prices: Mapping[str, list[tuple[str, Decimal]]],
    until: str,
    splits: Splits | None = None,
) -> dict:
    """Daily value, split by account, with the net amount invested so far.

    `prices` gives, per ISIN, (day, price in euros) sorted by day; `splits`,
    per ISIN, the splits published by the price source.
    """
    tracks, flows = _tracks(rows, splits)
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
        bought, sold = ZERO, ZERO  # of that day: what a performance must set aside
        while flow_index < len(flows) and flows[flow_index][0] <= day:
            amount = flows[flow_index][1]
            invested += amount
            if amount > 0:
                bought += amount
            else:
                sold -= amount
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
                "bought": money(bought),
                "sold": money(sold),
                "at_cost": money(at_cost),
                "accounts": {name: money(value) for name, value in sorted(accounts.items())},
            }
        )

    unpriced = sorted({isin for (_, isin) in tracks if not prices.get(isin)})
    return {"points": points, "unpriced": unpriced}
