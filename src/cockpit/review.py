"""The quarterly review.

Every figure is computed here, from the same functions as the screens: the
review is a photograph of one quarter, taken when it is generated and kept as
it was. Reading the figures is another matter, left to the user (the
conclusions) and, when asked, to the assistant (the commentary).

A review reports and compares. It gives no order to buy or to sell.
"""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_right
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from . import compliance, performance, roadmap, rules, store
from .money import ZERO, dec, money, ratio
from .portfolio import quarter_of

ACCOUNTS = {"CTO": "Compte-titres", "PEA": "PEA"}
STATUSES = {**compliance.STATUSES, None: "non renseignée"}
# Counters set against a ceiling, in the order the review shows them.
COUNTED = (
    "ordres_manuels_trimestre",
    "frais_trimestre",
    "ventes_trimestre",
    "lignes_soldees_trimestre",
    "rechargements_carte_trimestre",
    "nouvelle_ligne_valeur_minimum",
)


# -- Quarters ----------------------------------------------------------------------


def bounds(quarter: str) -> tuple[date, date]:
    """First and last day of '2026-T3'."""
    try:
        year, number = int(quarter[:4]), int(quarter[6:])
        if quarter[4:6] != "-T" or not 1 <= number <= 4:
            raise ValueError
    except ValueError as exc:
        raise ValueError("Trimestre attendu sous la forme 2026-T3.") from exc
    first = date(year, 3 * number - 2, 1)
    after = date(year + 1, 1, 1) if number == 4 else date(year, 3 * number + 1, 1)
    return first, after - timedelta(days=1)


def following(quarter: str) -> str:
    return quarter_of((bounds(quarter)[1] + timedelta(days=1)).isoformat())


def preceding(quarter: str) -> str:
    return quarter_of((bounds(quarter)[0] - timedelta(days=1)).isoformat())


def name(quarter: str) -> str:
    """'2026-T3' -> 'T3 2026'."""
    return f"{quarter[5:]} {quarter[:4]}"


# -- Words for figures -------------------------------------------------------------

MONEY = {"frais_trimestre"}  # counters that are amounts, not counts


def _euro(value: float | None) -> str:
    if value is None:
        return "—"
    text = f"{abs(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{'-' if value < 0 else ''}{text} €"


def _signed(value: float | None) -> str:
    return "—" if value is None else ("+" if value > 0 else "") + _euro(value)


def _pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "—"
    text = f"{abs(value) * 100:.1f}".replace(".", ",")
    sign = "-" if value < 0 else "+" if signed and value > 0 else ""
    return f"{sign}{text} %"


def _day(iso: str | None) -> str:
    return "—" if not iso else f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def _observed(kind: str, count: float) -> str:
    """What was counted over the quarter, in words a table can show."""
    return _euro(count) if kind in MONEY else f"{count:g}"


def _allowed(kind: str, limit: float | None) -> str:
    if limit is None:
        return "pas de règle"
    if kind == "nouvelle_ligne_valeur_minimum":
        return f"aucune tant que le portefeuille vaut moins de {_euro(limit)}"
    return f"au plus {_euro(limit) if kind in MONEY else f'{limit:g}'}"


# -- Building ----------------------------------------------------------------------


