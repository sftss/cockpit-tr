-- V1: rules, compliance status, roadmap, physical gold.
-- Everything here is personal data entered on this machine. The code only
-- knows the kinds of rules; their values live in this database.

CREATE TABLE rules (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    account_id TEXT,              -- NULL: every account
    value      TEXT NOT NULL,
    valid_from TEXT NOT NULL,     -- ISO date
    valid_to   TEXT,              -- NULL: still in force
    note       TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX rules_kind ON rules (kind, valid_from);

-- Written reason for a transaction that departs from a rule.
CREATE TABLE deviation_notes (
    transaction_id TEXT PRIMARY KEY,
    reason         TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

-- Compliance status, checked by hand in the screening application.
-- One row per check: the history is kept.
CREATE TABLE compliance (
    isin       TEXT NOT NULL,
    checked_on TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('conforme', 'non_conforme', 'douteux')),
    note       TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (isin, checked_on)
);

CREATE TABLE roadmap_items (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    isin            TEXT,
    account_id      TEXT,
    amount          TEXT,          -- planned amount, euros
    entry_condition TEXT,
    entry_price     TEXT,          -- euros: flagged once the price is at or below it
    thesis          TEXT,
    status          TEXT NOT NULL DEFAULT 'idee'
                    CHECK (status IN ('idee', 'prevu', 'execute', 'abandonne')),
    quote_symbol    TEXT,
    last_price      TEXT,          -- euros
    last_price_at   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Physical gold, outside the broker: weight of fine gold and what was paid.
CREATE TABLE gold_lots (
    id          INTEGER PRIMARY KEY,
    label       TEXT NOT NULL,
    grams       TEXT NOT NULL,
    cost        TEXT,
    acquired_on TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE gold_prices (
    date         TEXT PRIMARY KEY,
    eur_per_gram TEXT NOT NULL,
    fetched_at   TEXT NOT NULL
);
