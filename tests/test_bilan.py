"""How the weekly readings fared against the market. Prices are invented."""

import json
from datetime import date
from decimal import Decimal as D

from fastapi.testclient import TestClient

from cockpit import bilan
from cockpit.api import create_app
from tests.fakes import FakeProvider, series
from tests.test_veille import UNIVERSE, with_reading


def reading(week: str, friday: str, lean: str) -> dict:
    return {"semaine": week, "du": "", "au": friday, "sens": lean, "confiance": "faible"}


READINGS = [
    reading("2025-W23", "2025-06-06", "hausse"),
    reading("2025-W24", "2025-06-13", "baisse"),
    reading("2025-W25", "2025-06-20", "partagée"),
    reading("2025-W26", "2025-06-27", "hausse"),
]
CLOSES = [
    ("2025-06-06", D("100")),
    ("2025-06-13", D("102")),
    ("2025-06-20", D("103")),
    ("2025-06-27", D("101")),
]


def verdicts(result: dict) -> dict:
    return {row["semaine"]: (row["verdict"], row["variation"]) for row in result["rows"]}


def test_each_balance_is_set_against_the_following_week():
    result = bilan.score(READINGS, CLOSES, date(2025, 6, 30))
    assert [row["semaine"] for row in result["rows"]][0] == "2025-W26"  # newest first
    assert verdicts(result) == {
        "2025-W23": ("juste", 0.02),  # said up, the benchmark rose
        "2025-W24": ("à côté", 0.0098),  # said down, it rose
        "2025-W25": ("non notée", -0.0194),  # took no side: shown, not scored
        "2025-W26": ("en attente", None),  # its week is not over
    }
    assert result["rows"][-1]["jusqu_au"] == "2025-06-13"
    summary = result["summary"]
    assert (summary["scored"], summary["right"]) == (2, 1)
    # "Up, every week" would have been right both times: the score to beat.
    assert summary["always_up_right"] == 2
    assert (summary["unscored"], summary["pending"], summary["enough"]) == (1, 1, False)


def test_a_verdict_waits_for_the_week_to_end():
    one = [READINGS[0]]
    # On the Friday itself the session is not over, whatever price is already there.
    assert verdicts(bilan.score(one, CLOSES, date(2025, 6, 13)))["2025-W23"][0] == "en attente"
    assert verdicts(bilan.score(one, CLOSES, date(2025, 6, 14)))["2025-W23"][0] == "juste"
    # Prices that stop long before the end of the week give no verdict yet.
    stale = [("2025-06-06", D("100")), ("2025-06-07", D("90"))]
    assert verdicts(bilan.score(one, stale, date(2025, 7, 1)))["2025-W23"][0] == "en attente"


def test_a_closed_market_on_friday_uses_the_last_close_before_it():
    closes = [("2025-06-06", D("100")), ("2025-06-12", D("95"))]  # no session on the 13th
    result = bilan.score([reading("2025-W23", "2025-06-06", "baisse")], closes, date(2025, 6, 16))
    assert verdicts(result)["2025-W23"] == ("juste", -0.05)


def test_without_a_price_that_far_back_the_reading_cannot_be_judged():
    result = bilan.score([READINGS[0]], [], date(2025, 7, 1))
    assert verdicts(result)["2025-W23"] == ("inconnu", None)
    assert bilan.score([], CLOSES, date(2025, 7, 1))["rows"] == []


def test_a_rate_is_only_announced_from_ten_scored_weeks():
    fridays = [
        date(2025, 1, 3).fromordinal(date(2025, 1, 3).toordinal() + 7 * n) for n in range(11)
    ]
    closes = [(day.isoformat(), D(100 + n)) for n, day in enumerate(fridays)]
    many = [reading(f"S{n}", day.isoformat(), "hausse") for n, day in enumerate(fridays[:10])]
    summary = bilan.score(many, closes, date(2025, 12, 1))["summary"]
    assert (summary["scored"], summary["right"], summary["enough"]) == (10, 10, True)


def test_the_record_over_the_api(tmp_path, monkeypatch):
    (tmp_path / "fiches").mkdir()
    (tmp_path / "fiches" / "univers.json").write_text(json.dumps({"titres": UNIVERSE}), "utf-8")
    folder = tmp_path / "veilles" / "2025"
    folder.mkdir(parents=True)
    (folder / "2025-W23.json").write_text(json.dumps(with_reading()), "utf-8")
    monkeypatch.setenv("COCKPIT_VEILLES_DIR", str(tmp_path / "veilles"))

    provider = FakeProvider()
    client = TestClient(create_app(tmp_path / "bilan.db", provider=provider))
    # The price source does not answer: the reading is listed, without a verdict.
    missing = client.get("/api/veille/bilan").json()
    assert missing["error"] and missing["rows"][0]["verdict"] == "inconnu"

    provider.charts["EUNL.DE"] = series(
        "EUNL.DE", "EUR", "GER", {"2025-06-06": "100", "2025-06-13": "98"}
    )
    record = client.get("/api/veille/bilan").json()
    assert record["benchmark"].startswith("MSCI World") and record["error"] is None
    row = record["rows"][0]
    assert (row["semaine"], row["sens"], row["verdict"], row["variation"]) == (
        "2025-W23",
        "baisse",
        "juste",
        -0.02,
    )
    assert record["summary"]["always_up_right"] == 0
