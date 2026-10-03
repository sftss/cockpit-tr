"""Order tickets: an order prepared and checked here, placed elsewhere.

A ticket says what the user intends to buy or sell, runs the controls, and
shows what to copy into the broker's own application. The application never
sends an order and has no access to the broker; once the order shows up in an
imported export, the ticket is matched with that transaction.

One control stops a ticket: a purchase without an up-to-date "halal" status.
The portfolio rules never stop anything: exceeding one asks for a written
reason, exactly as they do after the fact on imported transactions. They are
measured by the same code (`rules.evaluate`), on the stored transactions plus
the tickets that are ready, so a ticket and the rules page always agree.
"""

from __future__ import annotations

import json
import re
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from . import compliance, portfolio, rules, store
from .market.provider import ProviderError
from .market.service import Market, choose_listing
from .money import SHARE_EPSILON, ZERO, cents, dec, money, qty, ratio

STATUSES = {
    "brouillon": "Brouillon",
    "pret": "Prêt",
    "execute": "Exécuté",
    "abandonne": "Abandonné",
}
OPEN = ("brouillon", "pret")
SIDES = {"BUY": "Achat", "SELL": "Vente"}
ORDER_TYPES = {"marche": "Au marché", "limite": "À cours limité"}
# The broker's public price for a manual order; each ticket can say otherwise.
DEFAULT_FEE = Decimal("1")
# Asset classes as the transaction export names them.
INSTRUMENTS = {"STOCK": "Action", "FUND": "ETF"}
# ISIN prefixes of the European Union and of the European Economic Area.
EEA = frozenset(
    [
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
        "IS",
        "LI",
        "NO",
    ]
)
ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
# An executed quantity this close to the planned one is taken for the same order.
QUANTITY_TOLERANCE = Decimal("0.10")
SHARE_STEP = Decimal("0.000001")
PRICE_STEP = Decimal("0.0001")
# Beyond this, a ready ticket is no longer matched without asking: an order placed
# that long after is more likely another decision than this one.
AUTO_MATCH_DAYS = 30
# No order of this portfolio comes near it: a larger number is a typing mistake.
LARGEST = Decimal("1000000000")

# How a control ends: "bloquant" stops the ticket, "motif" asks for a written
# reason, "avertissement" and "info" ask for nothing, "attente" and "erreur"
# mean the ticket is not filled in properly yet.
NOT_READY = ("attente", "erreur")


class TicketError(ValueError):
    """The ticket cannot be saved or moved as asked; the message is for the user."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _text(value: object) -> str | None:
    return str(value).strip() or None if value is not None else None


def _positive(value: object, what: str, zero: bool = False) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = dec(str(value).replace(",", ".").replace(" ", ""))
    except ValueError as exc:
        raise TicketError(f"{what} : nombre illisible.") from exc
    if not number.is_finite() or number > LARGEST:
        raise TicketError(f"{what} : nombre illisible.")
    if number < 0 or (number == 0 and not zero):
        raise TicketError(f"{what} : attendu un nombre positif.")
    return number


def _euros(value: Decimal) -> str:
    return f"{value:,.2f} €".replace(",", " ").replace(".", ",")


def _plain(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


def _percent(value: Decimal) -> str:
    return f"{value:.1f} %".replace(".", ",")


def _rank(n: int) -> str:
    return "1er" if n == 1 else f"{n}e"


def _day(iso: str | None) -> str:
    return date.fromisoformat(iso[:10]).strftime("%d/%m/%Y") if iso else "date inconnue"


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


# -- One ticket, as numbers ----------------------------------------------------


@dataclass(frozen=True)
class Order:
    id: int
    isin: str
    name: str
    account: str
    side: str
    shares: Decimal | None
    unit: Decimal | None  # the price the amount is counted with
    fee: Decimal
    target: int | None
    status: str
    ready_at: str | None

    @property
    def complete(self) -> bool:
        return self.shares is not None and self.unit is not None

    @property
    def amount(self) -> Decimal | None:
        """To the cent, as the broker settles it: a quantity derived from an
        amount gives that amount back, not a hair less."""
        return cents(self.shares * self.unit) if self.complete else None


def _unit(row: sqlite3.Row | dict) -> Decimal | None:
    """A limit order is counted at its limit, any other at the indicative price."""
    chosen = row["limit_price"] if row["order_type"] == "limite" else row["price"]
    return dec(chosen) if chosen else None


def _order(row: sqlite3.Row) -> Order:
    return Order(
        id=row["id"],
        isin=row["isin"],
        name=row["name"],
        account=row["account_id"],
        side=row["side"],
        shares=dec(row["shares"]) if row["shares"] else None,
        unit=_unit(row),
        fee=dec(row["fee"]),
        target=row["roadmap_item_id"],
        status=row["status"],
        ready_at=row["ready_at"],
    )


# -- What the controls look at -------------------------------------------------


@dataclass
class Context:
    """Everything the controls read, gathered once for a whole list of tickets."""

    today: date
    rows: list
    rules: list[rules.Rule]
    points: list[tuple[str, Decimal]]
    report: dict
    statuses: dict[str, sqlite3.Row]
    classes: dict[str, str]
    targets: dict[int, sqlite3.Row]
    ready: list[Order]

    def value_on(self, when: str) -> Decimal | None:
        index = bisect_right([point[0] for point in self.points], when) - 1
        return self.points[index][1] if index >= 0 else None


def context(
    conn: sqlite3.Connection, fiches: Path | None = None, today: date | None = None
) -> Context:
    history = store.value_history(conn)
    classes = {
        row["isin"]: row["asset_class"]
        for row in conn.execute("SELECT isin, asset_class FROM instruments")
        if row["asset_class"]
    }
    for isin in store.universe(fiches):  # the public list only holds companies
        classes.setdefault(isin, "STOCK")
    ready = conn.execute("SELECT * FROM tickets WHERE status = 'pret' ORDER BY ready_at, id")
    return Context(
        today=today or date.today(),
        rows=store.all_transactions(conn),
        rules=rules.list_rules(conn),
        points=[(point["date"], Decimal(str(point["value"]))) for point in history["points"]],
        report=store.current_report(conn),
        statuses=compliance.latest(conn),
        classes=classes,
        targets={row["id"]: row for row in conn.execute("SELECT * FROM roadmap_items")},
        ready=[_order(row) for row in ready],
    )


def _as_transaction(order: Order, day: str, rank: int, asset_class: str) -> dict:
    """The ticket as the transaction it would become, placed after today's real ones."""
    stamp = datetime.fromisoformat(f"{day}T23:00:00+00:00") + timedelta(seconds=rank)
    buying = order.side == "BUY"
    return {
        "transaction_id": f"ticket-{order.id}",
        "datetime": stamp.isoformat(),
        "date": day,
        "account_id": order.account,
        "category": "TRADING",
        "type": order.side,
        "asset_class": asset_class,
        "name": order.name,
        "isin": order.isin,
        "shares": str(order.shares if buying else -order.shares),
        "price": str(order.unit),
        "amount": str(-order.amount if buying else order.amount),
        "fee": str(-order.fee),  # exported negative when paid
        "tax": "0",
    }


