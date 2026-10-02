-- Market data: where each instrument is quoted, its latest quote, exchange rates.
-- Prices stay in the `prices` table, always in euros; the native price and its
-- currency are kept beside it.

ALTER TABLE instruments ADD COLUMN quote_symbol TEXT;
ALTER TABLE instruments ADD COLUMN quote_exchange TEXT;
ALTER TABLE instruments ADD COLUMN quote_currency TEXT;
-- 'ok' (found by ISIN), 'manuel' (symbol typed in by hand), 'introuvable'
ALTER TABLE instruments ADD COLUMN quote_status TEXT;

ALTER TABLE prices ADD COLUMN native_price TEXT;
ALTER TABLE prices ADD COLUMN native_currency TEXT;

-- Latest quote per instrument, as received.
CREATE TABLE quotes (
    isin           TEXT PRIMARY KEY REFERENCES instruments (isin),
    price          TEXT NOT NULL,
    currency       TEXT NOT NULL,
    price_eur      TEXT NOT NULL,
    previous_close TEXT,
    market_time    TEXT,
    exchange       TEXT,
    delay_minutes  INTEGER,
    fetched_at     TEXT NOT NULL
);

-- Units of the currency for one euro, per day.
CREATE TABLE fx_rates (
    currency TEXT NOT NULL,
    date     TEXT NOT NULL,
    rate     TEXT NOT NULL,
    PRIMARY KEY (currency, date)
);
