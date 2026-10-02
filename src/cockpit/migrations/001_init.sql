-- V0 schema. Amounts and quantities are stored as TEXT holding exact decimal
-- strings: Trade Republic quantities carry up to 10 decimals and money must
-- not go through binary floats.

CREATE TABLE accounts (
    id              TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    tr_account_type TEXT NOT NULL UNIQUE
);

INSERT INTO accounts (id, label, tr_account_type) VALUES
    ('CTO', 'Compte-titres ordinaire', 'DEFAULT'),
    ('PEA', 'Plan d''épargne en actions', 'PEA');

CREATE TABLE instruments (
    isin        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    asset_class TEXT
);

-- One row per line of the Trade Republic transaction export, columns kept as
-- exported. transaction_id is the key, so importing the same file twice (or a
-- newer export that overlaps the previous one) never creates duplicates.
CREATE TABLE transactions (
    transaction_id     TEXT PRIMARY KEY,
    datetime           TEXT NOT NULL,
    date               TEXT NOT NULL,
    account_id         TEXT NOT NULL REFERENCES accounts (id),
    category           TEXT NOT NULL,
    type               TEXT NOT NULL,
    asset_class        TEXT,
    name               TEXT,
    isin               TEXT,
    shares             TEXT,
    price              TEXT,
    amount             TEXT,
    fee                TEXT,
    tax                TEXT,
    currency           TEXT,
    original_amount    TEXT,
    original_currency  TEXT,
    fx_rate            TEXT,
    description        TEXT,
    counterparty_name  TEXT,
    counterparty_iban  TEXT,
    payment_reference  TEXT,
    mcc_code           TEXT,
    source             TEXT NOT NULL,
    imported_at        TEXT NOT NULL
);

CREATE INDEX idx_transactions_line ON transactions (account_id, isin);
CREATE INDEX idx_transactions_date ON transactions (date);

-- Latest known price per instrument and day. In V0 prices are typed in by
-- hand; the Trade Republic sync will write here later.
CREATE TABLE prices (
    isin     TEXT NOT NULL,
    date     TEXT NOT NULL,
    price    TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    source   TEXT NOT NULL,
    PRIMARY KEY (isin, date)
);

CREATE TABLE snapshots (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at TEXT NOT NULL,
    label    TEXT,
    totals   TEXT NOT NULL
);

CREATE TABLE snapshot_positions (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots (id) ON DELETE CASCADE,
    account_id  TEXT NOT NULL,
    isin        TEXT NOT NULL,
    name        TEXT NOT NULL,
    shares      TEXT NOT NULL,
    cost        TEXT NOT NULL,
    price       TEXT,
    value       TEXT,
    PRIMARY KEY (snapshot_id, account_id, isin)
);