def _held(ctx: Context, account: str, isin: str) -> Decimal:
    line = portfolio.build_lines(ctx.rows).get((account, isin))
    return line.shares if line and line.is_open else ZERO


def _ahead(ctx: Context, order: Order) -> list[Order]:
    """The ready tickets that count as passed before this one: all of them for
    a draft, those made ready earlier for a ticket that is ready itself."""
    queue = [other for other in ctx.ready if other.id != order.id and other.complete]
    if order.status == "pret":
        mine = (order.ready_at or "", order.id)
        queue = [other for other in queue if (other.ready_at or "", other.id) < mine]
    return queue


def _planned(ctx: Context, queue: list[Order]) -> list[dict]:
    day = ctx.today.isoformat()
    return [
        _as_transaction(item, day, rank, ctx.classes.get(item.isin, ""))
        for rank, item in enumerate(queue)
    ]


def _held_after_ready(ctx: Context, order: Order) -> Decimal:
    """What would be held on the account once the ready tickets ahead are passed."""
    planned = _planned(ctx, _ahead(ctx, order))
    line = portfolio.build_lines([*ctx.rows, *planned]).get((order.account, order.isin))
    return line.shares if line and line.is_open else ZERO


def _check(key: str, label: str, state: str, detail: str) -> dict:
    return {"key": key, "label": label, "state": state, "detail": detail}


def _halalitude(ctx: Context, order: Order) -> dict:
    label = "Halalitude"
    seen = compliance.view(ctx.statuses.get(order.isin), ctx.today)
    said = compliance.STATUSES.get(seen["status"] or "", "")
    if order.side == "SELL":
        told = (
            f"Statut relevé : {said.lower()}, le {_day(seen['checked_on'])}."
            if said
            else "Statut non relevé."
        )
        return _check("halalitude", label, "info", f"{told} Une vente n'est jamais arrêtée.")
    if seen["state"] == "non_renseigne":
        return _check(
            "halalitude",
            label,
            "bloquant",
            "Statut non relevé. Le relever dans la page Halalitude avant tout achat.",
        )
    if seen["status"] != "conforme":
        return _check(
            "halalitude",
            label,
            "bloquant",
            f"Statut relevé le {_day(seen['checked_on'])} : {said.lower()}. "
            "Un achat demande un statut halal.",
        )
    if seen["state"] == "a_reverifier":
        return _check(
            "halalitude",
            label,
            "bloquant",
            f"Relevé du {_day(seen['checked_on'])}, de plus de "
            f"{compliance.VALIDITY_DAYS} jours : à relever de nouveau avant l'achat.",
        )
    return _check(
        "halalitude",
        label,
        "ok",
        f"Halal, relevé le {_day(seen['checked_on'])}, valable jusqu'au {_day(seen['due_on'])}.",
    )


def _instrument(ctx: Context, order: Order) -> dict:
    known = INSTRUMENTS.get(ctx.classes.get(order.isin, ""))
    if known:
        return _check("instrument", "Instrument", "ok", f"{known}.")
    return _check(
        "instrument",
        "Instrument",
        "avertissement",
        "Type non connu de l'application. Les tickets ne portent que sur des actions et des "
        "ETF : à confirmer.",
    )