def _quarter_performance(conn: sqlite3.Connection, first: date, last: date) -> dict:
    """What the portfolio did over the quarter, money added or withdrawn set aside,
    beside a fund of the portfolio taken as a benchmark (stored prices only)."""
    points = store.value_history(conn)["points"]
    days = [point["date"] for point in points]
    before = bisect_right(days, (first - timedelta(days=1)).isoformat()) - 1
    until = bisect_right(days, last.isoformat()) - 1
    inside = points[before + 1 : until + 1]
    if until < 0:
        return {"available": False}  # nothing was held yet

    start_value = Decimal(str(points[before]["value"])) if before >= 0 else ZERO
    end_value = Decimal(str(points[until]["value"]))
    bought = sum((Decimal(str(point["bought"])) for point in inside), ZERO)
    sold = sum((Decimal(str(point["sold"])) for point in inside), ZERO)
    index = performance.portfolio_index(points)
    start_index = index[before] if before >= 0 else Decimal(1)
    result = {
        "available": True,
        # Without a trade or a price in the quarter, the last known value carries over.
        "from": inside[0]["date"] if inside else first.isoformat(),
        "to": inside[-1]["date"] if inside else last.isoformat(),
        "start_value": money(start_value),
        "end_value": money(end_value),
        "bought": money(bought),
        "sold": money(sold),
        "gain": money(end_value - start_value - bought + sold),
        "change": ratio(index[until] - start_index, start_index),
        "at_cost": points[until]["at_cost"],
        "benchmark": None,
    }

    history = store.price_history(conn)
    funds = store.benchmark_funds(conn, history)
    if funds:
        prices = history[funds[0]["id"]]
        price_days = [day for day, _ in prices]
        base = bisect_right(price_days, (first - timedelta(days=1)).isoformat()) - 1
        end = bisect_right(price_days, last.isoformat()) - 1
        base = max(base, 0)  # a fund first priced inside the quarter starts there
        if end > base and prices[base][1] > 0:
            result["benchmark"] = {
                "label": funds[0]["label"],
                "from": prices[base][0],
                "change": ratio(prices[end][1] - prices[base][1], prices[base][1]),
            }
    return result


def _sheets(fiches: Path | None, first: date, last: date) -> list[dict]:
    """Company sheets dated in the quarter, best score first."""
    if fiches is None:
        return []
    from .scoring import score  # the grid itself: same figures, same score

    found = []
    for file in fiches.glob("20*/*.json"):
        try:
            sheet = json.loads(file.read_text(encoding="utf-8"))
            if not first.isoformat() <= str(sheet.get("date")) <= last.isoformat():
                continue
            result = score(sheet.get("chiffres", sheet))
        except (ValueError, OSError, TypeError, KeyError):
            continue
        found.append(
            {
                "date": sheet["date"],
                "name": sheet.get("nom"),
                "score": result["note"],
                "label": result["libelle"],
            }
        )
    return sorted(found, key=lambda s: (-(s["score"] or 0), s["name"] or ""))


