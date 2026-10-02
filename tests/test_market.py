from decimal import Decimal as D

import pytest

from cockpit import store
from cockpit.importers import tr_csv
from cockpit.market import service, yahoo
from cockpit.market.provider import Listing, ProviderError
from tests.conftest import ACME, GLOBEX, to_csv, tx
from tests.fakes import FakeProvider, series

ACME_ISIN, GLOBEX_ISIN, FUND_ISIN = "XX0000000001", "XX0000000002", "XX0000000003"


@pytest.fixture
def provider():
    fake = FakeProvider()
    fake.listings[ACME_ISIN] = [Listing("ACME.PA", "Acme SA", "PAR", "EQUITY")]
    fake.listings[GLOBEX_ISIN] = [Listing("GLBX", "Globex Inc.", "NMS", "EQUITY")]
    fake.charts["ACME.PA"] = series(
        "ACME.PA", "EUR", "PAR", {"2025-06-27": "29", "2025-06-30": "30"}, previous="29"
    )
    fake.charts["GLBX"] = series(
        "GLBX", "USD", "NMS", {"2025-06-27": "11", "2025-06-30": "12"}, previous="11"
    )
    fake.charts["EURUSD=X"] = series(
        "EURUSD=X", "USD", "CCY", {"2025-06-27": "1.10", "2025-06-30": "1.20"}
    )
    return fake


@pytest.fixture
def loaded(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    return conn


# -- Reading Yahoo's answers ---------------------------------------------------


def test_search_answer_keeps_securities_only():
    payload = {
        "quotes": [
            {
                "symbol": "AI.PA",
                "longname": "L'Air Liquide",
                "exchange": "PAR",
                "quoteType": "EQUITY",
            },
            {"symbol": "AIL.DE", "shortname": "AIR LIQUIDE", "exchange": "GER", "quoteType": "ETF"},
            {"symbol": "^FCHI", "exchange": "PAR", "quoteType": "INDEX"},
            {"shortname": "no symbol", "quoteType": "EQUITY"},
        ]
    }
    assert yahoo.parse_search(payload) == [
        Listing("AI.PA", "L'Air Liquide", "PAR", "EQUITY"),
        Listing("AIL.DE", "AIR LIQUIDE", "GER", "ETF"),
    ]
    with pytest.raises(ProviderError) as error:
        yahoo.parse_search({"finance": {"error": "x"}})
    assert error.value.kind == "format"


def test_chart_answer():
    payload = {"chart": {"error": None, "result": [{
        "meta": {"currency": "EUR", "symbol": "AI.PA", "exchangeName": "PAR",
                 "fullExchangeName": "Paris", "regularMarketPrice": 166.16,
                 "chartPreviousClose": 165.2, "regularMarketTime": 1759413600},
        "timestamp": [1759388400, 1759388700, 1759389000],
        "indicators": {"quote": [{"close": [165.5, None, 166.16]}]},
    }]}}  # fmt: skip
    chart = yahoo.parse_chart(payload, "AI.PA")
    assert (chart.currency, chart.exchange, chart.exchange_name) == ("EUR", "PAR", "Paris")
    assert (chart.price, chart.previous_close) == (D("166.16"), D("165.2"))
    assert [(p.time, p.close) for p in chart.points] == [
        (1759388400, D("165.5")),
        (1759389000, D("166.16")),  # the gap exported as null is left out
    ]


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        ({"chart": {"result": None, "error": {"code": "Not Found"}}}, "not_found"),
        ({"chart": {"result": [], "error": None}}, "not_found"),
        ({"chart": {"result": [{"meta": {}}], "error": None}}, "format"),
        ({"unexpected": True}, "format"),
    ],
)
def test_unusable_chart_answers(payload, kind):
    with pytest.raises(ProviderError) as error:
        yahoo.parse_chart(payload, "X")
    assert error.value.kind == kind


# -- Choosing a listing, currencies ----------------------------------------------


def test_funds_prefer_a_euro_listing_and_shares_the_first_one():
    listings = [
        Listing("WRLD.L", "World Fund", "LSE", "ETF"),
        Listing("WRLD.DE", "World Fund", "GER", "ETF"),
    ]
    assert service.choose_listing("IE00ABCDEFG1", listings).symbol == "WRLD.DE"
    assert service.choose_listing("US0000000001", listings).symbol == "WRLD.L"
    assert service.choose_listing("IE00ABCDEFG1", listings[:1]).symbol == "WRLD.L"
    assert service.choose_listing("IE00ABCDEFG1", []) is None


def test_delay_falls_back_on_the_symbol_suffix():
    assert service.delay_minutes("PAR", "ACME.PA") == 15
    assert service.delay_minutes("IOB", "SMSN.IL") == 20  # exchange code not in the table
    assert service.delay_minutes("", "COLO-B.CO") == 0
    assert service.delay_minutes("NMS", "ACME") == 0
    assert service.delay_minutes("???", "ACME") is None  # no suffix, unknown exchange
    assert service.delay_minutes(None, None) is None