def _pea(ctx: Context, order: Order) -> dict | None:
    if order.account != "PEA" or order.side != "BUY":
        return None
    label, country = "Éligibilité PEA", order.isin[:2]
    if country not in EEA:
        return _check(
            "pea",
            label,
            "avertissement",
            f"ISIN « {country} », hors UE et EEE : ce titre n'est sans doute pas éligible au PEA.",
        )
    if ctx.classes.get(order.isin) == "FUND":
        return _check(
            "pea",
            label,
            "info",
            "Pour un ETF, l'éligibilité dépend du fonds : elle se lit dans Trade Republic.",
        )
    return _check(
        "pea",
        label,
        "ok",
        "ISIN d'un pays de l'UE ou de l'EEE. L'éligibilité réelle se lit dans Trade Republic.",
    )


def _rule_checks(ctx: Context, order: Order) -> list[dict]:
    """The portfolio rules, as if the ticket were already a transaction.

    Tickets that are ready count as passed, in the order they were made ready;
    a draft comes after all of them.
    """
    day = ctx.today.isoformat()
    ahead = _ahead(ctx, order)
    planned = _planned(ctx, [*ahead, order])
    held = _held_after_ready(ctx, order)

    deviations, quarters = rules.evaluate([*ctx.rows, *planned], ctx.rules, ctx.value_on)
    breached = {
        breach["kind"]: breach["detail"]
        for deviation in deviations
        if deviation["transaction_id"] == f"ticket-{order.id}"
        for breach in deviation["breaches"]
    }
    counter = quarters[portfolio.quarter_of(day)]
    checks: list[dict] = []

    def measure(kind: str, passing) -> None:
        rule = rules.active(ctx.rules, kind, order.account, day)
        if rule is None:
            return
        label = rules.KINDS[kind]["label"]
        if kind in breached:
            checks.append(_check(kind, label, "motif", _sentence(breached[kind]) + "."))
        else:
            checks.append(_check(kind, label, "ok", passing(rule.value)))

    manual = order.fee > 0
    if manual:
        measure(
            "ordres_manuels_trimestre",
            lambda limit: (
                f"{_rank(counter['ordres_manuels'])} ordre manuel du trimestre, "
                f"pour {_plain(limit)} prévus."
            ),
        )
        measure(
            "frais_trimestre",
            lambda limit: (
                f"Frais d'ordre du trimestre portés à {_euros(counter['frais'])}, "
                f"pour {_euros(limit)} prévus."
            ),
        )
    if order.side == "BUY":
        if manual:
            measure(
                "achat_minimum",
                lambda limit: (
                    f"Achat de {_euros(order.amount)}, pour un minimum de {_euros(limit)}."
                ),
            )
        if held < SHARE_EPSILON:
            worth = ctx.value_on(day)
            measure(
                "nouvelle_ligne_valeur_minimum",
                lambda limit: (
                    f"Nouvelle ligne ; le portefeuille vaut {_euros(worth or ZERO)}, "
                    f"pour un seuil de {_euros(limit)}."
                ),
            )
        ceiling = rules.active(ctx.rules, "poids_maximum", None, day)
        if ceiling is not None:
            basis = ctx.report["total"]["basis"]
            total = Decimal(str(ctx.report["total"]["amount"] or 0))
            current = sum(
                (
                    Decimal(str(position[basis]))
                    for position in ctx.report["positions"]
                    if position["account"] == order.account and position["isin"] == order.isin
                ),
                ZERO,
            )
            # The ready tickets ahead count as passed: their purchases are in the
            # portfolio, and on this line when they are for the same title.
            for other in ahead:
                signed = other.amount if other.side == "BUY" else -other.amount
                total += signed
                if (other.account, other.isin) == (order.account, order.isin):
                    current += signed
            total = max(total, ZERO)
            weight = (max(current, ZERO) + order.amount) / (total + order.amount) * 100
            checks.append(
                _check(
                    "poids_maximum",
                    rules.KINDS["poids_maximum"]["label"],
                    "motif" if weight > ceiling.value else "ok",
                    f"Poids de la ligne après l'achat : {_percent(weight)}, "
                    f"pour {_plain(ceiling.value)} % au plus.",
                )
            )
    else:
        measure(
            "ventes_trimestre",
            lambda limit: (
                f"{_rank(counter['ventes'])} vente du trimestre, pour {_plain(limit)} prévues."
            ),
        )
        if held - order.shares < SHARE_EPSILON:
            measure(
                "lignes_soldees_trimestre",
                lambda limit: (
                    f"{_rank(counter['lignes_soldees'])} ligne soldée du trimestre, "
                    f"pour {_plain(limit)} prévues."
                ),
            )
    # Whatever the rules found that was not reported above still asks for a reason.
    reported = {check["key"] for check in checks}
    for kind, detail in breached.items():
        if kind not in reported:
            checks.append(
                _check(kind, rules.KINDS[kind]["label"], "motif", _sentence(detail) + ".")
            )
    return checks


def _roadmap(ctx: Context, order: Order) -> dict | None:
    if order.side != "BUY":
        return None
    label = "Feuille de route"
    target = ctx.targets.get(order.target) if order.target else None
    if target is not None and target["isin"] and target["isin"].upper() != order.isin:
        target = None  # the target was pointed at another title since
    if target is None:
        return _check(
            "feuille_de_route",
            label,
            "avertissement",
            "Hors feuille de route : le ticket n'est lié à aucune cible.",
        )
    if target["status"] != "prevu":
        said = {"idee": "idée", "execute": "exécuté", "abandonne": "abandonné"}[target["status"]]
        return _check(
            "feuille_de_route",
            label,
            "avertissement",
            f"Hors feuille de route : la cible « {target['name']} » est au statut "
            f"« {said} », pas « prévu ».",
        )
    return _check("feuille_de_route", label, "ok", f"Cible prévue : {target['name']}.")


