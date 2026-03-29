"""
SQLite Schema Definitions — DDL for all memory tables.

All three memory tiers share a single SQLite database file
(rudy-data/memory.sqlite) to avoid filesystem fragmentation
and simplify backup/restore.
"""

# ── Episodic Memory ───────────────────────────────────────────────
# Timestamped event log. Every tool call, agent action, user command,
# and inter-agent message is recorded here.
EPISODIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    agent       TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    payload     TEXT    NOT NULL DEFAULT '{}',
    session_id  TEXT    DEFAULT NULL,
    tags        TEXT    DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
"""

# ── Semantic Memory ───────────────────────────────────────────────
# Vector embeddings for similarity search. Chunks of text with
# source attribution and collection tagging.
SEMANTIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'manual',
    collection  TEXT    NOT NULL DEFAULT 'general',
    file_path   TEXT    DEFAULT NULL,
    file_hash   TEXT    DEFAULT NULL,
    chunk_index INTEGER DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    metadata    TEXT    DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id    INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    vector      BLOB    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_collection ON chunks(collection);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
CREATE INDEX IF NOT EXISTS idx_chunks_file_hash ON chunks(file_hash);
"""

# ── Procedural Memory ────────────────────────────────────────────
# Persona rules, learned behaviors, and operational boundaries.
# These are loaded from YAML files but cached in SQLite for fast
# retrieval and versioning.
PROCEDURAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS persona_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    persona     TEXT    NOT NULL,
    rule_type   TEXT    NOT NULL,
    rule_key    TEXT    NOT NULL,
    rule_value  TEXT    NOT NULL,
    priority    INTEGER DEFAULT 0,
    source_file TEXT    DEFAULT NULL,
    file_hash   TEXT    DEFAULT NULL,
    loaded_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    UNIQUE(persona, rule_type, rule_key)
);

CREATE TABLE IF NOT EXISTS learned_behaviors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT    NOT NULL,
    behavior    TEXT    NOT NULL,
    context     TEXT    DEFAULT '{}',
    success     INTEGER DEFAULT 1,
    learned_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_rules_persona ON persona_rules(persona);
CREATE INDEX IF NOT EXISTS idx_rules_type ON persona_rules(rule_type);
CREATE INDEX IF NOT EXISTS idx_behaviors_agent ON learned_behaviors(agent);
"""

# ── Summary Table ─────────────────────────────────────────────────
# Compressed daily summaries of episodic events. Events older than
# 30 days are compressed into these summaries.
SUMMARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL UNIQUE,
    agent       TEXT    DEFAULT 'all',
    summary     TEXT    NOT NULL,
    event_count INTEGER DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_summaries_date ON daily_summaries(date);
"""

ALL_SCHEMAS = [EPISODIC_SCHEMA, SEMANTIC_SCHEMA, PROCEDURAL_SCHEMA, SUMMARY_SCHEMA]
