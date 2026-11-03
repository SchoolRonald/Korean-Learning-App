import random
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.db import connect, init_db
from app.drill import record_word_attempt
from app.memory import confidence, confidence_parts, since_correct, streaks, word_stats
from app.stats import summary

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def days_ago(n):
    return (NOW - timedelta(days=n)).isoformat()


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
        [("물", "water", 1), ("책", "book", 1), ("개", "dog", 1), ("집", "house", 1), ("학교", "school", 2)],
    )
    c.execute("INSERT INTO learned (word_id, learned_at) SELECT id, '2026-10-01' FROM words")
    c.commit()
    return c


def word_id(conn, hangul):
    return conn.execute("SELECT id FROM words WHERE hangul = ?", (hangul,)).fetchone()[0]


def wid(conn, hangul):
    return word_id(conn, hangul)


def answer(conn, hangul, results, last_day=0):
    """Record answers oldest first; the last one lands last_day days before NOW."""
    wid = word_id(conn, hangul)
    for i, correct in enumerate(results):
        ts = days_ago(last_day + len(results) - 1 - i)
        record_word_attempt(conn, wid, "x", correct, ts=ts)


def test_confidence_unseen_is_zero():
    assert confidence(0, 0, 0, None, NOW) == 0.0


def test_confidence_smoothed_accuracy_when_just_seen():
    assert confidence(1, 0, 1, days_ago(0), NOW) == pytest.approx(2 / 3)
    assert confidence(10, 0, 10, days_ago(0), NOW) == pytest.approx(11 / 12)


def test_confidence_halves_after_half_life():
    # streak 3 -> half-life 8 days
    fresh = confidence(3, 0, 3, days_ago(0), NOW)
    assert confidence(3, 0, 3, days_ago(8), NOW) == pytest.approx(fresh / 2)


def test_confidence_after_miss_decays_fast():
    # streak 0 -> half-life 1 day
    assert confidence(2, 1, 0, days_ago(2), NOW) == pytest.approx(0.5 * 0.25)


def test_confidence_half_life_capped():
    a = confidence(20, 0, 20, days_ago(64), NOW)
    assert a == pytest.approx(21 / 22 * 0.5)


def test_longer_streak_remembers_longer():
    assert confidence(4, 0, 4, days_ago(5), NOW) > confidence(4, 0, 1, days_ago(5), NOW)


def test_streaks_count_back_from_latest(conn):
    answer(conn, "물", [True, False, True, True])
    answer(conn, "책", [True, True, False])
    answer(conn, "개", [True, True])
    s = streaks(conn)
    assert s[word_id(conn, "물")] == 2
    assert s[word_id(conn, "책")] == 0
    assert s[word_id(conn, "개")] == 2


def test_summary_lists(conn):
    answer(conn, "물", [False, False, True], last_day=1)  # fail rate 2/3
    answer(conn, "책", [False, True, True, True], last_day=10)  # fail rate 1/4, oldest
    answer(conn, "개", [True, True], last_day=0)  # never failed
    answer(conn, "학교", [False], last_day=0)  # lesson 2, outside range
    s = summary(conn, 1, NOW)
    assert (s["total"], s["practiced"]) == (4, 3)
    assert [w["hangul"] for w in s["weakest"]] == ["물", "책"]
    assert [w["hangul"] for w in s["stale"]] == ["책", "물", "개"]
    assert s["words"][0]["hangul"] == "집" and s["words"][0]["confidence"] == 0
    assert [w["confidence"] for w in s["words"]] == sorted(w["confidence"] for w in s["words"])
    assert s["avg_confidence"] == pytest.approx(sum(w["confidence"] for w in s["words"]) / 4)


def test_summary_empty_range(conn):
    s = summary(conn, 0, NOW)
    assert s["total"] == 0 and s["avg_confidence"] == 0 and s["words"] == []