def test_pence_are_brought_back_to_pounds():
    assert service.normalise(D("1234"), "GBp") == (D("12.34"), "GBP")
    assert service.normalise(D("12"), "USD") == (D("12"), "USD")


# -- Latest quotes -----------------------------------------------------------------


def test_refresh_stores_quotes_in_euros(loaded, provider):
    market = service.Market(provider)
    outcome = market.refresh_quotes(loaded, [ACME_ISIN, GLOBEX_ISIN, FUND_ISIN])
    assert (outcome.updated, outcome.skipped, outcome.errors) == (2, 1, [])  # fund: no listing

    live = store.quotes(loaded)
    assert live[ACME_ISIN]["price_eur"] == 30.0
    assert (live[ACME_ISIN]["change"], live[ACME_ISIN]["delay_minutes"]) == (0.0345, 15)
    globex = live[GLOBEX_ISIN]
    assert (globex["price"], globex["currency"], globex["price_eur"]) == (12.0, "USD", 10.0)
    assert globex["delay_minutes"] == 0

    # The quote also becomes the price of the day, so the valuation follows.
    positions = {(p["account"], p["isin"]): p for p in store.current_report(loaded)["positions"]}
    assert positions[("CTO", ACME_ISIN)]["value"] == 30.0
    assert positions[("PEA", GLOBEX_ISIN)]["value"] == 20.0  # 2 shares at 12 USD = 10 EUR each
    assert positions[("CTO", ACME_ISIN)]["quote"]["price"] == 30.0
    assert positions[("CTO", FUND_ISIN)]["quote"] is None

    status = {i["isin"]: i for i in service.instruments(loaded)}
    assert (status[ACME_ISIN]["symbol"], status[ACME_ISIN]["status"]) == ("ACME.PA", "ok")
    assert status[FUND_ISIN]["status"] == "introuvable"
    assert (status[GLOBEX_ISIN]["currency"], status[GLOBEX_ISIN]["held"]) == ("USD", True)


def test_quotes_are_not_asked_twice_within_a_minute(loaded, provider):
    market = service.Market(provider)
    market.refresh_quotes(loaded, [ACME_ISIN])
    provider.calls.clear()
    again = market.refresh_quotes(loaded, [ACME_ISIN])
    assert (again.updated, again.skipped, provider.calls) == (0, 1, [])


def test_a_refusal_stops_the_refresh(loaded, provider):
    provider.fail = ProviderError("refused", "Yahoo a refusé la requête (HTTP 429)")
    outcome = service.Market(provider).refresh_quotes(loaded, [ACME_ISIN, GLOBEX_ISIN])
    assert outcome.refused and outcome.updated == 0
    assert len(outcome.errors) == 1 and len(provider.calls) == 1  # did not insist
    assert store.quotes(loaded) == {}


def test_symbol_typed_by_hand(loaded, provider):
    market = service.Market(provider)
    market.refresh_quotes(loaded, [FUND_ISIN])  # not found by ISIN
    provider.charts["WRLD.DE"] = series("WRLD.DE", "EUR", "GER", {"2025-06-30": "25"})
    market.set_symbol(loaded, FUND_ISIN, " WRLD.DE ")
    assert market.refresh_quotes(loaded, [FUND_ISIN]).updated == 1
    status = {i["isin"]: i for i in service.instruments(loaded)}[FUND_ISIN]
    assert (status["symbol"], status["status"], status["exchange"]) == ("WRLD.DE", "manuel", "GER")

    market.set_symbol(loaded, FUND_ISIN, "")  # back to a search by ISIN
    assert {i["isin"]: i for i in service.instruments(loaded)}[FUND_ISIN]["symbol"] is None


def test_candidates_by_name_when_the_isin_finds_nothing(loaded, provider):
    assert service.search_terms("World Fund (Acc)") == "World Fund"
    assert service.search_terms("  Acme  (A) SA ") == "Acme SA"
    assert service.search_terms("(GDR)") == "(GDR)"

    provider.listings["World Fund"] = [
        Listing("WRLD.DE", "World Fund", "GER", "ETF", "XETRA"),
        Listing("WRLD.L", "World Fund", "LSE", "ETF"),
        Listing("GONE", "World Fund Old", "NMS", "ETF"),
    ]
    provider.charts["WRLD.DE"] = series("WRLD.DE", "EUR", "GER", {"2025-06-30": "25"})
    provider.charts["WRLD.L"] = series("WRLD.L", "GBp", "LSE", {"2025-06-30": "2400"})
    provider.charts["EURGBP=X"] = series("EURGBP=X", "GBP", "CCY", {"2025-06-30": "0.80"})
    market = service.Market(provider)

    found = market.candidates(loaded, FUND_ISIN)
    assert (found["by"], found["query"]) == ("nom", "World Fund")
    assert [c["symbol"] for c in found["candidates"]] == ["WRLD.DE", "WRLD.L", "GONE"]
    german, london, gone = found["candidates"]
    assert (german["exchange"], german["price"], german["price_eur"]) == ("XETRA", 25.0, 25.0)
    assert (london["exchange"], london["price"], london["currency"]) == ("LSE", 24.0, "GBP")
    assert london["price_eur"] == 30.0
    assert gone["price"] is None  # unknown symbol: listed without a price
    assert found["last_trade"]["price"] > 0
    # Nothing is chosen for the person.
    assert {i["isin"]: i for i in service.instruments(loaded)}[FUND_ISIN]["symbol"] is None

    by_isin = market.candidates(loaded, ACME_ISIN)
    assert (by_isin["by"], [c["symbol"] for c in by_isin["candidates"]]) == ("isin", ["ACME.PA"])

    with pytest.raises(ProviderError):
        market.candidates(loaded, "UNKNOWN")


