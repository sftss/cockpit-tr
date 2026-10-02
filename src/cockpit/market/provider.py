"""What the application needs from a market-data source.

The rest of the code only talks to this interface, so the source can be
replaced (another provider, an official API with a key) without touching the
calculations or the screens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


class ProviderError(Exception):
    """A request to the source failed.

    kind: 'refused' (the source turned the request down: rate limit or block),
          'not_found' (unknown symbol), 'network', 'format' (unexpected answer).
    """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Listing:
    """One place where an instrument is quoted."""

    symbol: str
    name: str
    exchange: str
    kind: str
    exchange_name: str = ""  # the exchange as shown to a person, when the source gives it


@dataclass(frozen=True)
class Point:
    time: int  # seconds since the epoch, UTC
    close: Decimal
    # The rest of the bar, when the source gives it (exchange rates have none).
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal | None = None


@dataclass(frozen=True)
class Split:
    time: int  # seconds since the epoch, UTC: first day quoted after the split
    ratio: Decimal  # new shares for one old share


@dataclass
class Series:
    symbol: str
    currency: str
    exchange: str
    exchange_name: str = ""
    price: Decimal | None = None
    previous_close: Decimal | None = None
    market_time: int | None = None
    points: list[Point] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)  # within the span asked


class QuoteProvider(Protocol):
    name: str

    def search(self, query: str) -> list[Listing]:
        """Listings matching an ISIN or a company name, best match first."""

    def chart(self, symbol: str, span: str, interval: str) -> Series:
        """Closing prices of `symbol` over `span` (e.g. '1d', '1y'), one per `interval`."""
