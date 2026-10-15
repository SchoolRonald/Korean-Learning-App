from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.db import connect, init_db
from app.drill import record_word_attempt
from app.memory import confidence, streaks
from app.stats import summary

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def days_ago(n):
    return (NOW - timedelta(days=n)).isoformat()


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    c.executemany(
        "INSERT INTO words (hangul, english, lesson) VALUES (?, ?, ?)",
        [("물", "water", 1), ("책", "book", 1), ("개", "dog", 1), ("집", "house", 1), ("학교", "school", 2)],
    )
    return c


def word_id(conn, hangul):
    return conn.execute("SELECT id FROM words WHERE hangul = ?", (hangul,)).fetchone()[0]


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


def test_api_stats_and_page(conn, monkeypatch):
    monkeypatch.setattr(main, "conn", conn)
    answer(conn, "물", [False])
    with TestClient(main.app) as client:
        body = client.get("/api/stats", params={"lesson": 1}).json()
        assert body["weakest"][0]["hangul"] == "물"
        assert "Stats" in client.get("/stats").text
