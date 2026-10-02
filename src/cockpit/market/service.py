"""Market data for the portfolio: symbols, latest quotes, history, exchange rates.

Everything is stored in euros, because costs are in euros. The price in the
quotation currency is kept beside it.
"""

from __future__ import annotations

import re
import sqlite3
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from ..money import SHARE_EPSILON, dec
from .provider import Listing, Point, ProviderError, QuoteProvider, Series

# Delay of the free quotes per exchange, in minutes, from Yahoo's own table
# (help.yahoo.com/kb/SLN2310.html, read on 02/10/2026). Unknown exchange: None.
DELAY_MINUTES = {
    "NMS": 0, "NGM": 0, "NCM": 0, "NYQ": 0,  # Nasdaq, NYSE
    "CPH": 0,  # Copenhagen
    "PAR": 15, "AMS": 15,  # Euronext Paris, Amsterdam
    "GER": 15, "FRA": 15,  # Xetra, Frankfurt
    "HKG": 15,
    "LSE": 20,
}  # fmt: skip

# The same table by symbol suffix, for exchange codes missing above (Yahoo's
# table is organised by suffix; '.IL' is London's international order book).
SUFFIX_DELAY = {"PA": 15, "AS": 15, "DE": 15, "F": 15, "HK": 15, "L": 20, "IL": 20, "CO": 0}

# For funds (several listings of the same ISIN), prefer one quoted in euros.
FUND_EXCHANGES = ["GER", "PAR", "AMS", "MIL", "FRA"]


@dataclass(frozen=True)
class Range:
    """What one period of the chart asks from the source, and what it shows."""

    span: str  # longer than what is shown when the moving averages need a run-up
    interval: str
    lifetime: int  # seconds an answer is kept
    days: int | None = None  # calendar days shown; None shows everything received
    averages: tuple[int, ...] = ()  # moving averages, counted in bars
    unit: str = "jours"  # what one bar is, for the label of an average

    @property
    def intraday(self) -> bool:
        return self.interval.endswith("m")


RANGES = {
    "1j": Range("1d", "5m", 60),
    "5j": Range("5d", "30m", 300),
    "1m": Range("2y", "1d", 900, 31, (50, 200)),
    "6m": Range("2y", "1d", 900, 183, (50, 200)),
    "1a": Range("2y", "1d", 900, 366, (50, 200)),
    "5a": Range("10y", "1wk", 3600, 1827, (10, 40), "semaines"),
    "max": Range("max", "1mo", 3600),
}
DAILY = Range("2y", "1d", 900)  # the series the key figures of an instrument are read from
DAY = 86_400

QUOTE_MAX_AGE = 60  # seconds before a quote is asked again
MAX_CANDIDATES = 6  # listings proposed when the search by ISIN finds nothing


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _day(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).date().isoformat()


def normalise(price: Decimal, currency: str) -> tuple[Decimal, str]:
    """London quotes in pence ('GBp'): bring them back to pounds."""
    if currency in ("GBp", "GBX"):
        return price / 100, "GBP"
    return price, currency


def delay_minutes(exchange: str | None, symbol: str | None) -> int | None:
    """Delay of the free quotes, from the exchange code or else the symbol suffix."""
    if exchange in DELAY_MINUTES:
        return DELAY_MINUTES[exchange]
    if symbol and "." in symbol:
        return SUFFIX_DELAY.get(symbol.rsplit(".", 1)[1].upper())
    return None


def search_terms(name: str) -> str:
    """The name without its bracketed share class: 'Alphabet (A)' -> 'Alphabet'."""
    cleaned = re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", name)).strip()
    return cleaned or name.strip()


def moving_average(values: list[Decimal], window: int) -> list[Decimal | None]:
    """Mean of the last `window` values at each position; None until there are enough."""
    result: list[Decimal | None] = []
    total = Decimal(0)
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        result.append(total / window if index >= window - 1 else None)
    return result


