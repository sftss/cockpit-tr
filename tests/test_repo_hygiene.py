"""The repository is public: personal data must never be committed.

This test fails as soon as git tracks a file that looks like data (an export,
a workbook, a database, a settings file with rule values and roadmap) or like
a secret.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".csv", ".xlsx", ".xls", ".db", ".sqlite", ".sqlite3"}
FORBIDDEN_NAMES = {".env", "credentials"}


def test_no_data_or_secret_file_is_tracked():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("pas de dépôt git ici")
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    offenders = [
        name
        for name in tracked
        if Path(name).suffix.lower() in FORBIDDEN_SUFFIXES
        or Path(name).name in FORBIDDEN_NAMES
        or Path(name).name.startswith("cookies")
        or Path(name).name.startswith("cockpit-reglages")
    ]
    assert offenders == [], f"fichiers de données ou secrets suivis par git : {offenders}"
