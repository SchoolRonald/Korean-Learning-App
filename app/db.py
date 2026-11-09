import os
import sqlite3

DB_PATH = os.environ.get("GONGBU_DB", "gongbu.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY,
    hangul TEXT NOT NULL,
    english TEXT NOT NULL,
    lesson INTEGER NOT NULL,
    UNIQUE (hangul, english)
);
CREATE TABLE IF NOT EXISTS stats (
    word_id INTEGER PRIMARY KEY REFERENCES words(id),
    attempts INTEGER NOT NULL DEFAULT 0,
    fails INTEGER NOT NULL DEFAULT 0,
    last_seen TEXT
);
CREATE TABLE IF NOT EXISTS sentences (
    id INTEGER PRIMARY KEY,
    english TEXT NOT NULL,
    korean_ref TEXT NOT NULL,
    word_ids TEXT NOT NULL,
    tokens TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learned (
    word_id INTEGER PRIMARY KEY REFERENCES words(id),
    learned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    max_lesson INTEGER NOT NULL,
    interpretation TEXT NOT NULL,
    word_ids TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (name, max_lesson)
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('word', 'sentence')),
    ref_id INTEGER NOT NULL,
    answer TEXT NOT NULL,
    correct INTEGER NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sentence_word_verdicts (
    id INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    word_id INTEGER NOT NULL REFERENCES words(id),
    correct INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS grammar_learned (
    point_id TEXT PRIMARY KEY,
    learned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grammar_explanations (
    id INTEGER PRIMARY KEY,
    point_id TEXT NOT NULL,
    style TEXT NOT NULL,
    request TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS grammar_explanations_point ON grammar_explanations (point_id, style);
CREATE TABLE IF NOT EXISTS grammar_items (
    id INTEGER PRIMARY KEY,
    point_id TEXT NOT NULL,
    type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    answers TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS grammar_items_point ON grammar_items (point_id, type);
CREATE TABLE IF NOT EXISTS grammar_attempts (
    id INTEGER PRIMARY KEY,
    point_id TEXT NOT NULL,
    item_id INTEGER REFERENCES grammar_items(id),
    source TEXT NOT NULL,
    answer TEXT NOT NULL,
    verdict TEXT NOT NULL,
    correct INTEGER NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS grammar_attempts_item ON grammar_attempts (item_id);
CREATE TABLE IF NOT EXISTS verb_classes (
    hangul TEXT NOT NULL,
    english TEXT NOT NULL,
    adjective INTEGER,
    class TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (hangul, english)
);
CREATE TABLE IF NOT EXISTS learner_records (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    point_id TEXT NOT NULL,
    detail TEXT NOT NULL,
    correct INTEGER,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learner_notes (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    removed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grammar_questions (
    id INTEGER PRIMARY KEY,
    point_id TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    # Columns added after the first version; CREATE TABLE IF NOT EXISTS skips existing tables.
    columns = {r[1] for r in conn.execute("PRAGMA table_info(sentences)")}
    if "tokens" not in columns:
        conn.execute("ALTER TABLE sentences ADD COLUMN tokens TEXT")
    if "grammar" not in columns:
        conn.execute("ALTER TABLE sentences ADD COLUMN grammar TEXT")
    item_columns = {r[1] for r in conn.execute("PRAGMA table_info(grammar_items)")}
    if "checked" not in item_columns:
        conn.execute("ALTER TABLE grammar_items ADD COLUMN checked TEXT")
    conn.commit()
