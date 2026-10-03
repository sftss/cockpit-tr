-- The quarterly review. One row per quarter: the figures as they stood when the
-- review was generated (JSON), the assistant's commentary when it was asked
-- for, and the user's own conclusions. All personal, all local.

CREATE TABLE reviews (
    quarter         TEXT PRIMARY KEY,          -- '2026-T3'
    generated_at    TEXT NOT NULL,
    data            TEXT NOT NULL,
    commentary      TEXT,
    commentary_at   TEXT,
    conversation_id INTEGER REFERENCES conversations (id) ON DELETE SET NULL,
    conclusions     TEXT
);
