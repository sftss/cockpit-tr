"""A market-data source for tests: answers from memory, never from the network."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cockpit.market.provider import Listing, Point, ProviderError, Series


def epoch(day: str, hour: int = 12) -> int:
    return int(datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=UTC).timestamp())


def series(symbol, currency, exchange, closes: dict[str, str], previous=None) -> Series:
    points = [Point(epoch(day), Decimal(value)) for day, value in closes.items()]
    return Series(
        symbol=symbol,
        currency=currency,
        exchange=exchange,
        exchange_name=exchange,
        price=points[-1].close if points else None,
        previous_close=None if previous is None else Decimal(previous),
        market_time=points[-1].time if points else None,
        points=points,
    )


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.listings: dict[str, list[Listing]] = {}
        self.charts: dict[str, Series] = {}
        self.calls: list[tuple] = []
        self.fail: ProviderError | None = None

    def search(self, query: str) -> list[Listing]:
        self.calls.append(("search", query))
        if self.fail:
            raise self.fail
        return self.listings.get(query, [])

    def chart(self, symbol: str, span: str, interval: str) -> Series:
        self.calls.append(("chart", symbol, span, interval))
        if self.fail:
            raise self.fail
        if symbol not in self.charts:
            raise ProviderError("not_found", f"symbole inconnu : {symbol}")
        return self.charts[symbol]