def _cash(ctx: Context, order: Order) -> dict | None:
    if order.side != "BUY":
        return None
    account = next((a for a in ctx.report["accounts"] if a["account"] == order.account), None)
    cash = Decimal(str(account["cash_estimate"])) if account else ZERO
    needed = order.amount + order.fee
    if cash < needed:
        return _check(
            "especes",
            "Espèces",
            "avertissement",
            f"Espèces estimées du compte : {_euros(cash)}, pour {_euros(needed)} à payer. "
            "C'est une estimation.",
        )
    return _check("especes", "Espèces", "ok", f"Espèces estimées du compte : {_euros(cash)}.")


def controls(ctx: Context, order: Order) -> list[dict]:
    checks = [_halalitude(ctx, order), _instrument(ctx, order), _pea(ctx, order)]
    if not order.complete:
        checks.append(
            _check(
                "saisie",
                "Quantité et cours",
                "attente",
                "Saisir la quantité et le cours pour contrôler les règles.",
            )
        )
        return [check for check in checks if check]
    if order.side == "SELL":
        held = _held_after_ready(ctx, order)
        if order.shares > held + SHARE_EPSILON:
            checks.append(
                _check(
                    "quantite",
                    "Quantité détenue",
                    "erreur",
                    f"Vente de {_plain(order.shares)} pour {_plain(held)} détenus sur ce compte, "
                    "une fois passées les ventes déjà prêtes.",
                )
            )
            return [check for check in checks if check]
    checks += _rule_checks(ctx, order)
    if order.fee == 0:
        checks.append(
            _check(
                "ordre_sans_frais",
                "Ordre sans frais",
                "avertissement",
                "Un ordre sans frais n'est pas compté comme un ordre manuel : les règles sur les "
                "ordres, les frais et l'achat minimal ne sont pas mesurées. Un ordre passé à la "
                "main chez Trade Republic a des frais.",
            )
        )
    checks += [_roadmap(ctx, order), _cash(ctx, order)]
    share = order.fee / order.amount * 100 if order.amount else ZERO
    checks.append(
        _check(
            "frais",
            "Frais de l'ordre",
            "info",
            f"{_euros(order.fee)}, soit {_percent(share)} du montant.",
        )
    )
    return [check for check in checks if check]


def _verdict(checks: list[dict], reason: str | None) -> dict:
    states = {check["state"] for check in checks}
    blocked, needs_reason = "bloquant" in states, "motif" in states
    stop = None
    if blocked:
        found = next(check["detail"] for check in checks if check["state"] == "bloquant")
        stop = f"{found} Le ticket s'arrête : aucun motif ne le débloque."
    elif states & set(NOT_READY):
        stop = next(check["detail"] for check in checks if check["state"] in NOT_READY)
    elif needs_reason and not reason:
        stop = "Un contrôle demande un motif écrit avant de passer le ticket à « prêt »."
    return {
        "blocked": blocked,
        "needs_reason": needs_reason,
        "can_be_ready": stop is None,
        "stop": stop,
    }


# -- What the screens show -----------------------------------------------------


def _trade(row: sqlite3.Row) -> dict:
    shares, amount = abs(dec(row["shares"])), abs(dec(row["amount"]))
    return {
        "transaction_id": row["transaction_id"],
        "date": row["date"],
        "shares": qty(shares),
        "price": float((amount / shares).quantize(Decimal("0.0001"))) if shares else None,
        "amount": money(amount),
        "fee": money(-dec(row["fee"])),
    }


def _free_trades(conn: sqlite3.Connection, row: sqlite3.Row) -> list[sqlite3.Row]:
    """Transactions the user may say are this ticket's order: same instrument,
    account and direction, since the ticket exists, not matched with another one."""
    return conn.execute(
        "SELECT transaction_id, date, datetime, shares, amount, fee FROM transactions "
        "WHERE isin = ? AND account_id = ? AND type = ? AND date >= ? AND transaction_id NOT IN "
        "(SELECT transaction_id FROM tickets WHERE transaction_id IS NOT NULL) ORDER BY datetime",
        (row["isin"], row["account_id"], row["side"], row["created_at"][:10]),
    ).fetchall()


def _halal_on(conn: sqlite3.Connection, isin: str, day: str) -> bool:
    """Whether the latest reading known that day was "halal" and still valid."""
    last = conn.execute(
        "SELECT status, checked_on FROM compliance WHERE isin = ? AND checked_on <= ? "
        "ORDER BY checked_on DESC LIMIT 1",
        (isin, day),
    ).fetchone()
    if last is None or last["status"] != "conforme":
        return False
    age = date.fromisoformat(day) - date.fromisoformat(last["checked_on"])
    return age.days <= compliance.VALIDITY_DAYS


