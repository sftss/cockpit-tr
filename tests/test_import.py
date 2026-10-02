import pytest

from cockpit.importers import tr_csv
from tests.conftest import to_csv, tx


def test_import_is_idempotent(conn, sample_csv, sample_rows):
    first = tr_csv.import_csv(conn, sample_csv)
    assert (first.total, first.inserted, first.already_present) == (len(sample_rows),) * 2 + (0,)
    assert first.accounts == {"CTO": 16, "PEA": 2}
    assert (first.date_min, first.date_max) == ("2025-01-02", "2025-06-03")

    second = tr_csv.import_csv(conn, sample_csv)
    assert (second.inserted, second.already_present) == (0, len(sample_rows))
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == len(sample_rows)


def test_overlapping_export_adds_only_new_lines(conn, sample_rows):
    tr_csv.import_csv(conn, to_csv(sample_rows[:10]))
    report = tr_csv.import_csv(conn, to_csv(sample_rows))
    assert (report.inserted, report.already_present) == (len(sample_rows) - 10, 10)


def test_instruments_come_from_securities_only(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    names = [row[0] for row in conn.execute("SELECT name FROM instruments ORDER BY name")]
    assert names == ["Acme", "Globex", "World Fund (Acc)"]  # the bakery is not an instrument


def test_other_files_are_refused(conn):
    with pytest.raises(tr_csv.CsvFormatError, match="colonnes absentes"):
        tr_csv.import_csv(conn, "date;libelle;montant\n2025-01-01;x;1\n")
    with pytest.raises(tr_csv.CsvFormatError, match="vide"):
        tr_csv.import_csv(conn, "")


def test_unknown_types_and_bad_lines_are_reported(conn):
    rows = [
        tx("2025-01-02", "CUSTOMER_INPAYMENT", amount="10.00"),
        tx("2025-01-03", "SOMETHING_NEW", amount="1.00"),
        tx(
            "2025-01-04",
            "BUY",
            symbol="XX0000000001",
            name="Acme",
            asset_class="STOCK",
            shares="abc",
            amount="-5.00",
        ),
    ]
    report = tr_csv.import_csv(conn, to_csv(rows))
    assert report.inserted == 2
    assert report.unknown_types == {"SOMETHING_NEW": 1}
    assert report.rejected == ["ligne 4 : valeur illisible dans shares"]


def test_semicolon_separated_and_bom(conn, sample_csv):
    text = "﻿" + sample_csv.replace('","', '";"')
    assert tr_csv.import_csv(conn, text).inserted == 18
