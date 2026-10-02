"""The decision journal: what was decided, when, and why."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

from .days import parse_day

AUTHORS = ("moi", "assistant")


def _clean(data: dict) -> dict:
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("Le titre de la note est obligatoire.")
    return {
        "decided_on": parse_day(data.get("decided_on"), date.today()).isoformat(),
        "title": title[:200],
        "body": str(data.get("body") or "").strip() or None,
    }


def add(conn: sqlite3.Connection, data: dict, author: str = "moi") -> int:
    if author not in AUTHORS:
        raise ValueError("Auteur inconnu.")
    entry = _clean(data)
    cursor = conn.execute(
        "INSERT INTO decisions (decided_on, title, body, author, created_at) "
        "VALUES (:decided_on, :title, :body, :author, :now)",
        {**entry, "author": author, "now": datetime.now(UTC).isoformat(timespec="seconds")},
    )
    conn.commit()
    return cursor.lastrowid


def update(conn: sqlite3.Connection, entry_id: int, data: dict) -> bool:
    entry = _clean(data)
    changed = conn.execute(
        "UPDATE decisions SET decided_on = :decided_on, title = :title, body = :body "
        "WHERE id = :id",
        {**entry, "id": entry_id},
    ).rowcount
    conn.commit()
    return bool(changed)


def delete(conn: sqlite3.Connection, entry_id: int) -> bool:
    deleted = conn.execute("DELETE FROM decisions WHERE id = ?", (entry_id,)).rowcount
    conn.commit()
    return bool(deleted)


def entries(conn: sqlite3.Connection, limit: int | None = None) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM decisions ORDER BY decided_on DESC, id DESC" + (" LIMIT ?" if limit else ""),
        (limit,) if limit else (),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "decided_on": row["decided_on"],
            "title": row["title"],
            "body": row["body"],
            "author": row["author"],
        }
        for row in rows
    ]