def _same_order(conn: sqlite3.Connection, row: sqlite3.Row, tx: sqlite3.Row) -> bool:
    """Sure enough to match without asking. Anything less is left to the user.

    The transaction was passed after the ticket was made ready and not long
    after; both paid a fee (a free execution is a savings plan, not this
    order); the quantity is close to the plan; a limit was respected; the user
    did not already say it was another order; and, for a purchase, the status
    was "halal" and valid on the day of the order.
    """
    planned = dec(row["shares"]) if row["shares"] else None
    if planned is None or not row["ready_at"]:
        return False
    if tx["transaction_id"] in json.loads(row["rejected"] or "[]"):
        return False
    if dec(row["fee"]) == 0 or dec(tx["fee"]) == 0:
        return False
    try:
        passed = datetime.fromisoformat(str(tx["datetime"]).replace("Z", "+00:00"))
        if passed.tzinfo is None:
            passed = passed.replace(tzinfo=UTC)
        ready = datetime.fromisoformat(row["ready_at"])
    except (TypeError, ValueError):
        return False  # an unreadable time: not sure enough
    if not ready <= passed <= ready + timedelta(days=AUTO_MATCH_DAYS):
        return False
    shares, amount = abs(dec(tx["shares"])), abs(dec(tx["amount"]))
    if shares == 0 or abs(shares - planned) > planned * QUANTITY_TOLERANCE:
        return False
    if row["order_type"] == "limite" and row["limit_price"]:
        limit, paid = dec(row["limit_price"]), amount / shares
        slack = limit * Decimal("0.001")  # the export rounds prices
        if (row["side"] == "BUY" and paid > limit + slack) or (
            row["side"] == "SELL" and paid < limit - slack
        ):
            return False
    return row["side"] != "BUY" or _halal_on(conn, row["isin"], tx["date"])


def view(conn: sqlite3.Connection, row: sqlite3.Row, ctx: Context) -> dict:
    order = _order(row)
    live = row["status"] in OPEN
    checks = controls(ctx, order) if live else json.loads(row["checks"] or "[]")
    target = ctx.targets.get(order.target) if order.target else None
    executed = None
    if row["transaction_id"]:
        tx = conn.execute(
            "SELECT transaction_id, date, shares, amount, fee FROM transactions "
            "WHERE transaction_id = ?",
            (row["transaction_id"],),
        ).fetchone()
        executed = _trade(tx) if tx else None
    return {
        "id": row["id"],
        "isin": row["isin"],
        "name": row["name"],
        "account": row["account_id"],
        "side": row["side"],
        "shares": qty(order.shares),
        "order_type": row["order_type"],
        "limit_price": float(dec(row["limit_price"])) if row["limit_price"] else None,
        "price": float(dec(row["price"])) if row["price"] else None,
        "price_at": row["price_at"],
        "unit": float(order.unit) if order.unit is not None else None,
        "amount": money(order.amount),
        "fee": money(order.fee),
        "fee_share": ratio(order.fee, order.amount) if order.amount else None,
        "reason": row["reason"],
        "status": row["status"],
        "proposed_by": row["proposed_by"],
        "created_at": row["created_at"],
        "ready_at": row["ready_at"],
        "closed_at": row["closed_at"],
        "held": qty(_held(ctx, order.account, order.isin)),
        "instrument": INSTRUMENTS.get(ctx.classes.get(order.isin, "")),
        "halalitude": compliance.view(ctx.statuses.get(order.isin), ctx.today),
        "target": {
            "id": target["id"],
            "name": target["name"],
            "status": target["status"],
            "thesis": target["thesis"],
            "entry_condition": target["entry_condition"],
        }
        if target
        else None,
        "controls": checks,
        **(
            _verdict(checks, row["reason"])
            if live
            else {"blocked": False, "needs_reason": False, "can_be_ready": False, "stop": None}
        ),
        "candidates": [_trade(tx) for tx in _free_trades(conn, row)]
        if row["status"] == "pret"
        else [],
        "executed": executed,
    }


