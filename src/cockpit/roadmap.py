"""The roadmap: what is planned, under which condition, and why.

An item is a target, not an order. When it carries a price in euros, the screen
says once the market price is at or below it; nothing else happens.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

from . import compliance
from .market.provider import ProviderError
from .market.service import Market, choose_listing
from .money import dec, money

STATUSES = {"idee": "Idée", "prevu": "Prévu", "execute": "Exécuté", "abandonne": "Abandonné"}
ACTIVE = ("idee", "prevu")
FIELDS = ("name", "isin", "account", "amount", "entry_condition", "entry_price", "thesis", "status")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _text(value: object) -> str | None:
    return str(value).strip() or None if value is not None else None


def _amount(value: object, what: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    number = dec(str(value).replace(",", "."))
    if number <= 0:
        raise ValueError(f"{what} : attendu un montant positif.")
    return str(number)


def _clean(conn: sqlite3.Connection, data: dict) -> dict:
    name = _text(data.get("name"))
    if not name:
        raise ValueError("Le nom de la cible est obligatoire.")
    status = data.get("status") or "idee"
    if status not in STATUSES:
        raise ValueError("Statut inconnu.")
    account = _text(data.get("account"))
    if account and not conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account,)).fetchone():
        raise ValueError("Compte inconnu.")
    isin = _text(data.get("isin"))
    return {
        "name": name,
        "isin": isin.upper() if isin else None,
        "account_id": account,
        "amount": _amount(data.get("amount"), "Montant prévu"),
        "entry_condition": _text(data.get("entry_condition")),
        "entry_price": _amount(data.get("entry_price"), "Cours d'entrée"),
        "thesis": _text(data.get("thesis")),
        "status": status,
        "quote_symbol": _text(data.get("symbol")),
    }


def create(conn: sqlite3.Connection, data: dict) -> int:
    item = _clean(conn, data)
    now = _now()
    cursor = conn.execute(
        "INSERT INTO roadmap_items (name, isin, account_id, amount, entry_condition, entry_price,"
        " thesis, status, quote_symbol, created_at, updated_at) "
        "VALUES (:name, :isin, :account_id, :amount, :entry_condition, :entry_price, :thesis,"
        " :status, :quote_symbol, :now, :now)",
        {**item, "now": now},
    )
    conn.commit()
    return cursor.lastrowid


def update(conn: sqlite3.Connection, item_id: int, data: dict) -> bool:
    before = conn.execute("SELECT * FROM roadmap_items WHERE id = ?", (item_id,)).fetchone()
    if before is None:
        return False
    item = _clean(conn, data)
    # Another instrument: the price kept for the old one no longer means anything.
    same = before["isin"] == item["isin"] and before["quote_symbol"] == item["quote_symbol"]
    conn.execute(
        "UPDATE roadmap_items SET name = :name, isin = :isin, account_id = :account_id,"
        " amount = :amount, entry_condition = :entry_condition, entry_price = :entry_price,"
        " thesis = :thesis, status = :status, quote_symbol = :quote_symbol, updated_at = :now"
        + ("" if same else ", last_price = NULL, last_price_at = NULL")
        + " WHERE id = :id",
        {**item, "now": _now(), "id": item_id},
    )
    conn.commit()
    return True


def delete(conn: sqlite3.Connection, item_id: int) -> bool:
    deleted = conn.execute("DELETE FROM roadmap_items WHERE id = ?", (item_id,)).rowcount
    conn.commit()
    return bool(deleted)


def items(conn: sqlite3.Connection, today: date | None = None) -> dict:
    statuses = compliance.latest(conn)
    order = "CASE status WHEN 'prevu' THEN 0 WHEN 'idee' THEN 1 WHEN 'execute' THEN 2 ELSE 3 END"
    rows = conn.execute(f"SELECT * FROM roadmap_items ORDER BY {order}, name").fetchall()
    result = []
    for row in rows:
        price = dec(row["last_price"]) if row["last_price"] else None
        target = dec(row["entry_price"]) if row["entry_price"] else None
        result.append(
            {
                "id": row["id"],
                "name": row["name"],
                "isin": row["isin"],
                "account": row["account_id"],
                "amount": money(dec(row["amount"])) if row["amount"] else None,
                "entry_condition": row["entry_condition"],
                "entry_price": float(target) if target is not None else None,
                "thesis": row["thesis"],
                "status": row["status"],
                "symbol": row["quote_symbol"],
                "last_price": float(price) if price is not None else None,
                "last_price_at": row["last_price_at"],
                "reached": bool(
                    row["status"] in ACTIVE
                    and price is not None
                    and target is not None
                    and price <= target
                ),
                "zoya": compliance.view(statuses.get(row["isin"]), today) if row["isin"] else None,
            }
        )
    return {"statuses": STATUSES, "items": result}


def refresh_prices(conn: sqlite3.Connection, market: Market) -> dict:
    """Latest price in euros of each active target that names an instrument."""
    updated, errors, stopped = 0, [], None
    rows = conn.execute(
        "SELECT id, name, isin, quote_symbol FROM roadmap_items "
        "WHERE status IN ('idee', 'prevu') AND (isin IS NOT NULL OR quote_symbol IS NOT NULL)"
    ).fetchall()
    for row in rows:
        try:
            symbol = row["quote_symbol"]
            if not symbol:
                known = conn.execute(
                    "SELECT quote_symbol FROM instruments WHERE isin = ?", (row["isin"],)
                ).fetchone()
                symbol = known["quote_symbol"] if known else None
            if not symbol:
                listing = choose_listing(row["isin"], market.provider.search(row["isin"]))
                symbol = listing.symbol if listing else None
            if not symbol:
                errors.append(f"{row['name']} : aucune cotation trouvée, saisir le symbole")
                continue
            price = market.price_eur(symbol)
            conn.execute(
                "UPDATE roadmap_items SET quote_symbol = ?, last_price = ?, last_price_at = ? "
                "WHERE id = ?",
                (symbol, str(price), _now(), row["id"]),
            )
            conn.commit()
            updated += 1
        except ProviderError as exc:
            errors.append(f"{row['name']} : {exc}")
            if exc.kind in ("refused", "network"):
                stopped = exc.kind
                break
    return {
        "updated": updated,
        "errors": errors,
        "refused": stopped == "refused",
        "unreachable": stopped == "network",
    }
