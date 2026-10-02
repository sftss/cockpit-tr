"""Dates typed in by a person."""

from __future__ import annotations

from datetime import date


def parse_day(text: str | None, default: date | None = None) -> date:
    """An ISO day (YYYY-MM-DD); `default` when nothing was given."""
    if text is None or not str(text).strip():
        if default is None:
            raise ValueError("Date manquante.")
        return default
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError as exc:
        raise ValueError(f"Date illisible : {text!r} (attendu AAAA-MM-JJ).") from exc