def _row(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise KeyError(ticket_id)
    return row


def get(
    conn: sqlite3.Connection, ticket_id: int, fiches: Path | None = None, today: date | None = None
) -> dict:
    refresh(conn, today)
    return view(conn, _row(conn, ticket_id), context(conn, fiches, today))


def refresh(conn: sqlite3.Connection, today: date | None = None) -> list[int]:
    """A purchase that was ready goes back to draft once its status is no longer
    an up-to-date "halal": nothing stays ready on a reading that has expired."""
    today = today or date.today()
    statuses = compliance.latest(conn)
    back = []
    for row in conn.execute("SELECT id, isin FROM tickets WHERE status = 'pret' AND side = 'BUY'"):
        seen = compliance.view(statuses.get(row["isin"]), today)
        if seen["status"] != "conforme" or seen["state"] != "a_jour":
            back.append(row["id"])
    for ticket_id in back:
        conn.execute(
            "UPDATE tickets SET status = 'brouillon', ready_at = NULL, checks = NULL, "
            "updated_at = ? WHERE id = ?",
            (_now(), ticket_id),
        )
    if back:
        conn.commit()
    return back


def summary(conn: sqlite3.Connection, today: date | None = None) -> dict:
    """How many tickets are in each state: what the home page says in one line."""
    refresh(conn, today)
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM tickets GROUP BY status").fetchall())
    return {status: counts.get(status, 0) for status in STATUSES}


def listing(
    conn: sqlite3.Connection, fiches: Path | None = None, today: date | None = None
) -> dict:
    refresh(conn, today)
    ctx = context(conn, fiches, today)
    order = (
        "CASE status WHEN 'pret' THEN 0 WHEN 'brouillon' THEN 1 WHEN 'execute' THEN 2 ELSE 3 END"
    )
    rows = conn.execute(
        f"SELECT * FROM tickets ORDER BY {order}, COALESCE(closed_at, updated_at) DESC, id DESC"
    ).fetchall()
    return {
        "statuses": STATUSES,
        "sides": SIDES,
        "order_types": ORDER_TYPES,
        "default_fee": float(DEFAULT_FEE),
        "tickets": [view(conn, row, ctx) for row in rows],
    }


# -- Writing --------------------------------------------------------------------


def _known_price(
    conn: sqlite3.Connection, isin: str, target: sqlite3.Row | None
) -> tuple[str | None, str | None]:
    """The latest price in euros this database already holds, with its date."""
    quote = conn.execute(
        "SELECT price_eur, fetched_at FROM quotes WHERE isin = ?", (isin,)
    ).fetchone()
    if quote:
        return quote["price_eur"], quote["fetched_at"]
    last = conn.execute(
        "SELECT price, date FROM prices WHERE isin = ? ORDER BY date DESC LIMIT 1", (isin,)
    ).fetchone()
    if last:
        return last["price"], last["date"]
    if target is not None and target["last_price"]:
        return target["last_price"], target["last_price_at"]
    return None, None


def _target(conn: sqlite3.Connection, item_id: object) -> sqlite3.Row | None:
    if item_id in (None, ""):
        return None
    row = conn.execute("SELECT * FROM roadmap_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise TicketError("Cible de la feuille de route introuvable.")
    return row


def _shares_held(conn: sqlite3.Connection, account: str, isin: str) -> Decimal:
    line = portfolio.build_lines(store.all_transactions(conn)).get((account, isin))
    return line.shares if line and line.is_open else ZERO


# What an update may leave out or empty: the stored value is kept. The others
# are cleared by an explicit null.
KEPT_WHEN_EMPTY = ("isin", "name", "side", "account", "order_type", "fee")


def _clean(
    conn: sqlite3.Connection, data: dict, before: sqlite3.Row | None, fiches: Path | None
) -> dict:
    """Fields of a ticket from what was typed, over what it already held."""

    def given(key: str, column: str | None = None) -> object:
        if key in data and not (key in KEPT_WHEN_EMPTY and data[key] in (None, "")):
            return data[key]
        return before[column or key] if before is not None else None

    isin = (_text(given("isin")) or "").upper()
    if before is not None and isin != before["isin"]:
        raise TicketError("Le titre d'un ticket ne se change pas : créer un autre ticket.")
    target = _target(conn, given("roadmap_item_id"))
    if not isin and target is not None:
        isin = (target["isin"] or "").upper()
    if not isin:
        raise TicketError(
            "La cible n'a pas de code ISIN : le renseigner dans la feuille de route."
            if target
            else "Le code ISIN du titre est obligatoire."
        )
    if not ISIN.fullmatch(isin):
        raise TicketError("Code ISIN illisible : 12 caractères attendus.")
    if target is not None and target["isin"] and target["isin"].upper() != isin:
        if "roadmap_item_id" in data:
            raise TicketError("La cible liée porte sur un autre titre.")
        target = None  # the target was pointed at another title since: the link is dropped

    known = conn.execute(
        "SELECT name, asset_class FROM instruments WHERE isin = ?", (isin,)
    ).fetchone()
    if known and known["asset_class"] and known["asset_class"] not in INSTRUMENTS:
        raise TicketError("Les tickets ne portent que sur des actions et des ETF.")
    listed = store.universe(fiches).get(isin)
    name = (
        _text(given("name"))
        or (known["name"] if known else None)
        or (target["name"] if target else None)
        or (listed["nom"] if listed else None)
        or isin
    )

    side = given("side") or "BUY"
    if side not in SIDES:
        raise TicketError("Sens inconnu : achat ou vente.")
    account = _text(given("account", "account_id"))
    if not account:
        held_on = [
            line.account
            for line in portfolio.build_lines(store.all_transactions(conn)).values()
            if line.isin == isin and line.is_open
        ]
        account = (target["account_id"] if target else None) or (
            held_on[0] if len(held_on) == 1 else "CTO"
        )
    if not conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account,)).fetchone():
        raise TicketError("Compte inconnu.")

    order_type = given("order_type") or "marche"
    if order_type not in ORDER_TYPES:
        raise TicketError("Type d'ordre inconnu.")
    limit_price = _positive(given("limit_price"), "Cours limite")
    if order_type != "limite":
        limit_price = None

    price, price_at = _positive(given("price"), "Cours indicatif"), None
    if price is None:
        found, price_at = _known_price(conn, isin, target)
        price = dec(found).quantize(PRICE_STEP) if found else None
        if price is not None and price <= 0:
            price, price_at = None, None
    elif before is not None and before["price"] and dec(before["price"]) == price:
        price_at = before["price_at"]
    else:
        price_at = _now()  # typed in by hand

    unit = limit_price if order_type == "limite" else price
    shares = _positive(given("shares"), "Quantité")
    amount = _positive(data.get("amount"), "Montant")
    if amount is not None and data.get("shares") in (None, ""):
        if unit is None:
            raise TicketError("Sans cours, la quantité ne se déduit pas du montant : la saisir.")
        shares = (amount / unit).quantize(SHARE_STEP, rounding=ROUND_DOWN)
        if shares <= 0:
            raise TicketError("Montant trop faible pour ce cours.")
    if side == "SELL":
        held = _shares_held(conn, account, isin)
        if held < SHARE_EPSILON:
            raise TicketError("Vente d'un titre qui n'est pas détenu sur ce compte.")
        if shares is not None and shares > held + SHARE_EPSILON:
            raise TicketError(
                f"Vente de {_plain(shares)} pour {_plain(held)} détenus sur ce compte."
            )

    fee = _positive(given("fee"), "Frais", zero=True)
    if side == "BUY" and target is None and before is None and "roadmap_item_id" not in data:
        # A new purchase of a title that is on the roadmap belongs to that target.
        target = conn.execute(
            "SELECT * FROM roadmap_items WHERE isin = ? AND status IN ('prevu', 'idee') "
            "ORDER BY CASE status WHEN 'prevu' THEN 0 ELSE 1 END, id LIMIT 1",
            (isin,),
        ).fetchone()
    return {
        "isin": isin,
        "name": name,
        "account_id": account,
        "side": side,
        "shares": str(shares) if shares is not None else None,
        "order_type": order_type,
        "limit_price": str(limit_price) if limit_price is not None else None,
        "price": str(price) if price is not None else None,
        "price_at": price_at if price is not None else None,
        "fee": str(fee if fee is not None else DEFAULT_FEE),
        "reason": _text(given("reason")),
        "roadmap_item_id": target["id"] if target is not None and side == "BUY" else None,
    }


