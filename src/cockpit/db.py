"""SQLite access: one file, versioned migrations, nothing else."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

from . import config


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database (creating and migrating it when needed)."""
    # Each request opens its own connection and uses it sequentially, but the web
    # framework may run the steps of one request on different worker threads.
    conn = sqlite3.connect(str(path or config.db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def _migration_files() -> list[tuple[int, str, str]]:
    files = []
    for entry in resources.files("cockpit.migrations").iterdir():
        if entry.name.endswith(".sql"):
            version = int(entry.name.split("_", 1)[0])
            files.append((version, entry.name, entry.read_text(encoding="utf-8")))
    return sorted(files)


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_version")}
    for version, name, sql in _migration_files():
        if version in applied:
            continue
        # executescript commits implicitly; each migration is its own unit.
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, datetime('now'))",
            (version, name),
        )
        conn.commit()
