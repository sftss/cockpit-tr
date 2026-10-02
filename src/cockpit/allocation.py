"""How the portfolio is spread: by account, kind, currency, country and sector.

Country and sector come from the public list of companies (``fiches/univers.json``).
A fund is not looked through: it counts as one block. A company that is not in
the list is reported as unclassified rather than guessed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from .money import money, ratio

ZERO = Decimal(0)
MAX_GROUPS = 8  # beyond it, the smallest are gathered: more bars would not be read
ACCOUNTS = {"CTO": "Compte-titres", "PEA": "PEA"}
FUND, UNKNOWN, OTHERS = "Fonds (non détaillé)", "Non classé", "Autres"
LAST = (OTHERS, FUND, UNKNOWN)  # shown after the real groups, whatever their size


def _groups(amounts: dict[str, Decimal], counts: dict[str, int], total: Decimal) -> list[dict]:
    named = sorted(
        (label for label in amounts if label not in LAST), key=lambda label: -amounts[label]
    )
    if len(named) > MAX_GROUPS:
        for label in named[MAX_GROUPS - 1 :]:
            amounts[OTHERS] = amounts.get(OTHERS, ZERO) + amounts.pop(label)
            counts[OTHERS] = counts.get(OTHERS, 0) + counts.pop(label)
        named = named[: MAX_GROUPS - 1]
    order = named + [label for label in LAST if label in amounts]
    return [
        {
            "label": label,
            "amount": money(amounts[label]),
            "weight": ratio(amounts[label], total) if total else None,
            "lines": counts[label],
        }
        for label in order
    ]


def breakdown(
    positions: Sequence[Mapping],
    basis: str,
    currencies: Mapping[str, str | None],
    universe: Mapping[str, Mapping],
) -> dict:
    """Shares of the portfolio along each dimension. `basis` is 'value' or 'cost',
    the same for every line; `currencies` gives the quotation currency per ISIN."""

    def kind(position: Mapping) -> str:
        return "Fonds (ETF)" if position["asset_class"] == "FUND" else "Actions"

    def from_list(field: str):
        def label(position: Mapping) -> str:
            if position["asset_class"] == "FUND":
                return FUND
            return str(universe.get(position["isin"], {}).get(field) or UNKNOWN)

        return label

    dimensions = [
        ("compte", "Compte", lambda p: ACCOUNTS.get(p["account"], p["account"])),
        ("type", "Type de titre", kind),
        ("devise", "Devise de cotation", lambda p: currencies.get(p["isin"]) or "Non connue"),
        ("pays", "Pays du siège", from_list("pays")),
        ("secteur", "Secteur", from_list("secteur")),
    ]
    total = sum((Decimal(str(p[basis])) for p in positions), ZERO)
    result = []
    for identifier, title, label_of in dimensions:
        amounts: dict[str, Decimal] = {}
        counts: dict[str, int] = {}
        for position in positions:
            label = label_of(position)
            amounts[label] = amounts.get(label, ZERO) + Decimal(str(position[basis]))
            counts[label] = counts.get(label, 0) + 1
        result.append({"id": identifier, "title": title, "groups": _groups(amounts, counts, total)})
    unclassified = sorted(
        {
            str(p["name"])
            for p in positions
            if p["asset_class"] != "FUND" and p["isin"] not in universe
        }
    )
    return {
        "basis": basis,
        "total": money(total),
        "dimensions": result,
        "unclassified": unclassified,
    }
