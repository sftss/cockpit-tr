"""Market data for the portfolio: symbols, latest quotes, history, exchange rates.

Everything is stored in euros, because costs are in euros. The price in the
quotation currency is kept beside it.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from ..money import SHARE_EPSILON, dec
from .provider import Listing, ProviderError, QuoteProvider, Series

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

# Screen range -> (span, interval) asked from the source, and cache lifetime in seconds.
RANGES = {
    "1j": ("1d", "5m", 60),
    "5j": ("5d", "30m", 300),
    "1m": ("1mo", "1d", 900),
    "6m": ("6mo", "1d", 900),
    "1a": ("1y", "1d", 900),
    "5a": ("5y", "1wk", 3600),
    "max": ("max", "1mo", 3600),
}

QUOTE_MAX_AGE = 60  # seconds before a quote is asked again


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
        self._chart_cache: dict[tuple[str, str], tuple[float, Series]] = {}
        self._fx_today: dict[str, tuple[float, Decimal]] = {}

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

    def chart(self, conn: sqlite3.Connection, isin: str, range_key: str) -> dict:
        """Series for one instrument, in its quotation currency, with a short cache."""
        if range_key not in RANGES:
            raise ValueError("Période inconnue.")
        span, interval, lifetime = RANGES[range_key]
        symbol = self.resolve(conn, isin)
        if symbol is None:
            raise ProviderError("not_found", "aucune cotation trouvée pour ce titre")
        key = (symbol, range_key)
        cached = self._chart_cache.get(key)
        if cached and time.monotonic() - cached[0] < lifetime:
            series = cached[1]
        else:
            series = self.provider.chart(symbol, span, interval)
            self._chart_cache[key] = (time.monotonic(), series)
        _, currency = normalise(Decimal(1), series.currency)
        return {
            "isin": isin,
            "symbol": series.symbol,
            "range": range_key,
            "currency": currency,
            "exchange": series.exchange_name or series.exchange,
            "delay_minutes": delay_minutes(series.exchange, series.symbol),
            "intraday": interval.endswith("m"),
            "points": [
                {"time": p.time, "value": float(normalise(p.close, series.currency)[0])}
                for p in series.points
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