def build(
    conn: sqlite3.Connection, quarter: str, fiches: Path | None, today: date | None = None
) -> dict:
    """Every figure of the review of `quarter`, as plain data."""
    today = today or date.today()
    first, last = bounds(quarter)
    if first > today:
        raise ValueError("Ce trimestre n'a pas commencé.")
    as_of = min(last, today)
    report = store.current_report(conn)
    state = store.rules_state(conn, as_of)
    all_rules = rules.list_rules(conn)
    next_first = (last + timedelta(days=1)).isoformat()

    counters = []
    for line in state["current"]:
        if line["kind"] not in COUNTED:
            continue
        ahead = rules.active(all_rules, line["kind"], None, next_first)
        counters.append(
            {
                "kind": line["kind"],
                "label": "Nouvelles lignes"
                if line["kind"] == "nouvelle_ligne_valeur_minimum"
                else line["label"],
                "count": _observed(line["kind"], line["count"]),
                "limit": _allowed(line["kind"], line["limit"]),
                "next_limit": _allowed(line["kind"], float(ahead.value) if ahead else None),
                "breaches": line["breaches"],
            }
        )

    in_quarter = [first.isoformat(), last.isoformat()]

    def within(day: str | None) -> bool:
        return bool(day) and in_quarter[0] <= day <= in_quarter[1]

    manual_amount = sum(
        (
            abs(dec(row["amount"]))
            for row in store.all_transactions(conn)
            if row["type"] in ("BUY", "SELL") and dec(row["fee"]) != 0 and within(row["date"])
        ),
        ZERO,
    )
    activity = next(
        (q for q in report["quarters"] if q["quarter"] == quarter),
        {"quarter": quarter, "manual_orders": 0, "trades": 0, "order_fees": 0, "deposit_fees": 0},
    )

    closed = [line for line in report["closed"] if within(line["closed_on"])]
    opened = sorted(
        {
            line["name"]
            for line in [*report["positions"], *report["closed"]]
            if within(line["first_buy"])
        }
    )
    statuses = compliance.overview(conn, store.held_names(conn), today)
    attention = [
        {
            "name": item["name"],
            "status": STATUSES.get(item["status"], item["status"]),
            "checked_on": item["checked_on"],
            "state": item["state"],
        }
        for item in statuses["items"]
        if item["group"] == "detenu" and (item["state"] != "a_jour" or item["status"] != "conforme")
    ]

    return {
        "quarter": quarter,
        "name": name(quarter),
        "from": first.isoformat(),
        "to": last.isoformat(),
        "as_of": today.isoformat(),
        "complete": today > last,
        "accounts": [
            {
                "account": a["account"],
                "label": ACCOUNTS.get(a["account"], a["account"]),
                "open_lines": a["open_lines"],
                "net_invested": a["net_invested"],
                "value": a["value"],
                "latent": a["latent"],
                "performance": a["performance"],
                "closed_net": a["closed_net"],
            }
            for a in report["accounts"]
        ],
        "performance": _quarter_performance(conn, first, as_of),
        "counters": counters,
        "deviations": [
            {
                "date": d["date"],
                "name": d["name"],
                "account": d["account"],
                "side": "achat" if d["type"] == "BUY" else "vente" if d["type"] == "SELL" else "",
                "amount": d["amount"],
                "details": [breach["detail"] for breach in d["breaches"]],
                "reason": d["reason"],
            }
            for d in state["deviations"]
            if d["quarter"] == quarter
        ],
        "fees": {
            "manual_orders": activity["manual_orders"],
            "free_trades": activity["trades"] - activity["manual_orders"],
            "order_fees": activity["order_fees"],
            "deposit_fees": activity["deposit_fees"],
            "manual_amount": money(manual_amount),
            "share_of_amount": ratio(dec(str(activity["order_fees"])), manual_amount),
            "total_since_start": report["fees"]["total"],
            "share_of_capital": report["fees"]["share_of_capital"],
        },
        "rotation": [
            {"quarter": q["quarter"], "manual_orders": q["manual_orders"]}
            for q in report["quarters"]
            if q["quarter"] <= quarter
        ],
        "closed": [
            {
                "name": line["name"],
                "account": line["account"],
                "holding_days": line["holding_days"],
                "net": line["net"],
                "net_pct": line["net_pct"],
            }
            for line in closed
        ],
        "opened": opened,
        "positions": [
            {
                "name": p["name"],
                "account": p["account"],
                "value": p["value"],
                "cost": p["cost"],
                "latent_pct": p["latent_pct"],
                "weight": p["weight_total"],
                "halalitude": STATUSES.get(p["halalitude"]["status"], "non renseignée"),
                "halalitude_state": p["halalitude"]["state"],
            }
            for p in sorted(report["positions"], key=lambda p: -(p["weight_total"] or 0))
        ],
        "weights_basis": report["total"]["basis"],
        "halalitude": {**statuses["summary"], "attention": attention},
        "roadmap": [
            {
                "name": item["name"],
                "status": roadmap.STATUSES.get(item["status"], item["status"]),
                "entry_price": item["entry_price"],
                "last_price": item["last_price"],
                "reached": item["reached"],
            }
            for item in roadmap.items(conn, today)["items"]
            if item["status"] in roadmap.ACTIVE
        ],
        "sheets": _sheets(fiches, first, as_of),
    }


# -- Storage -----------------------------------------------------------------------


def _row(row: sqlite3.Row) -> dict:
    return {
        "quarter": row["quarter"],
        "generated_at": row["generated_at"],
        "data": json.loads(row["data"]),
        "commentary": row["commentary"],
        "commentary_at": row["commentary_at"],
        "conversation_id": row["conversation_id"],
        "conclusions": row["conclusions"],
    }


def get(conn: sqlite3.Connection, quarter: str) -> dict | None:
    row = conn.execute("SELECT * FROM reviews WHERE quarter = ?", (quarter,)).fetchone()
    return _row(row) if row else None