def trades(conn: sqlite3.Connection, isin: str) -> list[dict]:
    """Every purchase and sale of one instrument, oldest first, as executed."""
    rows = conn.execute(
        "SELECT datetime, date, account_id, type, shares, price, amount, fee FROM transactions "
        "WHERE isin = ? AND type IN ('BUY', 'SELL') ORDER BY datetime",
        (isin,),
    ).fetchall()
    return [
        {
            "datetime": row["datetime"],
            "date": row["date"],
            "account": row["account_id"],
            "side": "achat" if row["type"] == "BUY" else "vente",
            "shares": float(abs(dec(row["shares"]))),
            "price": float(dec(row["price"])) if row["price"] else None,
            "amount": float(abs(dec(row["amount"]))),
            "fee": float(-dec(row["fee"])),
        }
        for row in rows
    ]


def _trade_marks(conn: sqlite3.Connection, isin: str, bars: list[Point], intraday: bool) -> list:
    """Where each purchase and sale falls on the bars shown: the bar of its day
    (of its minute on an intraday chart). A trade older than the first bar is
    left out. The mark carries no price: the trade was paid in euros, on another
    market than the one charted."""
    if not bars:
        return []
    times = [bar.time for bar in bars]
    days = [_day(bar.time) for bar in bars]
    marks = []
    for trade in trades(conn, isin):
        if intraday:
            stamp = datetime.fromisoformat(trade["datetime"]).timestamp()
            index = bisect_right(times, stamp) - 1
        else:
            index = bisect_right(days, trade["date"]) - 1
        if index >= 0:
            marks.append({"time": bars[index].time, **trade})
    return marks


def _bar(bar: Point) -> dict:
    def number(value: Decimal | None) -> float | None:
        return None if value is None else float(value)

    return {
        "time": bar.time,
        "value": float(bar.close),
        "open": number(bar.open),
        "high": number(bar.high),
        "low": number(bar.low),
        "volume": number(bar.volume),
    }


def choose_listing(isin: str, listings: list[Listing]) -> Listing | None:
    if not listings:
        return None
    if isin[:2] in ("IE", "LU"):  # funds: pick a euro listing when there is one
        for exchange in FUND_EXCHANGES:
            for listing in listings:
                if listing.exchange == exchange:
                    return listing
    return listings[0]


@dataclass
class Outcome:
    """What a refresh did, in terms the screen can show."""

    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    refused: bool = False  # the source turned us down: stop asking for now
    unreachable: bool = False  # no network, or the source is down

    def as_dict(self) -> dict:
        return {
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "refused": self.refused,
            "unreachable": self.unreachable,
        }


