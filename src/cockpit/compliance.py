"""Compliance status of each instrument ("Halalitude"), as checked by hand.

The application never decides whether an instrument is compliant: it stores
the status read in the screening applications, with the day it was read, and
says when that reading is too old to rely on.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta

from .days import parse_day

VALIDITY_DAYS = 90
# Stored values on the left (they are in the database); what the screens say on the right.
STATUSES = {"conforme": "Halal", "douteux": "Douteux", "non_conforme": "Haram"}


def record(
    conn: sqlite3.Connection, isin: str, status: str, checked_on: str | None, note: str | None
) -> None:
    isin = isin.strip().upper()
    if not isin:
        raise ValueError("Code ISIN manquant.")
    if status not in STATUSES:
        raise ValueError("Statut inconnu.")
    day = parse_day(checked_on, date.today())
    if day > date.today():
        raise ValueError("La date de vérification est dans le futur.")
    conn.execute(
        "INSERT INTO compliance (isin, checked_on, status, note, created_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (isin, checked_on) DO UPDATE SET "
        "status = excluded.status, note = excluded.note",
        (
            isin,
            day.isoformat(),
            status,
            (note or "").strip() or None,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def latest(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT c.* FROM compliance c JOIN (SELECT isin, MAX(checked_on) AS checked_on "
        "FROM compliance GROUP BY isin) last "
        "ON last.isin = c.isin AND last.checked_on = c.checked_on"
    ).fetchall()
    return {row["isin"]: row for row in rows}


def view(entry: sqlite3.Row | None, today: date | None = None) -> dict:
    """What the screens show for one instrument."""
    if entry is None:
        return {
            "status": None,
            "checked_on": None,
            "note": None,
            "age_days": None,
            "due_on": None,
            "state": "non_renseigne",
        }
    today = today or date.today()
    checked = date.fromisoformat(entry["checked_on"])
    age = (today - checked).days
    return {
        "status": entry["status"],
        "checked_on": entry["checked_on"],
        "note": entry["note"],
        "age_days": age,
        "due_on": (checked + timedelta(days=VALIDITY_DAYS)).isoformat(),
        "state": "a_reverifier" if age > VALIDITY_DAYS else "a_jour",
    }


def overview(conn: sqlite3.Connection, held: dict[str, str], today: date | None = None) -> dict:
    """Held instruments first, then roadmap targets, then anything else with a status.

    `held` maps the ISIN of each open line to its name.
    """
    statuses = latest(conn)
    names = dict(conn.execute("SELECT isin, name FROM instruments").fetchall())
    targets = {
        row["isin"]: row["name"]
        for row in conn.execute(
            "SELECT isin, name FROM roadmap_items "
            "WHERE isin IS NOT NULL AND status IN ('idee', 'prevu')"
        )
    }
    checks = dict(conn.execute("SELECT isin, COUNT(*) FROM compliance GROUP BY isin").fetchall())

    items, seen = [], set()

    def add(isin: str, name: str, group: str) -> None:
        if isin in seen:
            return
        seen.add(isin)
        items.append(
            {
                "isin": isin,
                "name": name,
                "group": group,
                "checks": checks.get(isin, 0),
                **view(statuses.get(isin), today),
            }
        )

    for isin, name in sorted(held.items(), key=lambda pair: pair[1].lower()):
        add(isin, name, "detenu")
    for isin, name in sorted(targets.items(), key=lambda pair: pair[1].lower()):
        add(isin, name, "cible")
    for isin in sorted(statuses, key=lambda code: names.get(code, code).lower()):
        add(isin, names.get(isin, isin), "autre")

    watched = [item for item in items if item["group"] != "autre"]
    return {
        "validity_days": VALIDITY_DAYS,
        "statuses": STATUSES,
        "items": items,
        "summary": {
            "held": sum(1 for item in items if item["group"] == "detenu"),
            "missing": sum(1 for item in watched if item["state"] == "non_renseigne"),
            "stale": sum(1 for item in watched if item["state"] == "a_reverifier"),
            "not_compliant": sum(
                1
                for item in watched
                if item["status"] in ("non_conforme", "douteux") and item["group"] == "detenu"
            ),
        },
    }
