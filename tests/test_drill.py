import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.db import connect, init_db
from app.drill import grade_word, record_word_attempt


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    c.executemany(
        "INSERT INTO words (hangul, english, lesson) VALUES (?, ?, ?)",
        [("물", "water", 1), ("나", "I", 1), ("저", "I", 2), ("책", "book", 3)],
    )
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
def client(conn, monkeypatch):
    monkeypatch.setattr(main, "conn", conn)
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


def test_index_serves_page(client):
    res = client.get("/")
    assert res.status_code == 200 and "Spelling drill" in res.text


def test_api_lessons(client):
    assert client.get("/api/lessons").json() == [1, 2, 3]


def test_api_next_exclude(client, conn):
    wid = word_id(conn, "물")
    for _ in range(20):
        assert client.get("/api/next", params={"lesson": 1, "exclude": wid}).json()["id"] != wid