class Market:
    def __init__(self, provider: QuoteProvider):
        self.provider = provider
        self._chart_cache: dict[tuple[str, str, str], tuple[float, Series]] = {}
        self._fx_today: dict[str, tuple[float, Decimal]] = {}
        self._spot: dict[str, tuple[float, Decimal]] = {}

    # -- Symbols ------------------------------------------------------------

    def resolve(self, conn: sqlite3.Connection, isin: str) -> str | None:
        """Find where the instrument is quoted and remember it. None if not found."""
        row = conn.execute(
            "SELECT quote_symbol, quote_status FROM instruments WHERE isin = ?", (isin,)
        ).fetchone()
        if row is None:
            return None
        if row["quote_symbol"]:
            return row["quote_symbol"]
        if row["quote_status"] == "introuvable":
            return None  # already looked for; a symbol can be typed in by hand
        listing = choose_listing(isin, self.provider.search(isin))
        if listing is None:
            conn.execute(
                "UPDATE instruments SET quote_status = 'introuvable' WHERE isin = ?", (isin,)
            )
            conn.commit()
            return None
        conn.execute(
            "UPDATE instruments SET quote_symbol = ?, quote_exchange = ?, quote_status = 'ok' "
            "WHERE isin = ?",
            (listing.symbol, listing.exchange, isin),
        )
        conn.commit()
        return listing.symbol

    def set_symbol(self, conn: sqlite3.Connection, isin: str, symbol: str | None) -> None:
        """Symbol typed in by hand; an empty one asks for a new search by ISIN."""
        symbol = (symbol or "").strip() or None
        conn.execute(
            "UPDATE instruments SET quote_symbol = ?, quote_exchange = NULL, "
            "quote_currency = NULL, quote_status = ? WHERE isin = ?",
            (symbol, "manuel" if symbol else None, isin),
        )
        conn.execute("DELETE FROM quotes WHERE isin = ?", (isin,))
        conn.commit()

    def candidates(self, conn: sqlite3.Connection, isin: str) -> dict:
        """Listings a person can choose from when the search by ISIN finds nothing.

        The source does not say which ISIN a listing carries, so a search by name
        can return another share class or another kind of security. Nothing is
        stored here: the choice is made on screen, with each listing's price and
        the last price traded as a point of comparison.
        """
        row = conn.execute("SELECT name FROM instruments WHERE isin = ?", (isin,)).fetchone()
        if row is None:
            raise ProviderError("not_found", "titre inconnu")
        query, by = isin, "isin"
        found = self.provider.search(isin)
        if not found:
            query, by = search_terms(row["name"]), "nom"
            found = self.provider.search(query)

        items, priced = [], True
        for listing in found[:MAX_CANDIDATES]:
            item = {
                "symbol": listing.symbol,
                "name": listing.name,
                "exchange": listing.exchange_name or listing.exchange,
                "kind": listing.kind,
                "price": None,
                "currency": None,
                "price_eur": None,
            }
            if priced:
                try:
                    series = self.provider.chart(listing.symbol, "1d", "5m")
                    if series.price is not None:
                        price, currency = normalise(series.price, series.currency)
                        item["price"], item["currency"] = float(price), currency
                        item["price_eur"] = float(price / self._rate_today(currency))
                except ProviderError as exc:
                    priced = exc.kind not in ("refused", "network")  # do not insist
            items.append(item)

        last = conn.execute(
            "SELECT date, price FROM transactions WHERE isin = ? AND type IN ('BUY', 'SELL') "
            "AND price != '' ORDER BY datetime DESC LIMIT 1",
            (isin,),
        ).fetchone()
        return {
            "isin": isin,
            "name": row["name"],
            "query": query,
            "by": by,
            "candidates": items,
            "last_trade": {"date": last["date"], "price": float(dec(last["price"]))}
            if last
            else None,
        }

    def price_eur(self, symbol: str) -> Decimal:
        """Latest price of any symbol in euros, asked at most once a minute."""
        cached = self._spot.get(symbol)
        if cached and time.monotonic() - cached[0] < QUOTE_MAX_AGE:
            return cached[1]
        series = self.provider.chart(symbol, "1d", "5m")
        if series.price is None or series.price <= 0:
            raise ProviderError("format", f"pas de cours dans la réponse pour {symbol}")
        price, currency = normalise(series.price, series.currency)
        value = price / self._rate_today(currency)
        self._spot[symbol] = (time.monotonic(), value)
        return value

    # -- Exchange rates -----------------------------------------------------

    def _rate_today(self, currency: str) -> Decimal:
        """Units of `currency` for one euro, now."""
        if currency == "EUR":
            return Decimal(1)
        cached = self._fx_today.get(currency)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        series = self.provider.chart(f"EUR{currency}=X", "1d", "5m")
        if not series.price or series.price <= 0:
            raise ProviderError("format", f"taux de change EUR/{currency} indisponible")
        self._fx_today[currency] = (time.monotonic(), series.price)
        return series.price

    def _load_rates(self, conn: sqlite3.Connection, currency: str, span: str) -> None:
        series = self.provider.chart(f"EUR{currency}=X", span, "1d")
        conn.executemany(
            "INSERT INTO fx_rates (currency, date, rate) VALUES (?, ?, ?) "
            "ON CONFLICT (currency, date) DO UPDATE SET rate = excluded.rate",
            [(currency, _day(p.time), str(p.close)) for p in series.points if p.close > 0],
        )

    @staticmethod
    def _rates(conn: sqlite3.Connection, currency: str) -> list[tuple[str, Decimal]]:
        rows = conn.execute(
            "SELECT date, rate FROM fx_rates WHERE currency = ? ORDER BY date", (currency,)
        ).fetchall()
        return [(row["date"], dec(row["rate"])) for row in rows]

    # -- Latest quotes ------------------------------------------------------

    def refresh_quotes(self, conn: sqlite3.Connection, isins: list[str]) -> Outcome:
        """Ask the latest price of each instrument, at most once a minute each."""
        outcome = Outcome()
        fresh = {
            row["isin"]
            for row in conn.execute("SELECT isin, fetched_at FROM quotes")
            if (datetime.now(UTC) - datetime.fromisoformat(row["fetched_at"])).total_seconds()
            < QUOTE_MAX_AGE
        }
        for isin in isins:
            if isin in fresh:
                outcome.skipped += 1
                continue
            try:
                symbol = self.resolve(conn, isin)
                if symbol is None:
                    outcome.skipped += 1
                    continue
                series = self.provider.chart(symbol, "1d", "5m")
                self._store_quote(conn, isin, series)
                conn.commit()  # short transactions: the dashboard keeps reading meanwhile
                outcome.updated += 1
            except ProviderError as exc:
                outcome.errors.append(f"{isin} : {exc}")
                if exc.kind in ("refused", "network"):
                    outcome.refused = exc.kind == "refused"
                    outcome.unreachable = exc.kind == "network"
                    break  # refused or unreachable: do not insist
        conn.commit()
        return outcome

    def _store_quote(self, conn: sqlite3.Connection, isin: str, series: Series) -> None:
        if series.price is None:
            raise ProviderError("format", f"pas de cours dans la réponse pour {series.symbol}")
        price, currency = normalise(series.price, series.currency)
        previous = None
        if series.previous_close is not None:
            previous, _ = normalise(series.previous_close, series.currency)
        price_eur = price / self._rate_today(currency)
        stamp = series.market_time or int(time.time())
        conn.execute(
            "INSERT INTO quotes (isin, price, currency, price_eur, previous_close, market_time,"
            " exchange, delay_minutes, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (isin) DO UPDATE SET price = excluded.price, "
            "currency = excluded.currency, price_eur = excluded.price_eur, "
            "previous_close = excluded.previous_close, market_time = excluded.market_time, "
            "exchange = excluded.exchange, delay_minutes = excluded.delay_minutes, "
            "fetched_at = excluded.fetched_at",
            (
                isin,
                str(price),
                currency,
                str(price_eur),
                None if previous is None else str(previous),
                datetime.fromtimestamp(stamp, UTC).isoformat(timespec="seconds"),
                series.exchange_name or series.exchange,
                delay_minutes(series.exchange, series.symbol),
                _now(),
            ),
        )
        conn.execute(
            "UPDATE instruments SET quote_currency = ?, quote_exchange = ? WHERE isin = ?",
            (currency, series.exchange, isin),
        )
        _upsert_price(conn, isin, _day(stamp), price_eur, price, currency, self.provider.name)

    # -- History ------------------------------------------------------------

    def load_history(self, conn: sqlite3.Connection, isins: list[str], since: str) -> Outcome:
        """Daily closes of each instrument since `since` (ISO date), in euros."""
        outcome = Outcome()
        span = _span_since(since)
        rates_loaded: set[str] = set()
        for isin in isins:
            try:
                symbol = self.resolve(conn, isin)
                if symbol is None:
                    outcome.skipped += 1
                    continue
                series = self.provider.chart(symbol, span, "1d")
                _, currency = normalise(Decimal(1), series.currency)
                if currency != "EUR" and currency not in rates_loaded:
                    self._load_rates(conn, currency, span)  # once per currency and per run
                    rates_loaded.add(currency)
                rates = self._rates(conn, currency) if currency != "EUR" else []
                index = 0
                rate = rates[0][1] if rates else Decimal(1)
                for point in series.points:
                    day = _day(point.time)
                    price, _ = normalise(point.close, series.currency)
                    # Rate of the day, or the last one known before it.
                    while index < len(rates) and rates[index][0] <= day:
                        rate = rates[index][1]
                        index += 1
                    _upsert_price(
                        conn, isin, day, price / rate, price, currency, self.provider.name
                    )
                conn.executemany(
                    "INSERT INTO splits (isin, date, ratio) VALUES (?, ?, ?) "
                    "ON CONFLICT (isin, date) DO UPDATE SET ratio = excluded.ratio",
                    [(isin, _day(split.time), str(split.ratio)) for split in series.splits],
                )
                conn.execute(
                    "UPDATE instruments SET quote_currency = ?, quote_exchange = ? WHERE isin = ?",
                    (currency, series.exchange, isin),
                )
                conn.commit()
                outcome.updated += 1
            except ProviderError as exc:
                outcome.errors.append(f"{isin} : {exc}")
                if exc.kind in ("refused", "network"):
                    outcome.refused = exc.kind == "refused"
                    outcome.unreachable = exc.kind == "network"
                    break
        return outcome

    # -- Charts -------------------------------------------------------------

    def _series(self, symbol: str, spec: Range) -> Series:
        """One answer of the source, kept a while: several periods share the same one."""
        key = (symbol, spec.span, spec.interval)
        cached = self._chart_cache.get(key)
        if cached and time.monotonic() - cached[0] < spec.lifetime:
            return cached[1]
        series = self.provider.chart(symbol, spec.span, spec.interval)
        self._chart_cache[key] = (time.monotonic(), series)
        return series

    def _bars(self, symbol: str, spec: Range, in_euros: bool) -> tuple[Series, str, list[Point]]:
        """Bars of a symbol, in its quotation currency or in euros.

        In euros, each bar is divided by the exchange rate of its own day (of its
        own interval): a reconstruction, since the instrument is not quoted in
        euros on that market.
        """
        series = self._series(symbol, spec)
        unit, currency = normalise(Decimal(1), series.currency)  # pence -> pounds
        rates: list[tuple[int, Decimal]] = []
        if in_euros and currency != "EUR":
            try:
                pair = self._series(f"EUR{currency}=X", spec)
                rates = [(point.time, point.close) for point in pair.points if point.close > 0]
            except ProviderError as exc:
                if exc.kind in ("refused", "network"):
                    raise
            if not rates:
                rates = [(0, self._rate_today(currency))]
            currency = "EUR"

        bars, index = [], 0
        rate = rates[0][1] if rates else Decimal(1)
        for point in series.points:
            while index < len(rates) and rates[index][0] <= point.time:
                rate = rates[index][1]
                index += 1
            factor = unit / rate

            def scaled(value: Decimal | None, factor: Decimal = factor) -> Decimal | None:
                return None if value is None else value * factor

            bars.append(
                Point(
                    time=point.time,
                    close=point.close * factor,
                    open=scaled(point.open),
                    high=scaled(point.high),
                    low=scaled(point.low),
                    volume=point.volume,
                )
            )
        return series, currency, bars

    def chart(
        self, conn: sqlite3.Connection, isin: str, range_key: str, in_euros: bool = False
    ) -> dict:
        """Bars of one instrument over a period, with its moving averages and the
        user's own purchases and sales placed on them."""
        if range_key not in RANGES:
            raise ValueError("Période inconnue.")
        spec = RANGES[range_key]
        symbol = self.resolve(conn, isin)
        if symbol is None:
            raise ProviderError("not_found", "aucune cotation trouvée pour ce titre")
        series, currency, bars = self._bars(symbol, spec, in_euros)
        _, native = normalise(Decimal(1), series.currency)

        first = 0
        if spec.days is not None and bars:
            cutoff = bars[-1].time - spec.days * DAY
            first = next(index for index, bar in enumerate(bars) if bar.time >= cutoff)
        closes = [bar.close for bar in bars]
        averages = []
        for window in spec.averages:
            points = [
                {"time": bars[index].time, "value": float(value)}
                for index, value in enumerate(moving_average(closes, window))
                if index >= first and value is not None
            ]
            if points:
                label = f"Moyenne {window} {spec.unit}"
                averages.append({"window": window, "label": label, "points": points})
        shown = bars[first:]
        return {
            "isin": isin,
            "symbol": series.symbol,
            "range": range_key,
            "currency": currency,
            "native_currency": native,
            "exchange": series.exchange_name or series.exchange,
            "delay_minutes": delay_minutes(series.exchange, series.symbol),
            "intraday": spec.intraday,
            "points": [_bar(bar) for bar in shown],
            "averages": averages,
            "trades": _trade_marks(conn, isin, shown, spec.intraday),
        }

    def closes_eur(self, symbol: str, since: str) -> list[tuple[str, Decimal]]:
        """Daily closes of any symbol in euros since `since`: a benchmark's history."""
        spec = Range(_span_since(since), "1d", 3600)
        _, _, bars = self._bars(symbol, spec, in_euros=True)
        return [(_day(bar.time), bar.close) for bar in bars]

    def stats(self, conn: sqlite3.Connection, isin: str, in_euros: bool = False) -> dict:
        """Key figures of one instrument, read from its daily bars of the last two
        years: the day, the last 52 weeks, and the change over a few periods."""
        symbol = self.resolve(conn, isin)
        if symbol is None:
            raise ProviderError("not_found", "aucune cotation trouvée pour ce titre")
        _, currency, bars = self._bars(symbol, DAILY, in_euros)
        if not bars:
            raise ProviderError("not_found", "pas d'historique de cours pour ce titre")
        last = bars[-1]
        year = [bar for bar in bars if bar.time >= last.time - 366 * DAY]
        volumes = [bar.volume for bar in bars[-64:-1] if bar.volume]

        def number(value: Decimal | None) -> float | None:
            return None if value is None else float(value)

        def change_since(limit: int) -> float | None:
            """Change from the last close at or before `limit` (seconds since the epoch)."""
            before = [bar for bar in bars if bar.time <= limit]
            if not before or before[-1].close <= 0:
                return None
            return float((last.close / before[-1].close - 1).quantize(Decimal("0.0001")))

        today = datetime.fromtimestamp(last.time, UTC)
        new_year = int(datetime(today.year, 1, 1, tzinfo=UTC).timestamp())
        return {
            "currency": currency,
            "as_of": _day(last.time),
            "price": float(last.close),
            "previous_close": float(bars[-2].close) if len(bars) > 1 else None,
            "open": number(last.open),
            "day_low": number(last.low),
            "day_high": number(last.high),
            "year_low": float(min(bar.low or bar.close for bar in year)),
            "year_high": float(max(bar.high or bar.close for bar in year)),
            "volume": number(last.volume),
            "average_volume": float(sum(volumes) / len(volumes)) if volumes else None,
            "changes": [
                {"label": "1 mois", "change": change_since(last.time - 31 * DAY)},
                {"label": "6 mois", "change": change_since(last.time - 183 * DAY)},
                {"label": "1 an", "change": change_since(last.time - 366 * DAY)},
                {"label": "Depuis le 1er janvier", "change": change_since(new_year)},
            ],
        }


