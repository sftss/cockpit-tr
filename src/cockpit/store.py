"""Reads and writes around the calculations: transactions, prices, snapshots."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

from . import portfolio
from .money import dec


def all_transactions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM transactions").fetchall()


def latest_prices(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT p.isin, p.date, p.price, p.source FROM prices p "
        "JOIN (SELECT isin, MAX(date) AS date FROM prices GROUP BY isin) last "
        "ON last.isin = p.isin AND last.date = p.date"
    ).fetchall()
    return {row["isin"]: dict(row) for row in rows}


def set_price(conn: sqlite3.Connection, isin: str, price: Decimal, day: str, source: str) -> None:
    if price <= 0:
        raise ValueError("Le cours doit être positif.")
    conn.execute(
        "INSERT INTO prices (isin, date, price, source) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (isin, date) DO UPDATE SET price = excluded.price, source = excluded.source",
        (isin, day, str(price), source),
    )
    conn.commit()


def current_report(conn: sqlite3.Connection) -> dict:
    data = portfolio.report(all_transactions(conn), latest_prices(conn))
    last = conn.execute("SELECT MAX(imported_at) FROM transactions").fetchone()[0]
    data["last_import"] = last
    return data


def state(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last, "
        "MAX(imported_at) AS imported FROM transactions"
    ).fetchone()
    return {
        "transactions": row["n"],
        "from": row["first"],
        "to": row["last"],
        "last_import": row["imported"],
    }


# -- Snapshots ---------------------------------------------------------------


def take_snapshot(conn: sqlite3.Connection, label: str | None = None) -> int:
    """Freeze today's positions and totals so they can be compared later."""
    data = current_report(conn)
    totals = {key: data[key] for key in ("period", "accounts", "closed_summary", "fees", "flows")}
    totals["manual_orders"] = data["manual_orders"]
    cursor = conn.execute(
        "INSERT INTO snapshots (taken_at, label, totals) VALUES (?, ?, ?)",
        (datetime.now(UTC).isoformat(timespec="seconds"), label or None, json.dumps(totals)),
    )
    snapshot_id = cursor.lastrowid
    conn.executemany(
        "INSERT INTO snapshot_positions "
        "(snapshot_id, account_id, isin, name, shares, cost, price, value) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                snapshot_id,
                p["account"],
                p["isin"],
                p["name"],
                str(p["shares"]),
                str(p["cost"]),
                None if p["price"] is None else str(p["price"]),
                None if p["value"] is None else str(p["value"]),
            )
            for p in data["positions"]
        ],
    )
    conn.commit()
    return snapshot_id


def list_snapshots(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT s.id, s.taken_at, s.label, s.totals, COUNT(p.isin) AS positions "
        "FROM snapshots s LEFT JOIN snapshot_positions p ON p.snapshot_id = s.id "
        "GROUP BY s.id ORDER BY s.id DESC"
    ).fetchall()
    result = []
    for row in rows:
        totals = json.loads(row["totals"])
        result.append(
            {
                "id": row["id"],
                "taken_at": row["taken_at"],
                "label": row["label"],
                "positions": row["positions"],
                "accounts": totals.get("accounts", []),
            }
        )
    return result


def snapshot(conn: sqlite3.Connection, snapshot_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if row is None:
        return None
    positions = conn.execute(
        "SELECT account_id AS account, isin, name, shares, cost, price, value "
        "FROM snapshot_positions WHERE snapshot_id = ? ORDER BY account_id, name",
        (snapshot_id,),
    ).fetchall()

    def number(text: str | None) -> float | None:
        return None if text is None else float(dec(text))

    return {
        "id": row["id"],
        "taken_at": row["taken_at"],
        "label": row["label"],
        **json.loads(row["totals"]),
        "positions": [
            {
                "account": p["account"],
                "isin": p["isin"],
                "name": p["name"],
                "shares": number(p["shares"]),
                "cost": number(p["cost"]),
                "price": number(p["price"]),
                "value": number(p["value"]),
            }
            for p in positions
        ],
    }


def snapshot_csv(data: dict) -> str:
    """Positions of a snapshot as CSV (semicolon-separated, opens in Excel FR)."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(["compte", "isin", "titre", "quantite", "prix_de_revient", "cours", "valeur"])
    for p in data["positions"]:
        writer.writerow(
            [
                p["account"],
                p["isin"],
                p["name"],
                _fr(p["shares"]),
                _fr(p["cost"]),
                _fr(p["price"]),
                _fr(p["value"]),
            ]
        )
    return out.getvalue()


def _fr(value: float | None) -> str:
    return "" if value is None else repr(value).replace(".", ",")