def generate(
    conn: sqlite3.Connection, quarter: str, fiches: Path | None, today: date | None = None
) -> dict:
    """Compute the review and keep it. Generating again replaces the figures and
    drops the commentary written on the old ones; the user's conclusions stay."""
    data = build(conn, quarter, fiches, today)
    conn.execute(
        "INSERT INTO reviews (quarter, generated_at, data) VALUES (?, ?, ?) "
        "ON CONFLICT (quarter) DO UPDATE SET generated_at = excluded.generated_at, "
        "data = excluded.data, commentary = NULL, commentary_at = NULL",
        (quarter, datetime.now(UTC).isoformat(timespec="seconds"), json.dumps(data)),
    )
    conn.commit()
    return get(conn, quarter)


def set_conclusions(conn: sqlite3.Connection, quarter: str, text: str) -> bool:
    updated = conn.execute(
        "UPDATE reviews SET conclusions = ? WHERE quarter = ?", (text.strip() or None, quarter)
    ).rowcount
    conn.commit()
    return bool(updated)


def set_commentary(
    conn: sqlite3.Connection, quarter: str, text: str, conversation_id: int | None
) -> None:
    conn.execute(
        "UPDATE reviews SET commentary = ?, commentary_at = ?, conversation_id = ? "
        "WHERE quarter = ?",
        (text, datetime.now(UTC).isoformat(timespec="seconds"), conversation_id, quarter),
    )
    conn.commit()


def delete(conn: sqlite3.Connection, quarter: str) -> bool:
    deleted = conn.execute("DELETE FROM reviews WHERE quarter = ?", (quarter,)).rowcount
    conn.commit()
    return bool(deleted)


def listing(conn: sqlite3.Connection, today: date | None = None) -> dict:
    """The reviews kept, the quarters that can be reviewed, and the one that is due:
    the last finished quarter, when it saw transactions and has no review yet."""
    today = today or date.today()
    kept = [
        {
            "quarter": row["quarter"],
            "name": name(row["quarter"]),
            "generated_at": row["generated_at"],
            "has_commentary": row["commentary"] is not None,
        }
        for row in conn.execute(
            "SELECT quarter, generated_at, commentary FROM reviews ORDER BY quarter DESC"
        )
    ]
    bounds_of_data = conn.execute("SELECT MIN(date), MAX(date) FROM transactions").fetchone()
    quarters: list[str] = []
    if bounds_of_data[0]:
        quarter, oldest = quarter_of(today.isoformat()), quarter_of(bounds_of_data[0])
        while quarter >= oldest:
            quarters.append(quarter)
            quarter = preceding(quarter)
    last_finished = preceding(quarter_of(today.isoformat()))
    due = (
        last_finished
        if last_finished in quarters and last_finished not in {r["quarter"] for r in kept}
        else None
    )
    return {
        "reviews": kept,
        "quarters": [{"quarter": q, "name": name(q)} for q in quarters],
        "due": {"quarter": due, "name": name(due)} if due else None,
    }


# -- Commentary --------------------------------------------------------------------

COMMENTARY_REQUEST = """\
Revue {name} : commentaire demandé.

Voici la revue trimestrielle calculée par l'application. Rédige son commentaire, en 400 mots au \
plus, avec ces quatre parties :
1. Ce que disent les chiffres : trois à cinq constats, chacun appuyé sur un chiffre de la revue.
2. Les écarts aux règles : ce qu'ils ont coûté, et ceux qui attendent encore un motif.
3. Deux scénarios pour le trimestre suivant, l'un favorable, l'autre défavorable, et ce qui \
ferait pencher vers l'un ou l'autre.
4. Points à vérifier : Halalitude à relever ou à revérifier, cours manquants, données incomplètes.

N'ajoute aucun chiffre qui n'est pas dans la revue, sauf à le lire par un outil. Ne donne aucune \
consigne d'achat ou de vente, et n'écris rien dans le journal ni sur la feuille de route.

"""
MAX_REQUEST_CHARS = 60_000


class CommentaryError(Exception):
    """The assistant could not write the commentary; the message says why."""


