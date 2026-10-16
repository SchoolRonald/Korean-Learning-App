import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.db import connect, init_db
from app.drill import grade_word, record_word_attempt


@pytest.fixture
def db_file(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_file):
    # A file, not :memory:, so the app's per-thread connections see the same data.
    c = connect(db_file)
    init_db(c)
    c.executemany(
        "INSERT INTO words (hangul, english, lesson) VALUES (?, ?, ?)",
        [("물", "water", 1), ("나", "I", 1), ("저", "I", 2), ("책", "book", 3)],
    )
    c.execute("INSERT INTO learned (word_id, learned_at) SELECT id, '2026-10-01' FROM words")
    c.commit()
    return c


def word_id(conn, hangul):
    return conn.execute("SELECT id FROM words WHERE hangul = ?", (hangul,)).fetchone()[0]


def test_grade_unknown_word(conn):
    assert grade_word(conn, 999, "물") is None


def test_grade_accepts_same_english_synonym(conn):
    r = grade_word(conn, word_id(conn, "나"), "저")
    assert r["correct"] and "나" in r["note"]


def test_grade_wrong(conn):
    assert not grade_word(conn, word_id(conn, "물"), "불")["correct"]


def test_record_creates_and_updates_stats(conn):
    wid = word_id(conn, "물")
    record_word_attempt(conn, wid, "불", False, ts="2026-10-01T00:00:00+00:00")
    record_word_attempt(conn, wid, "물", True, ts="2026-10-02T00:00:00+00:00")
    stats = conn.execute("SELECT attempts, fails, last_seen FROM stats WHERE word_id = ?", (wid,)).fetchone()
    assert tuple(stats) == (2, 1, "2026-10-02T00:00:00+00:00")
    rows = conn.execute("SELECT kind, answer, correct FROM attempts ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("word", "불", 0), ("word", "물", 1)]


@pytest.fixture
def client(conn, db_file, monkeypatch):
    monkeypatch.setattr(main, "db_path", db_file)
    with TestClient(main.app) as c:
        yield c


def test_api_next_respects_lesson(client):
    for _ in range(20):
        body = client.get("/api/next", params={"lesson": 1}).json()
        assert body["lesson"] == 1 and "hangul" not in body


def test_api_next_no_words(client):
    assert client.get("/api/next", params={"lesson": 0}).status_code == 404


def test_api_answer_records(client, conn):
    wid = word_id(conn, "책")
    body = client.post("/api/answer", json={"word_id": wid, "answer": "채"}).json()
    assert not body["correct"] and body["syllables"][0]["parts"] == ["final consonant"]
    assert tuple(conn.execute("SELECT attempts, fails FROM stats WHERE word_id = ?", (wid,)).fetchone()) == (1, 1)


def test_api_answer_unknown_word(client):
    assert client.post("/api/answer", json={"word_id": 999, "answer": "x"}).status_code == 404


def test_pages_served(client):
    assert "Spelling drill" in client.get("/words").text
    assert "Learn" in client.get("/").text


def test_api_lessons(client):
    assert client.get("/api/lessons").json() == [1, 2, 3]


def test_api_next_exclude(client, conn):
    wid = word_id(conn, "물")
    for _ in range(20):
        assert client.get("/api/next", params={"lesson": 1, "exclude": wid}).json()["id"] != wid


@pytest.fixture
def demonstratives(conn):
    # The real list's entries.
    conn.executemany("INSERT INTO words (hangul, english, lesson) VALUES (?, ?, 1)", [
        ("그", "that"), ("그", "he, him"), ("저", "that (when something is far away)"), ("저", "I, me (formal)"),
        ("거기", "there"), ("저기", "there (when farther away)"),
    ])
    return lambda hangul, english: conn.execute(
        "SELECT id FROM words WHERE hangul = ? AND english = ?", (hangul, english)).fetchone()[0]


@pytest.mark.parametrize("card, answer, correct", [
    (("그", "that"), "저", True),  # plain "that": either
    (("거기", "there"), "저기", True),  # plain "there": either
    (("저", "that (when something is far away)"), "그", False),  # the card says far
    (("저기", "there (when farther away)"), "거기", False),
    (("그", "he, him"), "저", False),  # 그 as "he" is not a demonstrative
    (("저", "I, me (formal)"), "그", False),  # nor 저 as "I"
])
def test_demonstrative_partner_accepted(conn, demonstratives, card, answer, correct):
    r = grade_word(conn, demonstratives(*card), answer)
    assert r["correct"] is correct


def test_demonstrative_note(conn, demonstratives):
    r = grade_word(conn, demonstratives("그", "that"), "저")
    assert r["note"] == 'Also correct: both 그 and 저 mean "that". 그 is near the listener, 저 is far from both of you.'
