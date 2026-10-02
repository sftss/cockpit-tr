"""Rules of the portfolio, checked after the fact on the stored transactions.

The code knows the *kinds* of rules; their values are personal and live in the
database, each with the period it applies to. A rule never blocks anything: a
transaction that departs from one is listed, and a written reason can be
attached to it ("dérogation motivée").

A transaction is only measured against the rules in force on its own day, so
setting a rule today says nothing about the past.
"""

from __future__ import annotations

import sqlite3
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from .days import parse_day
from .money import SHARE_EPSILON, ZERO, dec, money
from .portfolio import DEPOSITS, SHARE_CATEGORIES, TRADES, Row, chronological, quarter_of

# bound: "max" (the count or amount must not go above the value) or "min".
KINDS: dict[str, dict] = {
    "ordres_manuels_trimestre": {
        "label": "Ordres manuels par trimestre",
        "unit": "ordres",
        "bound": "max",
        "help": "Un ordre manuel est un achat ou une vente qui a payé des frais. "
        "Les exécutions de plan d'épargne n'en font pas partie.",
    },
    "frais_trimestre": {
        "label": "Frais d'ordre par trimestre",
        "unit": "€",
        "bound": "max",
        "help": "Frais payés sur les achats et les ventes du trimestre. "
        "Les frais de rechargement par carte ont leur propre règle.",
    },
    "achat_minimum": {
        "label": "Montant minimal d'un achat manuel",
        "unit": "€",
        "bound": "min",
        "per_account": True,
        "help": "En dessous, les frais fixes pèsent trop : passer par le plan d'épargne.",
    },
    "nouvelle_ligne_valeur_minimum": {
        "label": "Valeur du portefeuille avant toute nouvelle ligne",
        "unit": "€",
        "bound": "min",
        "help": "Tant que le portefeuille vaut moins, l'ouverture d'une ligne est un écart.",
    },
    "ventes_trimestre": {
        "label": "Ventes par trimestre",
        "unit": "ventes",
        "bound": "max",
        "help": "À zéro, chaque vente demande un motif : rupture de conformité ou de thèse.",
    },
    "lignes_soldees_trimestre": {
        "label": "Lignes soldées par trimestre",
        "unit": "lignes",
        "bound": "max",
        "help": "Une ligne est soldée quand sa quantité revient à zéro.",
    },
    "rechargements_carte_trimestre": {
        "label": "Rechargements par carte par trimestre",
        "unit": "rechargements",
        "bound": "max",
        "help": "Un rechargement par carte est un versement qui a payé des frais.",
    },
    "poids_maximum": {
        "label": "Poids maximal d'une ligne",
        "unit": "%",
        "bound": "max",
        "help": "Part d'une ligne dans le portefeuille Trade Republic, or exclu.",
    },
}

COUNTERS = (
    "ordres_manuels",
    "frais",
    "achats_sous_minimum",
    "nouvelles_lignes",
    "ventes",
    "lignes_soldees",
    "rechargements_carte",
)


@dataclass(frozen=True)
class Rule:
    id: int
    kind: str
    account: str | None
    value: Decimal
    valid_from: str
    valid_to: str | None
    note: str | None

    def covers(self, day: str) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day <= self.valid_to)


def active(rules: Iterable[Rule], kind: str, account: str | None, day: str) -> Rule | None:
    """The rule of this kind in force that day; one set for the account wins."""
    found = [
        rule
        for rule in rules
        if rule.kind == kind and rule.covers(day) and rule.account in (None, account)
    ]
    if not found:
        return None
    return max(found, key=lambda rule: (rule.account is not None, rule.valid_from, rule.id))


def _plain(value: Decimal) -> str:
    """A rule value as a person writes it: '4', '100', '2,5'."""
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


def _euros(value: Decimal) -> str:
    return f"{value:,.2f} €".replace(",", " ").replace(".", ",")


def _rank(n: int) -> str:
    return "1er" if n == 1 else f"{n}e"


