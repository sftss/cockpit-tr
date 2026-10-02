"""Shared fixtures. All data here is invented: the repository is public and
must never contain a real export."""

from __future__ import annotations

import csv
import io
import itertools

import pytest

from cockpit import db
from cockpit.importers.tr_csv import COLUMNS

_ids = itertools.count(1)


def tx(
    day: str, tx_type: str, *, account: str = "DEFAULT", time: str = "10:00:00", **cells
) -> dict:
    """One line of a Trade Republic export, with sensible defaults."""
    category = {
        "BUY": "TRADING",
        "SELL": "TRADING",
        "SPLIT": "CORPORATE_ACTION",
        "BONUS_ISSUE": "CORPORATE_ACTION",
        "MIGRATION": "DELIVERY",
    }.get(tx_type, "CASH")
    row = dict.fromkeys(COLUMNS, "")
    row.update(
        datetime=f"{day}T{time}.000000Z",
        date=day,
        account_type=account,
        category=category,
        type=tx_type,
        currency="EUR",
        transaction_id=f"tx-{next(_ids):04d}",
    )
    row.update({key: str(value) for key, value in cells.items()})
    return row


def to_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


ACME = {"symbol": "XX0000000001", "name": "Acme", "asset_class": "STOCK"}
GLOBEX = {"symbol": "XX0000000002", "name": "Globex", "asset_class": "STOCK"}
FUND = {"symbol": "XX0000000003", "name": "World Fund (Acc)", "asset_class": "FUND"}


@pytest.fixture
def sample_rows() -> list[dict]:
    """A small invented history covering every case the calculations handle."""
    return [
        # Deposits: 100 € by card (0.70 € fee), 50 € by bank transfer (free).
        tx("2025-01-02", "CUSTOMER_INPAYMENT", amount="100.70", fee="-0.70"),
        tx("2025-01-03", "TRANSFER_INBOUND", amount="50.00"),
        # Acme: bought twice, half sold -> open line with a realised part.
        tx("2025-01-06", "BUY", **ACME, shares="1.0", price="20", amount="-20.00", fee="-1.00"),
        tx("2025-02-10", "BUY", **ACME, shares="1.0", price="30", amount="-30.00", fee="-1.00"),
        tx("2025-04-15", "SELL", **ACME, shares="-1.0", price="40", amount="40.00", fee="-1.00"),
        # Globex: bought, split 2-for-1, fully sold at a loss -> closed line.
        tx("2025-02-03", "BUY", **GLOBEX, shares="2.0", price="10", amount="-20.00", fee="-1.00"),
        tx("2025-03-01", "SPLIT", **GLOBEX, shares="2.0"),
        tx("2025-05-05", "SELL", **GLOBEX, shares="-4.0", price="4", amount="16.00", fee="-1.00"),
        # Fund: two free savings-plan executions, then a migration pair.
        tx("2025-03-03", "BUY", **FUND, shares="0.5", price="20", amount="-10.00"),
        tx("2025-04-01", "BUY", **FUND, shares="0.4", price="25", amount="-10.00"),
        tx("2025-04-02", "MIGRATION", **FUND, shares="-0.9", price="25", time="09:00:00"),
        tx("2025-04-02", "MIGRATION", **FUND, shares="0.9", price="25", time="09:00:01"),
        # Income, card spending, internal transfer to the PEA.
        tx("2025-03-20", "DIVIDEND", **ACME, shares="2.0", amount="0.50", tax="-0.15"),
        tx("2025-03-31", "INTEREST_PAYMENT", amount="0.10", tax="-0.03"),
        tx("2025-04-10", "CARD_TRANSACTION", name="Boulangerie", amount="-5.00", mcc_code="5462"),
        tx("2025-06-02", "TRANSFER_OUT", amount="-30.00", description="Versement PEA"),
        tx("2025-06-02", "TRANSFER_IN", account="PEA", amount="30.00"),
        # PEA: proportional fee and a transaction tax.
        tx(
            "2025-06-03",
            "BUY",
            account="PEA",
            **GLOBEX,
            shares="2.0",
            price="10",
            amount="-20.00",
            fee="-0.10",
            tax="-0.08",
        ),
    ]


@pytest.fixture
def sample_csv(sample_rows) -> str:
    return to_csv(sample_rows)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()