def test_api_stats_and_page(conn, db_file, monkeypatch):
    monkeypatch.setattr(main, "db_path", db_file)
    answer(conn, "물", [False])
    with TestClient(main.app) as client:
        body = client.get("/api/stats", params={"lesson": 1}).json()
        assert body["weakest"][0]["hangul"] == "물"
        assert "Stats" in client.get("/stats").text


def test_answer_decay_halves_after_half_life_of_answers():
    # streak 0 -> half-life 1 day, 10 answers; streak 2 -> 4 days, 40 answers
    assert confidence(2, 1, 0, days_ago(0), NOW, gap=10) == pytest.approx(0.5 * 0.5)
    fresh = confidence(2, 0, 2, days_ago(0), NOW)
    assert confidence(2, 0, 2, days_ago(0), NOW, gap=40) == pytest.approx(fresh / 2)


def test_confidence_parts_multiply():
    p = confidence_parts(4, 1, 1, days_ago(2), NOW, gap=5)
    assert p["half_life"] == 2
    assert p["confidence"] == pytest.approx(p["accuracy"] * p["time_decay"] * p["answer_decay"])
    assert p["answer_decay"] == pytest.approx(0.5 ** (5 / 20))


def test_answers_counted_since_last_correct(conn):
    answer(conn, "물", [True])
    answer(conn, "책", [True])
    answer(conn, "개", [True, False])
    answer(conn, "물", [True])
    answer(conn, "집", [False])
    s = since_correct(conn)
    # 개's own miss after its last correct answer counts; 집 was never right.
    assert [s[wid(conn, w)][1] for w in ("물", "책", "개")] == [1, 4, 3]
    assert wid(conn, "집") not in s


def test_never_correct_is_zero(conn):
    answer(conn, "물", [False, False])
    w = next(w for w in summary(conn, 1, NOW)["words"] if w["hangul"] == "물")
    assert w["confidence"] == 0 and w["accuracy"] == pytest.approx(1 / 4)


def test_other_answers_lower_confidence(conn):
    answer(conn, "물", [True])
    before = {w["hangul"]: w["confidence"] for w in summary(conn, 1, NOW)["words"]}["물"]
    answer(conn, "책", [True] * 10)
    after = {w["hangul"]: w for w in summary(conn, 1, NOW)["words"]}["물"]
    # streak 1: half-life 2 -> 20 answers, so 10 other answers take it to 1/sqrt(2)
    assert after["gap"] == 10 and after["confidence"] == pytest.approx(before * 0.5 ** 0.5, rel=0.01)


def word_confidence(conn, hangul, now):
    return next(w for w in word_stats(conn, 99, now) if w["hangul"] == hangul)["confidence"]


@pytest.mark.parametrize("seed", range(40))
def test_wrong_never_raises_and_right_never_lowers_confidence(conn, seed):
    """Over random histories (several words, answers spread over days), one more wrong answer
    never raises a word's confidence and one more right answer never lowers it."""
    rng = random.Random(seed)
    words = ["물", "책", "개"]
    t = NOW - timedelta(days=30)
    for _ in range(rng.randint(1, 25)):
        t += timedelta(hours=rng.choice([0.1, 1, 12, 48]))
        record_word_attempt(conn, wid(conn, rng.choice(words)), "x", rng.random() < 0.6, ts=t.isoformat())
    later = t + timedelta(minutes=1)
    for target in words:
        before = word_confidence(conn, target, later)
        for correct in (False, True):
            probe = sqlite3.connect(":memory:")  # record_word_attempt commits, so answer on a copy
            conn.backup(probe)
            record_word_attempt(probe, wid(conn, target), "x", correct, ts=later.isoformat())
            after = word_confidence(probe, target, later)
            if correct:
                assert after >= before - 1e-9, f"right answer lowered {target}: {before:.3f} -> {after:.3f}"
            else:
                assert after <= before + 1e-9, f"wrong answer raised {target}: {before:.3f} -> {after:.3f}"
