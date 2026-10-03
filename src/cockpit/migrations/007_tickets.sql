-- V3: order tickets. A ticket prepares and checks an order; the order itself is
-- placed by the user in the broker's own application. Nothing here sends anything.
-- Personal data, like the rest: it stays in this database.

CREATE TABLE tickets (
    id              INTEGER PRIMARY KEY,
    isin            TEXT NOT NULL,
    name            TEXT NOT NULL,
    account_id      TEXT NOT NULL REFERENCES accounts (id),
    side            TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    shares          TEXT,                       -- planned quantity; empty while drafting
    order_type      TEXT NOT NULL DEFAULT 'marche' CHECK (order_type IN ('marche', 'limite')),
    limit_price     TEXT,                       -- euros
    price           TEXT,                       -- indicative price, euros
    price_at        TEXT,
    fee             TEXT NOT NULL DEFAULT '1',  -- expected order fee, euros
    reason          TEXT,                       -- written by the user when a rule is exceeded
    roadmap_item_id INTEGER REFERENCES roadmap_items (id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'brouillon'
                    CHECK (status IN ('brouillon', 'pret', 'execute', 'abandonne')),
    proposed_by     TEXT,                       -- 'assistant' for a draft it created
    checks          TEXT,                       -- JSON: the controls as they stood when made ready
    ready_at        TEXT,
    transaction_id  TEXT UNIQUE REFERENCES transactions (transaction_id),
    reason_copied   INTEGER NOT NULL DEFAULT 0, -- 1: the reason was written beside the transaction
    rejected        TEXT,                       -- JSON: transactions the user said were not this order
    closed_at       TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX tickets_status ON tickets (status);
