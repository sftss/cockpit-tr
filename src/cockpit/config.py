"""Where the application keeps its data.

Personal data (database, exports) never lives inside the repository: it goes to
the per-user data directory of the operating system. Set ``COCKPIT_DATA_DIR``
to override the location (the tests do).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "cockpit-tr"


def data_dir() -> Path:
    override = os.environ.get("COCKPIT_DATA_DIR")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_DIR_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "cockpit.db"


def frontend_dir() -> Path | None:
    """Built frontend, if present (``frontend/dist`` at the repository root)."""
    override = os.environ.get("COCKPIT_FRONTEND_DIR")
    candidates = [Path(override)] if override else []
    candidates.append(Path(__file__).resolve().parents[2] / "frontend" / "dist")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def fiches_dir() -> Path | None:
    """The daily company sheets (``fiches/`` at the repository root), if present."""
    override = os.environ.get("COCKPIT_FICHES_DIR")
    candidate = Path(override) if override else Path(__file__).resolve().parents[2] / "fiches"
    return candidate if candidate.is_dir() else None