def create(
    conn: sqlite3.Connection,
    data: dict,
    proposed_by: str | None = None,
    fiches: Path | None = None,
) -> int:
    """A new draft. Whoever creates it, it starts as a draft and nothing else."""
    ticket = _clean(conn, data, None, fiches)
    now = _now()
    cursor = conn.execute(
        "INSERT INTO tickets (isin, name, account_id, side, shares, order_type, limit_price, "
        "price, price_at, fee, reason, roadmap_item_id, status, proposed_by, created_at, "
        "updated_at) VALUES (:isin, :name, :account_id, :side, :shares, :order_type, "
        ":limit_price, :price, :price_at, :fee, :reason, :roadmap_item_id, 'brouillon', "
        ":proposed_by, :now, :now)",
        {**ticket, "proposed_by": proposed_by, "now": now},
    )
    conn.commit()
    return cursor.lastrowid


CHANGED = "Le ticket a changé entre-temps : recharger la page."


def update(
    conn: sqlite3.Connection, ticket_id: int, data: dict, fiches: Path | None = None
) -> None:
    before = _row(conn, ticket_id)
    if before["status"] != "brouillon":
        raise TicketError("Seul un brouillon se modifie : revenir au brouillon d'abord.")
    ticket = _clean(conn, data, before, fiches)
    # Only what is still the draft that was read: a ticket made ready in the
    # meantime keeps the fields its controls were run on.
    changed = conn.execute(
        "UPDATE tickets SET name = :name, account_id = :account_id, side = :side, "
        "shares = :shares, order_type = :order_type, limit_price = :limit_price, price = :price, "
        "price_at = :price_at, fee = :fee, reason = :reason, roadmap_item_id = :roadmap_item_id, "
        "updated_at = :now WHERE id = :id AND status = 'brouillon' AND updated_at = :seen",
        {**ticket, "now": _stamp(before), "id": ticket_id, "seen": before["updated_at"]},
    ).rowcount
    conn.commit()
    if not changed:
        raise TicketError(CHANGED)


def _stamp(before: sqlite3.Row) -> str:
    """A time of change that differs from the one read, even within one second."""
    now = _now()
    if now != before["updated_at"]:
        return now
    later = datetime.fromisoformat(now) + timedelta(seconds=1)
    return later.isoformat(timespec="seconds")


def set_status(
    conn: sqlite3.Connection,
    ticket_id: int,
    status: str,
    fiches: Path | None = None,
    today: date | None = None,
) -> None:
    """Move a ticket by hand. "Exécuté" is not reachable here: only a matched
    transaction makes a ticket executed."""
    refresh(conn, today)
    row = _row(conn, ticket_id)
    moves = {
        ("brouillon", "pret"),
        ("pret", "brouillon"),
        ("brouillon", "abandonne"),
        ("pret", "abandonne"),
        ("abandonne", "brouillon"),
    }
    if (row["status"], status) not in moves:
        raise TicketError("Ce changement d'état n'est pas possible.")
    now = _stamp(row)
    still = (ticket_id, row["status"], row["updated_at"])  # the row the controls were run on
    if status == "pret":
        seen = view(conn, row, context(conn, fiches, today))
        if not seen["can_be_ready"]:
            raise TicketError(seen["stop"])
        changed = conn.execute(
            "UPDATE tickets SET status = 'pret', ready_at = ?, checks = ?, updated_at = ? "
            "WHERE id = ? AND status = ? AND updated_at = ?",
            (now, json.dumps(seen["controls"], ensure_ascii=False), now, *still),
        ).rowcount
    elif status == "abandonne":
        changed = conn.execute(
            "UPDATE tickets SET status = 'abandonne', closed_at = ?, updated_at = ? "
            "WHERE id = ? AND status = ? AND updated_at = ?",
            (now, now, *still),
        ).rowcount
    else:
        changed = conn.execute(
            "UPDATE tickets SET status = 'brouillon', ready_at = NULL, closed_at = NULL, "
            "checks = NULL, updated_at = ? WHERE id = ? AND status = ? AND updated_at = ?",
            (now, *still),
        ).rowcount
    conn.commit()
    if not changed:
        raise TicketError(CHANGED)