def evaluate(
    rows: Iterable[Row],
    rules: list[Rule],
    value_on: Callable[[str], Decimal | None],
) -> tuple[list[dict], dict[str, dict]]:
    """Walk the transactions in order; return the departures and the counters per quarter."""
    held: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    quarters: dict[str, dict] = {}
    deviations: list[dict] = []

    for row in chronological(rows):
        kind, day, account = str(row["type"]), str(row["date"]), str(row["account_id"])
        isin = str(row["isin"] or "")
        fee = -dec(row["fee"])  # exported negative when paid
        counter = quarters.setdefault(
            quarter_of(day), {name: (ZERO if name == "frais" else 0) for name in COUNTERS}
        )
        breaches: list[dict] = []

        def limit(name: str, account: str = account, day: str = day) -> Decimal | None:
            rule = active(rules, name, account, day)
            return rule.value if rule else None

        def breach(name: str, detail: str, breaches: list[dict] = breaches) -> None:
            breaches.append({"kind": name, "label": KINDS[name]["label"], "detail": detail})

        if kind in TRADES and isin:
            key = (account, isin)
            before = held[key]
            quantity, amount = abs(dec(row["shares"])), abs(dec(row["amount"]))
            manual = fee != 0
            if manual:
                counter["ordres_manuels"] += 1
                allowed = limit("ordres_manuels_trimestre")
                if allowed is not None and counter["ordres_manuels"] > allowed:
                    breach(
                        "ordres_manuels_trimestre",
                        f"{_rank(counter['ordres_manuels'])} ordre manuel du trimestre, "
                        f"pour {_plain(allowed)} prévus",
                    )
            if kind == "BUY":
                minimum = limit("achat_minimum")
                if manual and minimum is not None and amount < minimum:
                    counter["achats_sous_minimum"] += 1
                    breach(
                        "achat_minimum",
                        f"achat de {_euros(amount)}, sous le minimum de {_euros(minimum)}",
                    )
                if before < SHARE_EPSILON:
                    counter["nouvelles_lignes"] += 1
                    threshold = limit("nouvelle_ligne_valeur_minimum")
                    worth = value_on(day) if threshold is not None else None
                    if threshold is not None and (worth is None or worth < threshold):
                        known = _euros(worth) if worth is not None else "un montant inconnu"
                        breach(
                            "nouvelle_ligne_valeur_minimum",
                            f"nouvelle ligne alors que le portefeuille vaut {known}, "
                            f"sous {_euros(threshold)}",
                        )
                held[key] = before + quantity
            else:
                counter["ventes"] += 1
                allowed = limit("ventes_trimestre")
                if allowed is not None and counter["ventes"] > allowed:
                    breach(
                        "ventes_trimestre",
                        "vente à motiver : rupture de conformité ou de thèse"
                        if allowed == 0
                        else f"{_rank(counter['ventes'])} vente du trimestre, "
                        f"pour {_plain(allowed)} prévues",
                    )
                after = before - quantity
                if before >= SHARE_EPSILON and after < SHARE_EPSILON:
                    counter["lignes_soldees"] += 1
                    allowed = limit("lignes_soldees_trimestre")
                    if allowed is not None and counter["lignes_soldees"] > allowed:
                        breach(
                            "lignes_soldees_trimestre",
                            f"{_rank(counter['lignes_soldees'])} ligne soldée du trimestre, "
                            f"pour {_plain(allowed)} prévues",
                        )
                held[key] = after if after >= SHARE_EPSILON else ZERO
        elif isin and str(row["category"]) in SHARE_CATEGORIES:
            held[(account, isin)] += dec(row["shares"])  # split, bonus issue, migration
        elif kind in DEPOSITS and fee != 0:
            counter["rechargements_carte"] += 1
            allowed = limit("rechargements_carte_trimestre")
            if allowed is not None and counter["rechargements_carte"] > allowed:
                breach(
                    "rechargements_carte_trimestre",
                    f"rechargement par carte ({_euros(fee)} de frais), "
                    f"pour {_plain(allowed)} prévus",
                )

        if fee > 0 and kind in TRADES:
            counter["frais"] += fee
            allowed = limit("frais_trimestre")
            if allowed is not None and counter["frais"] > allowed:
                breach(
                    "frais_trimestre",
                    f"frais d'ordre du trimestre portés à {_euros(counter['frais'])}, "
                    f"pour {_euros(allowed)} prévus",
                )

        if breaches:
            deviations.append(
                {
                    "transaction_id": str(row["transaction_id"]),
                    "date": day,
                    "quarter": quarter_of(day),
                    "account": account,
                    "type": kind,
                    "name": str(row["name"] or ""),
                    "isin": isin or None,
                    "amount": money(abs(dec(row["amount"]))),
                    "fee": money(fee),
                    "breaches": breaches,
                }
            )
    return deviations, quarters


