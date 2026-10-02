"""Quality grid out of 20 for the daily company sheet ("fiche du jour").

The grid turns published figures into ratios, then into points, with fixed
thresholds taken from the AQRP method (five base ratios, valuation, payout).
Same figures in, same score out: nothing here is estimated or judged.

A score sorts companies for the quarterly review. It is not a forecast and not
a buy signal, and it says nothing about Sharia compliance, which is checked
separately.

This module only uses the standard library and imports nothing from the rest
of the package, so it also runs on its own:

    python src/cockpit/scoring.py fiches/2026/2026-10-02-legrand.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

MIN_CRITERIA = 5  # below this, too little is known to give a score
LABELS = [(15, "à approfondir"), (12, "à surveiller"), (0, "écarté")]


@dataclass
class Criterion:
    key: str
    label: str
    max_points: int
    value: float | None = None
    points: int | None = None
    display: str = "non disponible"
    rule: str = ""


def cagr(start: float, end: float, years: int) -> float | None:
    """Compound annual growth rate; undefined from a zero or negative base."""
    if years <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def _first_last(series: dict[str, float]) -> tuple[int, float, int, float]:
    years = sorted(int(year) for year in series)
    first, last = years[0], years[-1]
    return first, float(series[str(first)]), last, float(series[str(last)])


def _steps(value: float, steps: list[tuple[float, int]]) -> int:
    """Points of the first threshold the value reaches (thresholds descending)."""
    for threshold, points in steps:
        if value >= threshold:
            return points
    return 0


def _pct(value: float) -> str:
    return f"{value * 100:.1f} %".replace(".", ",")


def _revenue_growth(data: dict) -> Criterion:
    c = Criterion("croissance_ca", "Croissance du chiffre d'affaires", 3)
    c.rule = "≥ 10 %/an : 3 · 5 à 10 % : 2 · 0 à 5 % : 1 · en baisse : 0"
    series = data.get("chiffre_affaires")
    if not series or len(series) < 2:
        return c
    first, start, last, end = _first_last(series)
    growth = cagr(start, end, last - first)
    if growth is None:
        return c
    c.value, c.points = growth, _steps(growth, [(0.10, 3), (0.05, 2), (0.0, 1)])
    c.display = f"{_pct(growth)} par an ({first}–{last})"
    return c


def _net_margin(data: dict) -> Criterion:
    c = Criterion("marge_nette", "Marge nette", 3)
    physical = bool(data.get("produits_physiques"))
    high, mid, low = (0.10, 0.05, 0.025) if physical else (0.20, 0.10, 0.05)
    c.rule = (
        f"≥ {high * 100:g} % : 3 · ≥ {mid * 100:g} % : 2 · ≥ {low * 100:g} % : 1 · sinon 0".replace(
            ".", ","
        )
        + (" (seuils des produits physiques)" if physical else "")
    )
    revenue, net = data.get("chiffre_affaires_12m"), data.get("resultat_net_12m")
    if not revenue or net is None:
        return c
    margin = net / revenue
    c.value, c.points = margin, _steps(margin, [(high, 3), (mid, 2), (low, 1)])
    c.display = _pct(margin)
    return c


def _leverage(data: dict) -> Criterion:
    c = Criterion("dette_ebitda", "Dette nette / EBITDA", 3)
    c.rule = "< 2 ou trésorerie nette : 3 · 2 à 3 : 1 · ≥ 3 : 0"
    debt, ebitda = data.get("dette_nette"), data.get("ebitda_12m")
    if debt is None or ebitda is None:
        return c
    if debt <= 0:
        c.value, c.points, c.display = 0.0, 3, "trésorerie nette"
        return c
    if ebitda <= 0:
        c.value, c.points, c.display = None, 0, "EBITDA négatif"
        return c
    ratio = debt / ebitda
    c.value = ratio
    c.points = 3 if ratio < 2 else 1 if ratio < 3 else 0
    c.display = f"{ratio:.1f}".replace(".", ",")
    return c


def _fcf_growth(data: dict) -> Criterion:
    c = Criterion("croissance_fcf", "Croissance du cash-flow libre", 3)
    c.rule = (
        "≥ 10 %/an : 3 · 0 à 10 % : 2 · positif mais en baisse ou irrégulier : 1 · "
        "négatif au dernier exercice : 0"
    )
    series = data.get("cash_flow_libre")
    if not series or len(series) < 2:
        return c
    first, start, last, end = _first_last(series)
    if end <= 0:
        c.value, c.points, c.display = None, 0, f"négatif en {last}"
        return c
    if any(float(v) <= 0 for v in series.values()):
        c.value, c.points, c.display = None, 1, "une année négative sur la période"
        return c
    growth = cagr(start, end, last - first)
    c.value = growth
    c.points = 3 if growth >= 0.10 else 2 if growth >= 0 else 1
    c.display = f"{_pct(growth)} par an ({first}–{last}), positif chaque année"
    return c


def _roic(data: dict) -> Criterion:
    c = Criterion("roic", "ROIC", 4)
    c.rule = "≥ 20 % : 4 · ≥ 15 % : 3 · ≥ 10 % : 2 · ≥ 5 % : 1 · sinon 0"
    operating, tax = data.get("resultat_operationnel_12m"), data.get("taux_impot")
    equity, debt = data.get("capitaux_propres"), data.get("dette_nette")
    if operating is None or tax is None or equity is None or debt is None:
        return c
    capital = equity + debt
    if capital <= 0:
        return c
    roic = operating * (1 - tax) / capital
    c.value, c.points = roic, _steps(roic, [(0.20, 4), (0.15, 3), (0.10, 2), (0.05, 1)])
    c.display = _pct(roic)
    return c


def _per(data: dict) -> Criterion:
    c = Criterion("per", "PER (12 derniers mois)", 2)
    c.rule = "< 25 : 2 · 25 à 35 : 1 · ≥ 35 ou bénéfice négatif : 0"
    per = data.get("per")
    if per is None:
        return c
    c.value = per
    c.points = 0 if per <= 0 or per >= 35 else 2 if per < 25 else 1
    c.display = "bénéfice négatif" if per <= 0 else f"{per:.1f}".replace(".", ",")
    return c


def _payout(data: dict) -> Criterion:
    c = Criterion("distribution", "Taux de distribution", 2)
    c.rule = "≤ 60 % : 2 · 60 à 80 % : 1 · > 80 % : 0 · pas de dividende : 1"
    if "taux_distribution" not in data:
        return c
    payout = data["taux_distribution"]
    if payout is None or payout == 0:
        c.value, c.points, c.display = 0.0, 1, "pas de dividende"
        return c
    c.value = payout
    c.points = 2 if payout <= 0.60 else 1 if payout <= 0.80 else 0
    c.display = _pct(payout)
    return c


def score(data: dict) -> dict:
    """Score one company from its published figures (the ``chiffres`` block)."""
    criteria = [
        f(data)
        for f in (_revenue_growth, _net_margin, _leverage, _fcf_growth, _roic, _per, _payout)
    ]
    known = [c for c in criteria if c.points is not None]
    earned = sum(c.points for c in known)
    available = sum(c.max_points for c in known)

    note = label = None
    if len(known) >= MIN_CRITERIA:
        # Missing criteria are left out and the score is brought back to 20.
        note = round(earned * 20 / available, 1)
        label = next(name for floor, name in LABELS if note >= floor)

    return {
        "note": note,
        "libelle": label,
        "points": earned,
        "points_possibles": available,
        "criteres_notes": len(known),
        "criteres": [
            {
                "cle": c.key,
                "critere": c.label,
                "valeur": c.value,
                "affichage": c.display,
                "points": c.points,
                "maximum": c.max_points,
                "bareme": c.rule,
            }
            for c in criteria
        ],
    }


def markdown_table(result: dict) -> str:
    lines = ["| Critère | Valeur | Points | Barème |", "| --- | --- | --- | --- |"]
    for c in result["criteres"]:
        points = "—" if c["points"] is None else f"{c['points']} / {c['maximum']}"
        lines.append(f"| {c['critere']} | {c['affichage']} | {points} | {c['bareme']} |")
    return "\n".join(lines)


def headline(result: dict) -> str:
    if result["note"] is None:
        return f"Non notée : {result['criteres_notes']} critères disponibles sur 7."
    note = f"{result['note']:g}".replace(".", ",")
    partial = (
        ""
        if result["criteres_notes"] == 7
        else (f" (note partielle : {result['criteres_notes']} critères sur 7)")
    )
    return f"{note} / 20 — {result['libelle']}{partial}"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage : python src/cockpit/scoring.py <fiche.json>", file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8") as handle:
        sheet = json.load(handle)
    result = score(sheet.get("chiffres", sheet))
    print(headline(result))
    print()
    print(markdown_table(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