def _span_since(since: str) -> str:
    years = (date.today() - date.fromisoformat(since)).days / 365.25
    for limit, span in ((0.9, "1y"), (1.9, "2y"), (4.9, "5y"), (9.9, "10y")):
        if years <= limit:
            return span
    return "max"


def _upsert_price(
    conn: sqlite3.Connection,
    isin: str,
    day: str,
    price_eur: Decimal,
    native: Decimal,
    currency: str,
    source: str,
) -> None:
    # A price typed in by hand for that day is never overwritten.
    conn.execute(
        "INSERT INTO prices (isin, date, price, currency, source, native_price, native_currency) "
        "VALUES (?, ?, ?, 'EUR', ?, ?, ?) "
        "ON CONFLICT (isin, date) DO UPDATE SET price = excluded.price, source = excluded.source, "
        "native_price = excluded.native_price, native_currency = excluded.native_currency "
        "WHERE prices.source != 'manuel'",
        (isin, day, str(price_eur), source, str(native), currency),
    )


# -- Reads used by the report -----------------------------------------------


def open_isins(conn: sqlite3.Connection) -> list[str]:
    """Instruments currently held, in any account."""
    from .. import portfolio, store  # local import: avoids a cycle with store

    lines = portfolio.build_lines(store.all_transactions(conn))
    return sorted({line.isin for line in lines.values() if abs(line.shares) >= SHARE_EPSILON})


def all_isins(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT isin FROM instruments ORDER BY isin")]


def instruments(conn: sqlite3.Connection) -> list[dict]:
    held = set(open_isins(conn))
    rows = conn.execute(
        "SELECT i.isin, i.name, i.asset_class, i.quote_symbol, i.quote_exchange, "
        "i.quote_currency, i.quote_status, q.fetched_at, "
        "(SELECT COUNT(*) FROM prices p WHERE p.isin = i.isin) AS price_days "
        "FROM instruments i LEFT JOIN quotes q ON q.isin = i.isin ORDER BY i.name"
    ).fetchall()
    return [
        {
            "isin": row["isin"],
            "name": row["name"],
            "held": row["isin"] in held,
            "symbol": row["quote_symbol"],
            "exchange": row["quote_exchange"],
            "currency": row["quote_currency"],
            "status": row["quote_status"],
            "delay_minutes": delay_minutes(row["quote_exchange"], row["quote_symbol"]),
            "last_quote": row["fetched_at"],
            "price_days": row["price_days"],
        }
        for row in rows
    ]