# -- Storage ---------------------------------------------------------------------


def _rule(row: sqlite3.Row) -> Rule:
    return Rule(
        id=row["id"],
        kind=row["kind"],
        account=row["account_id"],
        value=dec(row["value"]),
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        note=row["note"],
    )


def list_rules(conn: sqlite3.Connection) -> list[Rule]:
    rows = conn.execute("SELECT * FROM rules ORDER BY kind, account_id, valid_from").fetchall()
    return [_rule(row) for row in rows if row["kind"] in KINDS]


def set_rule(
    conn: sqlite3.Connection,
    kind: str,
    value: object,
    valid_from: str | None = None,
    account: str | None = None,
    note: str | None = None,
) -> int:
    """Give a rule a value from a given day; the value in force until then is closed."""
    if kind not in KINDS:
        raise ValueError("Type de règle inconnu.")
    account = (account or "").strip() or None
    if account and not KINDS[kind].get("per_account"):
        raise ValueError("Cette règle ne se règle pas par compte.")
    if account and not conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account,)).fetchone():
        raise ValueError("Compte inconnu.")
    amount = dec(str(value).replace(",", "."))
    if amount < 0:
        raise ValueError("La valeur d'une règle ne peut pas être négative.")
    start = parse_day(valid_from, date.today())

    same_day = conn.execute(
        "SELECT id FROM rules WHERE kind = ? AND account_id IS ? AND valid_from = ?",
        (kind, account, start.isoformat()),
    ).fetchone()
    if same_day:
        conn.execute(
            "UPDATE rules SET value = ?, note = ?, valid_to = NULL WHERE id = ?",
            (str(amount), (note or "").strip() or None, same_day["id"]),
        )
        conn.commit()
        return same_day["id"]

    conn.execute(
        "UPDATE rules SET valid_to = ? WHERE kind = ? AND account_id IS ? "
        "AND valid_from < ? AND (valid_to IS NULL OR valid_to >= ?)",
        (
            (start - timedelta(days=1)).isoformat(),
            kind,
            account,
            start.isoformat(),
            start.isoformat(),
        ),
    )
    # A value dated before one already set stops the day before that one starts.
    later = conn.execute(
        "SELECT MIN(valid_from) FROM rules WHERE kind = ? AND account_id IS ? AND valid_from > ?",
        (kind, account, start.isoformat()),
    ).fetchone()[0]
    end = (date.fromisoformat(later) - timedelta(days=1)).isoformat() if later else None
    cursor = conn.execute(
        "INSERT INTO rules (kind, account_id, value, valid_from, valid_to, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            kind,
            account,
            str(amount),
            start.isoformat(),
            end,
            (note or "").strip() or None,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    deleted = conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,)).rowcount
    conn.commit()
    return bool(deleted)


