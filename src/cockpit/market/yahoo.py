"""Yahoo Finance as a market-data source (unofficial, no account, no key).

Yahoo does not publish this interface and may change it, slow it down or
refuse it. The client is deliberately modest: plain HTTPS requests, one at a
time, spaced out, with no attempt to pass for a browser beyond a User-Agent
header. When Yahoo refuses, the caller is told so and the application falls
back to prices typed in by hand.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

from .provider import Listing, Point, ProviderError, Series

SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
USER_AGENT = "Mozilla/5.0 (cockpit-tr; usage personnel)"
KINDS = {"EQUITY", "ETF", "MUTUALFUND"}
MIN_SPACING = 0.3  # seconds between two requests


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


class YahooProvider:
    name = "yahoo"

    def __init__(self, timeout: float = 10.0, user_agent: str = USER_AGENT):
        self._timeout = timeout
        self._user_agent = user_agent
        self._lock = threading.Lock()
        self._last_request = 0.0

    # -- HTTP ---------------------------------------------------------------

    def _get(self, url: str) -> dict:
        with self._lock:  # one request at a time, spaced out
            wait = MIN_SPACING - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                return self._fetch(url)
            finally:
                self._last_request = time.monotonic()

    def _fetch(self, url: str) -> dict:
        request = urllib.request.Request(
            url, headers={"User-Agent": self._user_agent, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ProviderError("not_found", "symbole inconnu de Yahoo") from exc
            if exc.code in (401, 403, 429):
                raise ProviderError(
                    "refused", f"Yahoo a refusé la requête (HTTP {exc.code})"
                ) from exc
            raise ProviderError("network", f"Yahoo a répondu HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError("network", f"Yahoo est injoignable ({exc})") from exc
        try:
            return json.loads(body)
        except ValueError as exc:
            raise ProviderError("format", "réponse de Yahoo illisible") from exc

    # -- Interface ----------------------------------------------------------

    def search(self, query: str) -> list[Listing]:
        params = urllib.parse.urlencode(
            {"q": query, "quotesCount": 10, "newsCount": 0, "listsCount": 0}
        )
        return parse_search(self._get(f"{SEARCH_URL}?{params}"))

    def chart(self, symbol: str, span: str, interval: str) -> Series:
        query = urllib.parse.urlencode(
            {"range": span, "interval": interval, "includePrePost": "false"}
        )
        url = f"{CHART_URL}{urllib.parse.quote(symbol, safe='')}?{query}"
        return parse_chart(self._get(url), symbol)


# -- Parsing (kept apart from HTTP so it can be tested on sample answers) ----


def parse_search(payload: dict) -> list[Listing]:
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        raise ProviderError("format", "réponse de recherche Yahoo inattendue")
    listings = []
    for quote in quotes:
        if not isinstance(quote, dict) or not quote.get("symbol"):
            continue
        if quote.get("quoteType") not in KINDS:
            continue
        listings.append(
            Listing(
                symbol=str(quote["symbol"]),
                name=str(quote.get("longname") or quote.get("shortname") or quote["symbol"]),
                exchange=str(quote.get("exchange") or ""),
                kind=str(quote.get("quoteType")),
                exchange_name=str(quote.get("exchDisp") or ""),
            )
        )
    return listings


def parse_chart(payload: dict, symbol: str) -> Series:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise ProviderError("format", "réponse de cours Yahoo inattendue")
    if chart.get("error"):
        raise ProviderError("not_found", f"Yahoo ne connaît pas le symbole {symbol}")
    results = chart.get("result") or []
    if not results:
        raise ProviderError("not_found", f"Yahoo n'a pas de cours pour {symbol}")
    result = results[0]
    meta = result.get("meta") or {}
    currency = meta.get("currency")
    if not currency:
        raise ProviderError("format", f"devise absente de la réponse pour {symbol}")

    series = Series(
        symbol=str(meta.get("symbol") or symbol),
        currency=str(currency),
        exchange=str(meta.get("exchangeName") or ""),
        exchange_name=str(meta.get("fullExchangeName") or meta.get("exchangeName") or ""),
        price=_decimal(meta.get("regularMarketPrice")),
        previous_close=_decimal(meta.get("chartPreviousClose") or meta.get("previousClose")),
        market_time=meta.get("regularMarketTime"),
    )
    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators") or {}).get("quote") or [{}]
    closes = (quotes[0] or {}).get("close") or []
    for stamp, close in zip(timestamps, closes, strict=False):
        value = _decimal(close)
        if value is not None and isinstance(stamp, int):  # gaps are exported as null
            series.points.append(Point(time=stamp, close=value))
    if series.price is None and series.points:
        series.price = series.points[-1].close
    return series
