"""A settings file: rule values, roadmap and the assistant's instructions, as JSON.

All three are personal, so they are not part of the code. This file is how they
are carried from one machine to another, or put in place the first time.
Importing the same file twice adds nothing.
"""

from __future__ import annotations

import sqlite3

from . import roadmap, rules
from .assistant import prompt

FORMAT = "cockpit-tr/reglages"
VERSION = 1


def export(conn: sqlite3.Connection) -> dict:
    return {
        "format": FORMAT,
        "version": VERSION,
        "rules": [
            {
                "kind": rule.kind,
                "account": rule.account,
                "value": str(rule.value),
                "valid_from": rule.valid_from,
                "valid_to": rule.valid_to,
                "note": rule.note,
            }
            for rule in rules.list_rules(conn)
        ],
        "roadmap": [
            {key: item[key] for key in (*roadmap.FIELDS, "symbol")}
            for item in roadmap.items(conn)["items"]
        ],
        "assistant_context": [
            {"title": doc["title"], "content": doc["content"]} for doc in prompt.documents(conn)
        ],
    }


def load(conn: sqlite3.Connection, data: object) -> dict:
    """Add what the file holds and the database does not have yet."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("Ce fichier n'est pas un fichier de réglages de Cockpit TR.")
    if data.get("version") != VERSION:
        raise ValueError("Version de fichier de réglages inconnue.")
    wanted_rules, wanted_items = data.get("rules") or [], data.get("roadmap") or []
    wanted_docs = data.get("assistant_context") or []
    if not all(isinstance(part, list) for part in (wanted_rules, wanted_items, wanted_docs)):
        raise ValueError("Fichier de réglages mal formé.")

    existing = {(r.kind, r.account, r.valid_from) for r in rules.list_rules(conn)}
    added_rules = 0
    # Oldest first, so that each value closes the one before it.
    for entry in sorted(wanted_rules, key=lambda e: str(e.get("valid_from") or "")):
        key = (entry.get("kind"), entry.get("account") or None, entry.get("valid_from"))
        if key in existing:
            continue
        rules.set_rule(
            conn,
            str(entry.get("kind")),
            entry.get("value"),
            entry.get("valid_from"),
            entry.get("account"),
            entry.get("note"),
        )
        existing.add(key)
        added_rules += 1

    names = {
        row["name"].casefold() for row in conn.execute("SELECT name FROM roadmap_items").fetchall()
    }
    added_items = 0
    for entry in wanted_items:
        if not isinstance(entry, dict):
            raise ValueError("Fichier de réglages mal formé.")
        name = str(entry.get("name") or "").strip()
        if name.casefold() in names:
            continue
        roadmap.create(conn, entry)
        names.add(name.casefold())
        added_items += 1

    titles = {doc["title"] for doc in prompt.documents(conn)}
    added_docs = 0
    for entry in wanted_docs:
        if not isinstance(entry, dict):
            raise ValueError("Fichier de réglages mal formé.")
        title = str(entry.get("title") or "").strip()
        if title in titles:
            continue  # a document already there is never overwritten by an import
        prompt.save_document(conn, title, str(entry.get("content") or ""))
        titles.add(title)
        added_docs += 1

    return {
        "rules_added": added_rules,
        "rules_present": len(wanted_rules) - added_rules,
        "roadmap_added": added_items,
        "roadmap_present": len(wanted_items) - added_items,
        "context_added": added_docs,
        "context_present": len(wanted_docs) - added_docs,
    }