def test_candidates_stop_asking_prices_after_a_refusal(loaded, provider):
    provider.listings["World Fund"] = [
        Listing("WRLD.DE", "World Fund", "GER", "ETF"),
        Listing("WRLD.L", "World Fund", "LSE", "ETF"),
    ]

    class RefusingCharts(FakeProvider):
        def chart(self, symbol, span, interval):
            self.calls.append(("chart", symbol, span, interval))
            raise ProviderError("refused", "HTTP 429")

    refusing = RefusingCharts()
    refusing.listings = provider.listings
    found = service.Market(refusing).candidates(loaded, FUND_ISIN)
    assert [c["price"] for c in found["candidates"]] == [None, None]
    assert [call for call in refusing.calls if call[0] == "chart"] == [
        ("chart", "WRLD.DE", "1d", "5m")
    ]


# -- History -------------------------------------------------------------------------


def test_history_is_converted_with_the_rate_of_each_day(loaded, provider):
    store.set_price(loaded, ACME_ISIN, D("99"), "2025-06-27", "manuel")
    outcome = service.Market(provider).load_history(loaded, [ACME_ISIN, GLOBEX_ISIN], "2025-01-02")
    assert (outcome.updated, outcome.errors) == (2, [])

    history = store.price_history(loaded)
    assert history[GLOBEX_ISIN] == [("2025-06-27", D("10")), ("2025-06-30", D("10"))]
    # A price typed in by hand is never overwritten by the source.
    assert history[ACME_ISIN] == [("2025-06-27", D("99")), ("2025-06-30", D("30"))]
    assert store.recent_prices(loaded, GLOBEX_ISIN) == [10.0, 10.0]


def test_chart_is_cached_and_validated(loaded, provider):
    market = service.Market(provider)
    first = market.chart(loaded, ACME_ISIN, "1j")
    assert (first["symbol"], first["currency"], first["intraday"]) == ("ACME.PA", "EUR", True)
    assert first["delay_minutes"] == 15 and len(first["points"]) == 2
    calls = len(provider.calls)
    market.chart(loaded, ACME_ISIN, "1j")
    assert len(provider.calls) == calls  # served from the cache
    assert market.chart(loaded, ACME_ISIN, "1a")["intraday"] is False

    with pytest.raises(ValueError):
        market.chart(loaded, ACME_ISIN, "3 semaines")
    with pytest.raises(ProviderError):
        market.chart(loaded, FUND_ISIN, "1j")


# -- Value over time ---------------------------------------------------------------


def test_value_history_restates_quantities_before_a_split(conn):
    rows = [
        tx("2025-01-06", "BUY", **GLOBEX, shares="2.0", price="100", amount="-200.00"),
        tx("2025-03-01", "SPLIT", **GLOBEX, shares="2.0"),  # 2-for-1
        tx("2025-04-01", "BUY", **ACME, shares="1.0", price="50", amount="-50.00"),
        tx("2025-05-05", "SELL", **GLOBEX, shares="-4.0", price="60", amount="240.00"),
    ]
    tr_csv.import_csv(conn, to_csv(rows))
    # Published histories are split-adjusted: 100 before the split is shown as 50.
    for day, price in [("2025-01-06", "50"), ("2025-02-03", "55"), ("2025-03-03", "52")]:
        store.set_price(conn, GLOBEX_ISIN, D(price), day, "fake")

    data = store.value_history(conn)
    points = {p["date"]: p for p in data["points"]}
    assert points["2025-01-06"]["value"] == 200.0  # 4 restated shares at 50, not 2
    assert points["2025-02-03"]["value"] == 220.0
    assert points["2025-03-03"]["value"] == 208.0
    # Acme has no price: counted at cost, and reported as such.
    april = points["2025-04-01"]
    assert (april["value"], april["at_cost"], april["invested"]) == (258.0, 50.0, 250.0)
    may = points["2025-05-05"]
    assert (may["value"], may["invested"], may["accounts"]) == (50.0, 10.0, {"CTO": 50.0})
    assert data["unpriced"] == ["Acme"]


def test_value_history_without_transactions(conn):
    assert store.value_history(conn) == {"points": [], "unpriced": []}


def test_an_unreachable_source_is_asked_once(loaded, provider):
    provider.fail = ProviderError("network", "Yahoo est injoignable")
    outcome = service.Market(provider).refresh_quotes(loaded, [ACME_ISIN, GLOBEX_ISIN])
    assert (outcome.unreachable, outcome.refused, outcome.updated) == (True, False, 0)
    assert len(provider.calls) == 1  # no queue of time-outs, one per instrument
