"""Charts of an instrument, performance against a benchmark, spread of the
portfolio. Companies, prices and trades are invented."""

import json
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cockpit import allocation, performance, store
from cockpit.api import create_app
from cockpit.importers import tr_csv
from cockpit.market import service, yahoo
from cockpit.market.provider import Listing, Point, ProviderError, Series
from tests.conftest import ACME, to_csv, tx
from tests.fakes import FakeProvider, epoch, series

ROOT = Path(__file__).resolve().parents[1]
ACME_ISIN, GLOBEX_ISIN, FUND_ISIN = "XX0000000001", "XX0000000002", "XX0000000003"
CSV = {"content-type": "text/csv"}


def weekdays(first: str, last: str) -> list[str]:
    day, end, days = date.fromisoformat(first), date.fromisoformat(last), []
    while day <= end:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    return days


def daily(symbol: str, currency: str, exchange: str, first: str, last: str) -> Series:
    """One bar per weekday; the close climbs by one each day from 100, the bar
    spans two below to three above it, and 1 000 shares change hands."""
    points = [
        Point(
            epoch(day),
            D(100 + index),
            open=D(99 + index),
            high=D(103 + index),
            low=D(98 + index),
            volume=D(1000),
        )
        for index, day in enumerate(weekdays(first, last))
    ]
    return Series(
        symbol=symbol,
        currency=currency,
        exchange=exchange,
        exchange_name=exchange,
        price=points[-1].close,
        market_time=points[-1].time,
        points=points,
    )


@pytest.fixture
def provider():
    fake = FakeProvider()
    fake.listings[ACME_ISIN] = [Listing("ACME.PA", "Acme SA", "PAR", "EQUITY")]
    fake.listings[GLOBEX_ISIN] = [Listing("GLBX", "Globex Inc.", "NMS", "EQUITY")]
    fake.charts["ACME.PA"] = daily("ACME.PA", "EUR", "PAR", "2024-07-01", "2025-06-30")
    fake.charts["GLBX"] = daily("GLBX", "USD", "NMS", "2025-06-23", "2025-06-30")
    return fake