def comment(conn: sqlite3.Connection, llm, api_key: str, quarter: str, model: str | None) -> dict:
    """Ask the assistant to read the review. The exchange is an ordinary
    conversation: it is counted in the month's usage and can be continued from
    the assistant's page."""
    from .assistant import chat  # local import: the assistant reads reviews through tools

    kept = get(conn, quarter)
    if kept is None:
        raise CommentaryError("Revue introuvable.")
    request = COMMENTARY_REQUEST.format(name=name(quarter)) + markdown({**kept, "commentary": None})
    conversation = chat.create(conn, model)
    problems = [
        event["message"]
        for event in chat.send(
            conn, llm, api_key, conversation, request, model=model, max_chars=MAX_REQUEST_CHARS
        )
        if event["type"] == "error"
    ]
    last = conn.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant' "
        "ORDER BY id DESC LIMIT 1",
        (conversation,),
    ).fetchone()
    text = "".join(
        block.get("text", "")
        for block in (json.loads(last["content"]) if last else [])
        if block.get("type") == "text"
    ).strip()
    if not text:
        chat.delete(conn, conversation)
        raise CommentaryError(problems[0] if problems else "L'assistant n'a rien répondu.")
    set_commentary(conn, quarter, text, conversation)
    return get(conn, quarter)


# -- Readable version --------------------------------------------------------------


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return [*lines, ""]