def set_reason(conn: sqlite3.Connection, transaction_id: str, reason: str) -> None:
    known = conn.execute(
        "SELECT 1 FROM transactions WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()
    if not known:
        raise KeyError(transaction_id)
    reason = reason.strip()
    if not reason:
        conn.execute("DELETE FROM deviation_notes WHERE transaction_id = ?", (transaction_id,))
    else:
        conn.execute(
            "INSERT INTO deviation_notes (transaction_id, reason, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (transaction_id) DO UPDATE SET reason = excluded.reason, "
            "updated_at = excluded.updated_at",
            (transaction_id, reason, datetime.now(UTC).isoformat(timespec="seconds")),
        )
    conn.commit()


# -- What the screens show ----------------------------------------------------


def _public(rule: Rule) -> dict:
    return {
        "id": rule.id,
        "kind": rule.kind,
        "account": rule.account,
        "value": float(rule.value),
        "valid_from": rule.valid_from,
        "valid_to": rule.valid_to,
        "note": rule.note,
    }


def state(
    rows: Iterable[Row],
    rules: list[Rule],
    value_points: list[tuple[str, Decimal]],
    weights: list[dict],
    reasons: Mapping[str, str],
    today: date | None = None,
) -> dict:
    """Counters of the current quarter against the rules, and every departure.

    `value_points` is the value of the portfolio day by day; `weights` gives, for
    each open line, its name, account and share of the portfolio.
    """
    today = today or date.today()
    day = today.isoformat()
    days = [point[0] for point in value_points]

    def value_on(when: str) -> Decimal | None:
        index = bisect_right(days, when) - 1
        return value_points[index][1] if index >= 0 else None

    deviations, quarters = evaluate(rows, rules, value_on)
    for deviation in deviations:
        deviation["reason"] = reasons.get(deviation["transaction_id"])
    deviations.sort(key=lambda d: (d["date"], d["transaction_id"]), reverse=True)

    quarter = quarter_of(day)
    counter = quarters.get(quarter, {name: (ZERO if name == "frais" else 0) for name in COUNTERS})
    this_quarter = [d for d in deviations if d["quarter"] == quarter]

    def breaches(kind: str) -> int:
        return sum(1 for d in this_quarter for b in d["breaches"] if b["kind"] == kind)

    def line(kind: str, count: object, account: str | None = None) -> dict:
        rule = active(rules, kind, account, day)
        return {
            "kind": kind,
            "label": KINDS[kind]["label"],
            "unit": KINDS[kind]["unit"],
            "bound": KINDS[kind]["bound"],
            "account": rule.account if rule else None,
            "count": float(count) if isinstance(count, Decimal) else count,
            "limit": float(rule.value) if rule else None,
            "breaches": breaches(kind),
        }

    current = [
        line("ordres_manuels_trimestre", counter["ordres_manuels"]),
        line("frais_trimestre", counter["frais"]),
        line("ventes_trimestre", counter["ventes"]),
        line("lignes_soldees_trimestre", counter["lignes_soldees"]),
        line("rechargements_carte_trimestre", counter["rechargements_carte"]),
    ]
    # Rules that are not a count against a ceiling: say what was observed instead.
    new_lines = line("nouvelle_ligne_valeur_minimum", counter["nouvelles_lignes"])
    worth = value_on(day)
    new_lines["portfolio_value"] = money(worth) if worth is not None else None
    current.append(new_lines)

    minimums = sorted(
        (
            rule
            for rule in rules
            if rule.kind == "achat_minimum"
            and rule.covers(day)
            and active(rules, "achat_minimum", rule.account, day) == rule
        ),
        key=lambda rule: rule.account or "",
    )
    under = line("achat_minimum", counter["achats_sous_minimum"])
    under["minimums"] = [{"account": r.account, "value": float(r.value)} for r in minimums]
    under["limit"] = float(minimums[0].value) if len(minimums) == 1 else None
    under["account"] = minimums[0].account if len(minimums) == 1 else None
    current.append(under)

    ceiling = active(rules, "poids_maximum", None, day)
    heavy = (
        [w for w in weights if w["weight"] is not None and w["weight"] * 100 > ceiling.value]
        if ceiling
        else []
    )
    weight = line("poids_maximum", len(heavy))
    weight["breaches"] = len(heavy)
    weight["lines"] = heavy
    current.append(weight)

    return {
        "quarter": quarter,
        "kinds": [{"kind": kind, **meta} for kind, meta in KINDS.items()],
        "rules": [_public(rule) for rule in rules],
        "current": current,
        "deviations": deviations,
        "pending": sum(1 for d in deviations if not d["reason"]),
        "has_rules": any(rule.covers(day) for rule in rules),
    }
