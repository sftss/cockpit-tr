"""Physical gold held outside the broker: lots typed in by hand.

The value follows the world price of gold converted to euros. It is an
approximation of what the metal is worth: the premium of a coin or a bar over
its gold content is not in it.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal

from .days import parse_day
from .market.service import Market
from .money import ZERO, dec, money, ratio

TROY_OUNCE_GRAMS = Decimal("31.1034768")
GOLD_SYMBOL = "GC=F"  # gold futures in US dollars per troy ounce: the usual public reference


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clean(data: dict) -> dict:
    label = str(data.get("label") or "").strip()
    if not label:
        raise ValueError("Le libellé du lot est obligatoire.")
    grams = dec(str(data.get("grams") or "").replace(",", "."))
    if grams <= 0:
        raise ValueError("Le poids d'or fin doit être positif, en grammes.")
    cost = data.get("cost")
    cost = None if cost is None or str(cost).strip() == "" else dec(str(cost).replace(",", "."))
    if cost is not None and cost < 0:
        raise ValueError("Le prix payé ne peut pas être négatif.")
    acquired = str(data.get("acquired_on") or "").strip() or None
    if acquired:
        acquired = parse_day(acquired).isoformat()
    return {
        "label": label,
        "grams": str(grams),
        "cost": None if cost is None else str(cost),
        "acquired_on": acquired,
        "note": str(data.get("note") or "").strip() or None,
    }


def add_lot(conn: sqlite3.Connection, data: dict) -> int:
    lot = _clean(data)
    cursor = conn.execute(
        "INSERT INTO gold_lots (label, grams, cost, acquired_on, note, created_at) "
        "VALUES (:label, :grams, :cost, :acquired_on, :note, :now)",
        {**lot, "now": _now()},
    )
    conn.commit()
    return cursor.lastrowid


def update_lot(conn: sqlite3.Connection, lot_id: int, data: dict) -> bool:
    lot = _clean(data)
    changed = conn.execute(
        "UPDATE gold_lots SET label = :label, grams = :grams, cost = :cost, "
        "acquired_on = :acquired_on, note = :note WHERE id = :id",
        {**lot, "id": lot_id},
    ).rowcount
    conn.commit()
    return bool(changed)


def delete_lot(conn: sqlite3.Connection, lot_id: int) -> bool:
    deleted = conn.execute("DELETE FROM gold_lots WHERE id = ?", (lot_id,)).rowcount
    conn.commit()
    return bool(deleted)


def refresh_price(conn: sqlite3.Connection, market: Market) -> Decimal:
    """Ask the price of gold and keep it, in euros per gram."""
    per_gram = market.price_eur(GOLD_SYMBOL) / TROY_OUNCE_GRAMS
    conn.execute(
        "INSERT INTO gold_prices (date, eur_per_gram, fetched_at) VALUES (?, ?, ?) "
        "ON CONFLICT (date) DO UPDATE SET eur_per_gram = excluded.eur_per_gram, "
        "fetched_at = excluded.fetched_at",
        (date.today().isoformat(), str(per_gram), _now()),
    )
    conn.commit()
    return per_gram


def summary(conn: sqlite3.Connection) -> dict:
    last = conn.execute("SELECT * FROM gold_prices ORDER BY date DESC LIMIT 1").fetchone()
    per_gram = dec(last["eur_per_gram"]) if last else None
    lots, grams, cost, costed_value = [], ZERO, ZERO, ZERO
    all_costed = True
    for row in conn.execute(
        "SELECT * FROM gold_lots ORDER BY acquired_on IS NULL, acquired_on, id"
    ):
        weight = dec(row["grams"])
        paid = dec(row["cost"]) if row["cost"] is not None else None
        value = weight * per_gram if per_gram is not None else None
        grams += weight
        if paid is None:
            all_costed = False
        else:
            cost += paid
            costed_value += value or ZERO
        lots.append(
            {
                "id": row["id"],
                "label": row["label"],
                "grams": float(weight),
                "cost": money(paid),
                "acquired_on": row["acquired_on"],
                "note": row["note"],
                "value": money(value),
                "latent": money(value - paid) if value is not None and paid is not None else None,
            }
        )
    value = grams * per_gram if per_gram is not None else None
    known = bool(lots) and all_costed and value is not None
    return {
        "lots": lots,
        "grams": float(grams),
        "cost": money(cost) if lots and all_costed else None,
        "value": money(value) if lots else None,
        "latent": money(value - cost) if known else None,
        "latent_pct": ratio(value - cost, cost) if known else None,
        "eur_per_gram": float(per_gram.quantize(Decimal("0.01"))) if per_gram is not None else None,
        "price_date": last["date"] if last else None,
        "fetched_at": last["fetched_at"] if last else None,
        "symbol": GOLD_SYMBOL,
    }
