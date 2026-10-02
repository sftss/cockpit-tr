"""Import of the Trade Republic transaction export (CSV, 23 columns).

The import is idempotent: ``transaction_id`` is the primary key, so loading the
same file twice, or a newer export overlapping an older one, adds only the new
lines. Nothing is ever updated or deleted by an import.
"""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from ..money import is_decimal

COLUMNS = [
    "datetime",
    "date",
    "account_type",
    "category",
    "type",
    "asset_class",
    "name",
    "symbol",
    "shares",
    "price",
    "amount",
    "fee",
    "tax",
    "currency",
    "original_amount",
    "original_currency",
    "fx_rate",
    "description",
    "transaction_id",
    "counterparty_name",
    "counterparty_iban",
    "payment_reference",
    "mcc_code",
]

# Without these the file is not a transaction export we can make sense of.
REQUIRED = {"datetime", "date", "account_type", "category", "type", "amount", "transaction_id"}
NUMERIC = ("shares", "price", "amount", "fee", "tax", "original_amount", "fx_rate")

# Every type seen so far in real exports. A type outside this set is still
# stored, but reported: the calculations ignore what they do not understand
# rather than guess.
KNOWN_TYPES = {
    "BUY",
    "SELL",
    "SPLIT",
    "BONUS_ISSUE",
    "MIGRATION",
    "CUSTOMER_INPAYMENT",
    "TRANSFER_INBOUND",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "CARD_TRANSACTION",
    "CARD_TRANSACTION_INTERNATIONAL",
    "DIVIDEND",
    "DIVIDEND_EQUIVALENT_PAYMENT",
    "INTEREST_PAYMENT",
    "PEA_MARKETING",
    "TAX_OPTIMIZATION",
}


class CsvFormatError(ValueError):
    """The file is not a Trade Republic transaction export."""


@dataclass
class ImportReport:
    total: int = 0
    inserted: int = 0
    already_present: int = 0
    rejected: list[str] = field(default_factory=list)
    unknown_types: dict[str, int] = field(default_factory=dict)
    date_min: str | None = None
    date_max: str | None = None
    accounts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def parse(text: str) -> list[dict[str, str]]:
    """Read the CSV text into rows, checking it has the expected shape."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise CsvFormatError("Le fichier est vide.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    header = {name.strip() for name in (reader.fieldnames or [])}
    missing = sorted(REQUIRED - header)
    if missing:
        raise CsvFormatError(
            "Ce fichier ne ressemble pas à l'export de transactions Trade Republic : "
            f"colonnes absentes : {', '.join(missing)}."
        )
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _fallback_id(row: dict[str, str]) -> str:
    """Stable id for a line exported without transaction_id."""
    payload = "|".join(row.get(col, "") for col in COLUMNS if col != "transaction_id")
    return "sans-id-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _account_id(conn: sqlite3.Connection, tr_account_type: str) -> str:
    found = conn.execute(
        "SELECT id FROM accounts WHERE tr_account_type = ?", (tr_account_type,)
    ).fetchone()
    if found:
        return found[0]
    # An account type this version does not know yet: keep it under its own name.
    conn.execute(
        "INSERT INTO accounts (id, label, tr_account_type) VALUES (?, ?, ?)",
        (tr_account_type, tr_account_type, tr_account_type),
    )
    return tr_account_type


def import_csv(conn: sqlite3.Connection, text: str, source: str = "csv") -> ImportReport:
    rows = parse(text)
    report = ImportReport(total=len(rows))
    now = datetime.now(UTC).isoformat(timespec="seconds")

    for line_no, row in enumerate(rows, start=2):  # line 1 is the header
        bad = [col for col in NUMERIC if not is_decimal(row.get(col, ""))]
        if bad or not row.get("datetime") or not row.get("account_type"):
            reason = f"valeur illisible dans {', '.join(bad)}" if bad else "date ou compte manquant"
            report.rejected.append(f"ligne {line_no} : {reason}")
            continue

        tx_id = row.get("transaction_id") or _fallback_id(row)
        account = _account_id(conn, row["account_type"])
        isin = row.get("symbol", "")

        cursor = conn.execute(
            "INSERT OR IGNORE INTO transactions ("
            "transaction_id, datetime, date, account_id, category, type, asset_class, name, isin,"
            " shares, price, amount, fee, tax, currency, original_amount, original_currency,"
            " fx_rate, description, counterparty_name, counterparty_iban, payment_reference,"
            " mcc_code, source, imported_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tx_id,
                row["datetime"],
                row.get("date") or row["datetime"][:10],
                account,
                row.get("category", ""),
                row.get("type", ""),
                row.get("asset_class", ""),
                row.get("name", ""),
                isin,
                row.get("shares", ""),
                row.get("price", ""),
                row.get("amount", ""),
                row.get("fee", ""),
                row.get("tax", ""),
                row.get("currency", ""),
                row.get("original_amount", ""),
                row.get("original_currency", ""),
                row.get("fx_rate", ""),
                row.get("description", ""),
                row.get("counterparty_name", ""),
                row.get("counterparty_iban", ""),
                row.get("payment_reference", ""),
                row.get("mcc_code", ""),
                source,
                now,
            ),
        )
        if cursor.rowcount:
            report.inserted += 1
            report.accounts[account] = report.accounts.get(account, 0) + 1
        else:
            report.already_present += 1

        if isin and row.get("asset_class"):
            # Card payments also carry a "name" (the merchant): only lines with an
            # asset class describe an instrument.
            conn.execute(
                "INSERT INTO instruments (isin, name, asset_class) VALUES (?, ?, ?) "
                "ON CONFLICT (isin) DO UPDATE SET name = excluded.name, "
                "asset_class = excluded.asset_class",
                (isin, row.get("name") or isin, row.get("asset_class", "")),
            )

        tx_type = row.get("type", "")
        if tx_type not in KNOWN_TYPES:
            report.unknown_types[tx_type] = report.unknown_types.get(tx_type, 0) + 1

        day = row.get("date") or row["datetime"][:10]
        report.date_min = day if report.date_min is None else min(report.date_min, day)
        report.date_max = day if report.date_max is None else max(report.date_max, day)

    conn.commit()
    return report