@pytest.fixture
def loaded(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    return conn


# -- Bars from the source ------------------------------------------------------------


def test_a_chart_answer_carries_whole_bars_when_they_are_coherent():
    quote = {
        "open": [10, 11, 12, None],
        "high": [12, 13, 11.5, 14],
        "low": [9, 10.5, 11, 12],
        "close": [11, 12, 12, None],
        "volume": [500, None, 300, 100],
    }
    payload = {"chart": {"error": None, "result": [{
        "meta": {"currency": "EUR", "symbol": "ACME.PA", "exchangeName": "PAR"},
        "timestamp": [100, 200, 300, 400],
        "indicators": {"quote": [quote]},
    }]}}  # fmt: skip
    points = yahoo.parse_chart(payload, "ACME.PA").points
    assert [(p.time, p.close) for p in points] == [(100, D("11")), (200, D("12")), (300, D("12"))]
    assert (points[0].open, points[0].high, points[0].low) == (D("10"), D("12"), D("9"))
    assert (points[0].volume, points[1].volume) == (D("500"), None)
    # A close outside its own bar: the bar is not drawn, the close is kept.
    assert (points[2].open, points[2].high, points[2].low) == (None, None, None)


def test_moving_average_waits_for_enough_values():
    values = [D(v) for v in (2, 4, 6, 8)]
    assert service.moving_average(values, 2) == [None, D(3), D(5), D(7)]
    assert service.moving_average(values, 5) == [None] * 4
    assert service.moving_average([], 3) == []


# -- The chart of one instrument -------------------------------------------------------


def test_a_period_shows_its_days_and_averages_computed_on_the_longer_history(loaded, provider):
    market = service.Market(provider)
    year = market.chart(loaded, ACME_ISIN, "1a")
    assert ("chart", "ACME.PA", "2y", "1d") in provider.calls  # asked longer than shown
    assert len(year["points"]) == 261  # the whole year of weekdays received

    month = market.chart(loaded, ACME_ISIN, "1m")
    days = [service._day(p["time"]) for p in month["points"]]
    assert (days[0], days[-1], len(days)) == ("2025-05-30", "2025-06-30", 22)
    last = month["points"][-1]
    assert (last["value"], last["open"], last["high"], last["low"]) == (360.0, 359.0, 363.0, 358.0)
    assert last["volume"] == 1000.0

    # The close climbs by one a day: its mean over 50 days trails it by 24.5, over 200 by 99.5.
    fifty, two_hundred = month["averages"]
    assert (fifty["window"], fifty["label"]) == (50, "Moyenne 50 jours")
    assert fifty["points"][-1] == {"time": last["time"], "value": 335.5}
    assert two_hundred["points"][-1]["value"] == 260.5
    assert len(fifty["points"]) == len(two_hundred["points"]) == 22  # from the first day shown

    # One request served the three periods.
    market.chart(loaded, ACME_ISIN, "6m")
    assert [c for c in provider.calls if c[0] == "chart"] == [("chart", "ACME.PA", "2y", "1d")]
    assert market.chart(loaded, ACME_ISIN, "1j")["averages"] == []


def test_an_average_without_enough_history_is_left_out(loaded, provider):
    provider.charts["ACME.PA"] = daily("ACME.PA", "EUR", "PAR", "2025-03-03", "2025-06-30")
    chart = service.Market(provider).chart(loaded, ACME_ISIN, "6m")
    assert [average["window"] for average in chart["averages"]] == [50]
    assert len(chart["averages"][0]["points"]) == len(chart["points"]) - 49


def test_purchases_and_sales_are_placed_on_the_bar_of_their_day(loaded, provider):
    market = service.Market(provider)
    marks = market.chart(loaded, ACME_ISIN, "6m")["trades"]
    assert [(m["date"], m["side"], m["shares"], m["price"]) for m in marks] == [
        ("2025-01-06", "achat", 1.0, 20.0),
        ("2025-02-10", "achat", 1.0, 30.0),
        ("2025-04-15", "vente", 1.0, 40.0),
    ]
    assert [service._day(m["time"]) for m in marks] == ["2025-01-06", "2025-02-10", "2025-04-15"]
    assert marks[0]["fee"] == 1.0 and marks[0]["account"] == "CTO"
    # Older than the first bar shown: left out.
    assert market.chart(loaded, ACME_ISIN, "1m")["trades"] == []


def test_a_trade_on_a_day_without_a_bar_goes_to_the_bar_before(conn, provider):
    rows = [tx("2025-06-28", "BUY", **ACME, shares="1.0", price="20", amount="-20.00")]  # Saturday
    tr_csv.import_csv(conn, to_csv(rows))
    marks = service.Market(provider).chart(conn, ACME_ISIN, "1m")["trades"]
    assert [service._day(m["time"]) for m in marks] == ["2025-06-27"]


def test_a_chart_in_euros_uses_the_rate_of_each_day(loaded, provider):
    provider.charts["EURUSD=X"] = series(
        "EURUSD=X", "USD", "CCY", {"2025-06-23": "1.00", "2025-06-27": "1.25", "2025-06-30": "2.00"}
    )
    market = service.Market(provider)
    native = market.chart(loaded, GLOBEX_ISIN, "1m")
    assert (native["currency"], native["native_currency"]) == ("USD", "USD")
    assert [p["value"] for p in native["points"]] == [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]

    euros = market.chart(loaded, GLOBEX_ISIN, "1m", in_euros=True)
    assert (euros["currency"], euros["native_currency"]) == ("EUR", "USD")
    # 23 to 26 June at 1.00, the 27th at 1.25, the 30th at 2.00.
    assert [p["value"] for p in euros["points"]] == [100.0, 101.0, 102.0, 103.0, 83.2, 52.5]
    assert (euros["points"][-1]["high"], euros["points"][-1]["volume"]) == (54.0, 1000.0)
    # An instrument already quoted in euros is left as it is.
    assert market.chart(loaded, ACME_ISIN, "1m", in_euros=True)["currency"] == "EUR"


def test_without_a_rate_history_todays_rate_is_used(loaded, provider):
    class NoHistory(FakeProvider):
        def chart(self, symbol, span, interval):
            if symbol == "EURUSD=X" and interval == "1d":
                raise ProviderError("not_found", "pas d'historique")
            return super().chart(symbol, span, interval)

    fake = NoHistory()
    fake.listings, fake.charts = provider.listings, dict(provider.charts)
    fake.charts["EURUSD=X"] = series("EURUSD=X", "USD", "CCY", {"2025-06-30": "2.00"})
    euros = service.Market(fake).chart(loaded, GLOBEX_ISIN, "1m", in_euros=True)
    assert [p["value"] for p in euros["points"]][-2:] == [52.0, 52.5]


def test_key_figures_come_from_the_daily_bars(loaded, provider):
    stats = service.Market(provider).stats(loaded, ACME_ISIN)
    assert (stats["currency"], stats["as_of"]) == ("EUR", "2025-06-30")
    assert (stats["price"], stats["previous_close"], stats["open"]) == (360.0, 359.0, 359.0)
    assert (stats["day_low"], stats["day_high"]) == (358.0, 363.0)
    # A year back is the first bar (1 July 2024): its low is 98, the latest high 363.
    assert (stats["year_low"], stats["year_high"]) == (98.0, 363.0)
    assert (stats["volume"], stats["average_volume"]) == (1000.0, 1000.0)
    changes = {c["label"]: c["change"] for c in stats["changes"]}
    assert changes["1 mois"] == 0.0619  # 360 against 339 on 30 May
    assert changes["Depuis le 1er janvier"] == 0.5584  # against 231 on 31 December
    assert changes["6 mois"] == 0.5721  # against 229 on 27 December
    assert changes["1 an"] is None  # the history starts less than a year ago
    with pytest.raises(ProviderError):
        service.Market(provider).stats(loaded, FUND_ISIN)  # no listing found


@pytest.fixture
def client(tmp_path, sample_csv, provider):
    client = TestClient(create_app(tmp_path / "charts.db", provider=provider))
    client.post("/api/import/csv", content=sample_csv.encode(), headers=CSV)
    return client


def test_the_page_of_an_instrument_over_the_api(client, provider):
    acme = client.get(f"/api/securities/{ACME_ISIN}").json()
    assert (acme["name"], acme["held"], acme["stats"]["price"]) == ("Acme", True, 360.0)
    assert [(t["date"], t["side"]) for t in acme["trades"]] == [
        ("2025-01-06", "achat"),
        ("2025-02-10", "achat"),
        ("2025-04-15", "vente"),
    ]
    chart = client.get(f"/api/market/chart/{ACME_ISIN}?range=6m&devise=eur").json()
    assert len(chart["trades"]) == 3 and chart["averages"][0]["window"] == 50

    # A line sold out keeps its page; without a listing, the trades still show.
    fund = client.get(f"/api/securities/{FUND_ISIN}").json()
    assert fund["stats"] is None and fund["stats_error"] and len(fund["trades"]) == 2
    assert client.get("/api/securities/XX0000000009").status_code == 404


# -- Performance ---------------------------------------------------------------------


def point(day: str, value: float, bought: float = 0, sold: float = 0) -> dict:
    return {"date": day, "value": value, "bought": bought, "sold": sold}


def test_performance_sets_purchases_and_sales_aside():
    points = [
        point("d1", 100, bought=100),  # bought at the close: no change yet
        point("d2", 110),  # +10 %
        point("d3", 210, bought=100),  # money added, prices flat
        point("d4", 105, sold=105),  # half sold, prices flat
        point("d5", 0, sold=126),  # the rest sold 20 % higher
        point("d6", 50, bought=50),  # back in: the index carries on from where it was
        point("d7", 55),  # +10 %
    ]
    index = performance.portfolio_index(points)
    assert [round(float(value), 4) for value in index] == [1, 1.1, 1.1, 1.1, 1.32, 1.32, 1.452]


def test_a_benchmark_starts_at_its_first_price():
    points = [
        point("2025-01-02", 100, bought=100),
        point("2025-01-03", 110),
        point("2025-01-06", 99),
    ]
    benchmark = [("2025-01-03", D("50")), ("2025-01-04", D("51"))]
    assert performance.series(points, benchmark) == [
        {"date": "2025-01-02", "portfolio": 1.0, "benchmark": None},
        {"date": "2025-01-03", "portfolio": 1.1, "benchmark": 50.0},
        {"date": "2025-01-06", "portfolio": 0.99, "benchmark": 51.0},  # last price known
    ]


def test_value_history_reports_what_was_bought_and_sold_each_day(loaded):
    points = {p["date"]: p for p in store.value_history(loaded)["points"]}
    assert (points["2025-01-06"]["bought"], points["2025-01-06"]["sold"]) == (20.0, 0.0)
    assert (points["2025-04-15"]["bought"], points["2025-04-15"]["sold"]) == (0.0, 40.0)


def test_performance_against_a_fund_of_the_portfolio_or_an_index(client, provider):
    client.put(f"/api/prices/{FUND_ISIN}", json={"price": "20", "date": "2025-03-03"})
    client.put(f"/api/prices/{FUND_ISIN}", json={"price": "25", "date": "2025-04-01"})
    view = client.get("/api/portfolio/performance").json()
    assert [b["id"] for b in view["benchmarks"]] == [FUND_ISIN, "msci-world", "sp500", "cac40"]
    assert view["benchmark"] == {"id": FUND_ISIN, "label": "World Fund (Acc)"}  # a fund first
    by_day = {p["date"]: p for p in view["points"]}
    assert by_day["2025-01-06"]["benchmark"] is None
    assert (by_day["2025-03-03"]["benchmark"], by_day["2025-06-03"]["benchmark"]) == (20.0, 25.0)
    assert by_day["2025-01-06"]["portfolio"] == 1.0 and view["error"] is None

    provider.charts["EUNL.DE"] = series("EUNL.DE", "EUR", "GER", {"2025-01-06": "80"})
    world = client.get("/api/portfolio/performance?indice=msci-world").json()
    assert world["benchmark"]["id"] == "msci-world"
    assert world["points"][0]["benchmark"] == 80.0
    # The source does not know the index: the portfolio's own curve still comes.
    missing = client.get("/api/portfolio/performance?indice=cac40").json()
    assert missing["error"] and missing["points"][0]["portfolio"] == 1.0
    assert missing["points"][0]["benchmark"] is None


# -- Spread of the portfolio -----------------------------------------------------------


def position(name: str, isin: str, value: float, account="CTO", kind="STOCK") -> dict:
    return {"name": name, "isin": isin, "value": value, "account": account, "asset_class": kind}


UNIVERSE = {
    "A": {"pays": "France", "secteur": "Industrie"},
    "B": {"pays": "États-Unis", "secteur": "Santé"},
    "C": {"pays": "France", "secteur": "Santé"},
}


def test_the_portfolio_is_spread_along_five_dimensions():
    positions = [
        position("Alpha", "A", 50),
        position("Beta", "B", 30, account="PEA"),
        position("Gamma", "C", 10),
        position("Delta", "D", 6),  # not in the list of companies
        position("World Fund", "F", 4, kind="FUND"),
    ]
    view = allocation.breakdown(positions, "value", {"A": "EUR", "B": "USD", "C": "EUR"}, UNIVERSE)
    assert (view["basis"], view["total"], view["unclassified"]) == ("value", 100.0, ["Delta"])
    groups = {
        d["id"]: [(g["label"], g["weight"], g["lines"]) for g in d["groups"]]
        for d in view["dimensions"]
    }
    assert groups["compte"] == [("Compte-titres", 0.7, 4), ("PEA", 0.3, 1)]
    assert groups["type"] == [("Actions", 0.96, 4), ("Fonds (ETF)", 0.04, 1)]
    assert groups["devise"] == [("EUR", 0.6, 2), ("USD", 0.3, 1), ("Non connue", 0.1, 2)]
    # A fund is one block, an unknown company is said to be unclassified: both come last.
    assert groups["pays"] == [
        ("France", 0.6, 2),
        ("États-Unis", 0.3, 1),
        ("Fonds (non détaillé)", 0.04, 1),
        ("Non classé", 0.06, 1),
    ]
    assert groups["secteur"][:2] == [("Industrie", 0.5, 1), ("Santé", 0.4, 2)]


def test_beyond_eight_groups_the_smallest_are_gathered():
    positions = [position(f"L{n}", f"I{n}", 10 - n) for n in range(10)]
    universe = {f"I{n}": {"pays": f"Pays {n}", "secteur": "Industrie"} for n in range(10)}
    view = allocation.breakdown(positions, "value", {}, universe)
    countries = next(d for d in view["dimensions"] if d["id"] == "pays")["groups"]
    assert [g["label"] for g in countries] == [f"Pays {n}" for n in range(7)] + ["Autres"]
    assert (countries[-1]["amount"], countries[-1]["lines"]) == (6.0, 3)  # 3 + 2 + 1
    assert abs(sum(g["weight"] for g in countries) - 1) < 0.001
    # Eight groups are still shown one by one.
    eight = allocation.breakdown(positions[:8], "value", {}, universe)
    assert len(next(d for d in eight["dimensions"] if d["id"] == "pays")["groups"]) == 8


def test_the_spread_over_the_api_uses_the_basis_of_the_weights(client):
    view = client.get("/api/portfolio/allocation").json()
    assert view["basis"] == "cost"  # no price yet: cost, like the weights
    accounts = next(d for d in view["dimensions"] if d["id"] == "compte")["groups"]
    assert [g["label"] for g in accounts] == ["Compte-titres", "PEA"]
    assert view["unclassified"] == ["Acme", "Globex"]  # invented companies: not in the list


SECTORS = {
    "Énergie", "Matériaux", "Industrie", "Consommation discrétionnaire", "Consommation de base",
    "Santé", "Finance", "Technologies de l'information", "Services de communication",
    "Services aux collectivités", "Immobilier",
}  # fmt: skip


def test_every_company_of_the_list_has_a_country_and_a_known_sector():
    listing = json.loads((ROOT / "fiches" / "univers.json").read_text("utf-8"))["titres"]
    for entry in listing:
        assert entry.get("pays"), entry["nom"]
        assert entry.get("secteur") in SECTORS, entry["nom"]
