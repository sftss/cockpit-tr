-- Stock splits published by the price source, per instrument.
-- ratio: new shares for one old share (10 for a 10-for-1 split).
-- Used to restate quantities of lines closed before a later split, since the
-- published price history is adjusted for it and the export has no trace of it.

CREATE TABLE splits (
    isin  TEXT NOT NULL REFERENCES instruments (isin),
    date  TEXT NOT NULL,
    ratio TEXT NOT NULL,
    PRIMARY KEY (isin, date)
);
