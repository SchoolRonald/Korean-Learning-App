import random

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.db import connect, init_db
from app.learn import batch, cloze, cloze_check, english_ok, mark_learned


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
        [("선생님", "teacher", 1), ("물", "water", 1), ("아기 / 애기", "baby, infant", 2), ("학교", "school", 3)],
    )
    c.commit()
    return c


def word_id(conn, hangul):
    return conn.execute("SELECT id FROM words WHERE hangul = ?", (hangul,)).fetchone()[0]


@pytest.mark.parametrize("english, answer", [
    ("I, me (formal)", "I"),
    ("I, me (formal)", "me"),
    ("to be interested in", "to be interested in"),
    ("to be interested in", "be interested in"),
    ("to be interested in", "interested in"),
    ("tree/wood", "wood"),
    ("old days, past", "the past"),
    ("Korea", "korea"),
    ("June*", "June"),
    ("How is/was … ?", "how is"),
    ("teacher", "teachr"),  # small typo
    ("to eat", "eat"),
    ("I, me (formal)", "I, me"),
    ("that (thing)", "that thing"),
    ("that (thing)", "that"),
    ("Korean (language)", "Korean language"),
    ("aunt (on mother’s side)", "aunt on mother's side"),
    ("(the color) black", "the color black"),
    ("(the color) black", "(the color) black"),
])
def test_english_accepted(english, answer):
    assert english_ok(english, answer)


@pytest.mark.parametrize("english, answer", [
    ("I, me (formal)", "formal"),  # bracketed notes are not meanings
    ("name", "city"),
    ("dog", "dig"),  # no typo allowance under 4 letters
    ("water", ""),
    ("water", "   "),
    ("I, me (formal)", "I, dog"),  # every listed meaning must be right
])
def test_english_rejected(english, answer):
    assert not english_ok(english, answer)


def test_cloze_masks_one_hangul_syllable():
    for seed in range(20):
        c = cloze("관심이 있다", random.Random(seed))
        assert c["masked"].count("_") == 1 and "관심이 있다"[c["index"]] != " "
    assert cloze("물") is None


def test_cloze_check():
    assert cloze_check("선생님", 1, "생")["correct"]
    assert cloze_check("선생님", 1, "선생님")["correct"]  # whole word also counts
    wrong = cloze_check("선생님", 1, "샹")
    assert not wrong["correct"] and wrong["expected"] == "선생님"
    assert wrong["syllables"][0]["parts"] == ["vowel"]
    # Typed over the whole word: feedback points at the syllable in the word.
    whole = cloze_check("선생님", 1, "선샹님")
    assert not whole["correct"] and whole["feedback"] == ["Syllable 2: expected 생, you typed 샹 (vowel wrong)"]


def test_batch_order_scope_and_form(conn):
    words = batch(conn, 2)
    assert [w["hangul"] for w in words] == ["선생님", "물", "아기 / 애기"]
    assert words[2]["form"] == "아기"
    assert words[1]["cloze"] is None and words[0]["cloze"]["masked"].count("_") == 1
    assert [w["hangul"] for w in batch(conn, 2, size=1)] == ["선생님"]
    assert [w["hangul"] for w in batch(conn, 3, topic_ids={word_id(conn, "학교")})] == ["학교"]


def test_batch_skips_learned(conn):
    mark_learned(conn, word_id(conn, "선생님"))
    mark_learned(conn, word_id(conn, "선생님"))  # idempotent
    assert [w["hangul"] for w in batch(conn, 1)] == ["물"]


@pytest.fixture
def client(conn, db_file, monkeypatch):
    monkeypatch.setattr(main, "db_path", db_file)
    with TestClient(main.app) as c:
        yield c


def test_api_learn_flow(client, conn):
    assert client.get("/api/next", params={"lesson": 1}).status_code == 404
    words = client.get("/api/learn/batch", params={"lesson": 1}).json()
    teacher = words[0]
    r = client.post("/api/learn/check", json={"word_id": teacher["id"], "step": "english", "answer": "a teacher"}).json()
    assert r["correct"]
    i = teacher["cloze"]["index"]
    r = client.post("/api/learn/check", json={"word_id": teacher["id"], "step": "cloze", "answer": "선생님"[i], "index": i})
    assert r.json()["correct"]
    assert client.post("/api/learn/done", json={"word_id": teacher["id"]}).json() == {"ok": True}
    assert client.get("/api/next", params={"lesson": 1}).json()["id"] == teacher["id"]
    assert [w["hangul"] for w in client.get("/api/learn/batch", params={"lesson": 1}).json()] == ["물"]


def test_api_learn_bad_input(client, conn):
    wid = word_id(conn, "선생님")
    assert client.post("/api/learn/check", json={"word_id": wid, "step": "cloze", "answer": "x"}).status_code == 400
    assert client.post("/api/learn/check", json={"word_id": wid, "step": "cloze", "answer": "x", "index": 9}).status_code == 400
    assert client.post("/api/learn/check", json={"word_id": wid, "step": "spell", "answer": "x"}).status_code == 422
    assert client.post("/api/learn/check", json={"word_id": 999, "step": "english", "answer": "x"}).status_code == 404
    assert client.post("/api/learn/done", json={"word_id": 999}).status_code == 404
