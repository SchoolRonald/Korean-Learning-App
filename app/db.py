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
    conn.commit()