def markdown(review: dict) -> str:
    """The review as a document to keep or to hand to the assistant."""
    data = review["data"]
    perf = data["performance"]
    out = [
        f"# Revue trimestrielle — {data['name']}",
        "",
        f"Du {_day(data['from'])} au {_day(data['to'])}, chiffres arrêtés au "
        f"{_day(data['as_of'])}"
        + ("." if data["complete"] else " : le trimestre n'est pas terminé.")
        + " Calculée par l'application à partir des transactions importées et des cours "
        "relevés ; les valeurs sont des estimations.",
        "",
        "## 1. Comptes",
        "",
    ]
    out += _table(
        ["Compte", "Lignes", "Capital net engagé", "Valeur", "Résultat latent", "Performance"],
        [
            [
                a["label"],
                str(a["open_lines"]),
                _euro(a["net_invested"]),
                _euro(a["value"]),
                _signed(a["latent"]),
                _pct(a["performance"]),
            ]
            for a in data["accounts"]
        ],
    )

    out += ["## 2. Le trimestre", ""]
    if perf["available"]:
        rows = [
            ["Valeur au début", _euro(perf["start_value"])],
            ["Achats", _euro(perf["bought"])],
            ["Ventes", _euro(perf["sold"])],
            ["Valeur à la fin", _euro(perf["end_value"])],
            ["Gain ou perte du trimestre", _signed(perf["gain"])],
            ["Performance, achats et ventes neutralisés", _pct(perf["change"])],
        ]
        if perf["benchmark"]:
            rows.append(
                [f"{perf['benchmark']['label']}, même période", _pct(perf["benchmark"]["change"])]
            )
        out += _table(["", "Montant"], rows)
        if perf["at_cost"]:
            out += [
                f"{_euro(perf['at_cost'])} sont comptés au prix de revient, faute de cours.",
                "",
            ]
    else:
        out += ["Pas de valeur connue sur ce trimestre : charger l'historique des cours.", ""]

    out += ["## 3. Activité face aux règles", ""]
    out += _table(
        ["Règle", "Constaté", "Prévu", "Écarts"],
        [[c["label"], c["count"], c["limit"], str(c["breaches"])] for c in data["counters"]],
    )
    if data["deviations"]:
        out += ["### Écarts du trimestre", ""]
        out += _table(
            ["Date", "Titre", "Écart", "Motif"],
            [
                [
                    _day(d["date"]),
                    d["name"] or "—",
                    " ; ".join(d["details"]),
                    d["reason"] or "**sans motif**",
                ]
                for d in data["deviations"]
            ],
        )
    else:
        out += ["Aucun écart aux règles sur le trimestre.", ""]

    fees = data["fees"]
    out += ["## 4. Frais", ""]
    out += _table(
        ["", "Trimestre"],
        [
            ["Ordres manuels", str(fees["manual_orders"])],
            ["Exécutions sans frais", str(fees["free_trades"])],
            ["Frais d'ordre", _euro(fees["order_fees"])],
            [
                "Frais d'ordre rapportés aux montants des ordres",
                _pct(fees["share_of_amount"], False),
            ],
            ["Frais de rechargement", _euro(fees["deposit_fees"])],
        ],
    )
    out += [
        f"Depuis l'ouverture : {_euro(fees['total_since_start'])} de frais, soit "
        f"{_pct(fees['share_of_capital'], False)} du capital apporté.",
        "",
        "Ordres manuels par trimestre : "
        + " / ".join(str(q["manual_orders"]) for q in data["rotation"])
        + ".",
        "",
    ]

    out += ["## 5. Lignes ouvertes et soldées dans le trimestre", ""]
    out += [
        "Nouvelles lignes : " + (", ".join(data["opened"]) if data["opened"] else "aucune") + ".",
        "",
    ]
    if data["closed"]:
        out += _table(
            ["Ligne soldée", "Compte", "Durée", "Résultat net"],
            [
                [
                    line["name"],
                    ACCOUNTS.get(line["account"], line["account"]),
                    f"{line['holding_days']} j" if line["holding_days"] is not None else "—",
                    f"{_signed(line['net'])} ({_pct(line['net_pct'])})",
                ]
                for line in data["closed"]
            ],
        )
    else:
        out += ["Aucune ligne soldée.", ""]

    basis = "valeur" if data["weights_basis"] == "value" else "prix de revient"
    out += [f"## 6. Portefeuille au {_day(data['as_of'])}", ""]
    out += _table(
        ["Titre", "Compte", f"Poids ({basis})", "Résultat latent", "Halalitude"],
        [
            [
                p["name"],
                ACCOUNTS.get(p["account"], p["account"]),
                _pct(p["weight"], False),
                _pct(p["latent_pct"]),
                p["halalitude"]
                + (" (à revérifier)" if p["halalitude_state"] == "a_reverifier" else ""),
            ]
            for p in data["positions"]
        ],
    )

    halal = data["halalitude"]
    out += ["## 7. Halalitude", ""]
    if halal["attention"]:
        out += _table(
            ["Titre détenu", "Statut relevé", "Relevé le"],
            [[i["name"], i["status"], _day(i["checked_on"])] for i in halal["attention"]],
        )
    else:
        out += ["Toutes les lignes détenues ont un statut halal à jour.", ""]

    out += ["## 8. Feuille de route", ""]
    if data["roadmap"]:
        out += _table(
            ["Cible", "Statut", "Cours d'entrée", "Dernier cours", "Atteint"],
            [
                [
                    item["name"],
                    item["status"],
                    _euro(item["entry_price"]),
                    _euro(item["last_price"]),
                    "oui" if item["reached"] else "non",
                ]
                for item in data["roadmap"]
            ],
        )
    else:
        out += ["Aucune cible en cours.", ""]

    out += ["## 9. Fiches du trimestre", ""]
    if data["sheets"]:
        out += _table(
            ["Entreprise", "Fiche du", "Note sur 20", "Libellé"],
            [
                [
                    s["name"] or "—",
                    _day(s["date"]),
                    f"{s['score']:g}".replace(".", ","),
                    s["label"] or "—",
                ]
                for s in data["sheets"]
            ],
        )
        out += ["Une note trie des candidats ; elle ne dit rien de la Halalitude.", ""]
    else:
        out += ["Aucune fiche datée de ce trimestre.", ""]

    following_name = name(following(data["quarter"]))
    out += [f"## 10. Repères pour {following_name}", ""]
    out += _table(
        ["Indicateur", data["name"], f"Règle en vigueur pour {following_name}"],
        [[c["label"], c["count"], c["next_limit"]] for c in data["counters"]],
    )

    if review.get("commentary"):
        out += ["## Commentaire de l'assistant", "", review["commentary"].strip(), ""]
    if review.get("conclusions"):
        out += ["## Mes conclusions", "", review["conclusions"].strip(), ""]
    out += [
        "*Document d'analyse personnelle, pas un conseil en investissement. La Halalitude se "
        "vérifie avant tout achat.*",
        "",
    ]
    return "\n".join(out)