def delete(conn: sqlite3.Connection, ticket_id: int) -> None:
    row = _row(conn, ticket_id)
    if row["status"] == "execute":
        raise TicketError("Un ticket exécuté se garde : il est la trace de l'ordre.")
    conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    conn.commit()


def refresh_price(conn: sqlite3.Connection, market: Market, ticket_id: int) -> None:
    """Ask the price source for the indicative price of a draft, in euros."""
    row = _row(conn, ticket_id)
    if row["status"] != "brouillon":
        raise TicketError("Seul un brouillon se modifie : revenir au brouillon d'abord.")
    symbol = market.resolve(conn, row["isin"])
    if not symbol and row["roadmap_item_id"]:
        target = _target(conn, row["roadmap_item_id"])
        symbol = target["quote_symbol"] if target else None
    if not symbol:
        listing = choose_listing(row["isin"], market.provider.search(row["isin"]))
        symbol = listing.symbol if listing else None
    if not symbol:
        raise ProviderError("format", "aucune cotation trouvée pour ce titre : saisir le cours")
    price = market.price_eur(symbol).quantize(PRICE_STEP)
    now = _now()
    if price <= 0:
        raise ProviderError("format", "cours nul dans la réponse de la source")
    changed = conn.execute(
        "UPDATE tickets SET price = ?, price_at = ?, updated_at = ? "
        "WHERE id = ? AND status = 'brouillon'",
        (str(price), now, now, ticket_id),
    ).rowcount
    conn.commit()
    if not changed:
        raise TicketError(CHANGED)


# -- Matching with what was really done ------------------------------------------


def _execute(conn: sqlite3.Connection, row: sqlite3.Row, transaction_id: str) -> None:
    now = _now()
    copied = 0
    if row["reason"]:
        # The reason written on the ticket is the reason of the transaction: the
        # rules page does not ask for it a second time.
        copied = conn.execute(
            "INSERT INTO deviation_notes (transaction_id, reason, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (transaction_id) DO NOTHING",
            (transaction_id, row["reason"], now),
        ).rowcount
    conn.execute(
        "UPDATE tickets SET status = 'execute', transaction_id = ?, reason_copied = ?, "
        "closed_at = ?, updated_at = ? WHERE id = ?",
        (transaction_id, copied, now, now, row["id"]),
    )


def reconcile(conn: sqlite3.Connection) -> dict:
    """Match each ready ticket with the transaction that carried it out.

    One transaction that is surely the order: the ticket becomes executed.
    Several, or one that is only possible: the user says which. None: nothing
    changes. Matching one ticket can leave a single sure transaction to
    another, so the pass is repeated until nothing moves.
    """
    matched: list[int] = []
    while True:
        moved = False
        ready = conn.execute("SELECT * FROM tickets WHERE status = 'pret' ORDER BY ready_at, id")
        for row in ready.fetchall():
            sure = [tx for tx in _free_trades(conn, row) if _same_order(conn, row, tx)]
            if len(sure) == 1:
                _execute(conn, row, sure[0]["transaction_id"])
                matched.append(row["id"])
                moved = True
        if not moved:
            break
    conn.commit()
    left = conn.execute("SELECT * FROM tickets WHERE status = 'pret' ORDER BY ready_at, id")
    ambiguous = [row["id"] for row in left.fetchall() if _free_trades(conn, row)]
    return {"matched": sorted(matched), "ambiguous": ambiguous}


def match(
    conn: sqlite3.Connection,
    ticket_id: int,
    transaction_id: str | None,
    today: date | None = None,
) -> None:
    """The user's own word on which transaction is the ticket's, or that none is."""
    row = _row(conn, ticket_id)
    if transaction_id is None:
        if row["status"] != "execute":
            raise TicketError("Ce ticket n'est rapproché d'aucune transaction.")
        # Not this order: remember it, so the next import does not match it again,
        # and take back the reason that was written beside that transaction.
        rejected = [*json.loads(row["rejected"] or "[]"), row["transaction_id"]]
        if row["reason_copied"]:
            conn.execute(
                "DELETE FROM deviation_notes WHERE transaction_id = ? AND reason = ?",
                (row["transaction_id"], row["reason"]),
            )
        conn.execute(
            "UPDATE tickets SET status = 'pret', transaction_id = NULL, reason_copied = 0, "
            "rejected = ?, closed_at = NULL, updated_at = ? WHERE id = ?",
            (json.dumps(rejected), _now(), ticket_id),
        )
        conn.commit()
        refresh(conn, today)  # ready again only if the status still allows it
        return
    if row["status"] != "pret":
        raise TicketError("Seul un ticket prêt se rapproche d'une transaction.")
    if transaction_id not in {tx["transaction_id"] for tx in _free_trades(conn, row)}:
        raise TicketError("Cette transaction ne correspond pas au ticket.")
    _execute(conn, row, transaction_id)
    conn.commit()
