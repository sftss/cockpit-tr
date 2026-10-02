-- V2: the assistant. Conversations, a decision journal, the user's own
-- standing instructions, and small settings. All personal, all local.

CREATE TABLE conversations (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- One row per message exchanged with the model. `content` holds the content
-- blocks exactly as sent or received (JSON): they must go back unchanged.
CREATE TABLE messages (
    id                 INTEGER PRIMARY KEY,
    conversation_id    INTEGER NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role               TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content            TEXT NOT NULL,
    model              TEXT,
    input_tokens       INTEGER,
    output_tokens      INTEGER,
    cache_read_tokens  INTEGER,
    cache_write_tokens INTEGER,
    web_searches       INTEGER,
    cost_usd           TEXT,
    created_at         TEXT NOT NULL
);
CREATE INDEX messages_conversation ON messages (conversation_id, id);

CREATE TABLE decisions (
    id         INTEGER PRIMARY KEY,
    decided_on TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT,
    author     TEXT NOT NULL DEFAULT 'moi' CHECK (author IN ('moi', 'assistant')),
    created_at TEXT NOT NULL
);

-- Standing instructions and reference documents given to the assistant.
CREATE TABLE assistant_context (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL UNIQUE,
    content    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 'assistant' when the target was proposed by the assistant.
ALTER TABLE roadmap_items ADD COLUMN proposed_by TEXT;
