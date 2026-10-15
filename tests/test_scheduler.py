import random
from datetime import datetime, timedelta, timezone

import pytest

from app.db import connect, init_db
from app.drill import record_word_attempt
from app.scheduler import next_word, ranked_words

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    return c


def add_word(conn, hangul, lesson, answers=(), last_day=0):
    """Add a word and its answer history, oldest first; the last answer is last_day days before NOW."""
    word_id = conn.execute(
        "INSERT INTO words (hangul, english, lesson) VALUES (?, ?, ?)", (hangul, hangul, lesson)
    ).lastrowid
    for i, correct in enumerate(answers):
        ts = (NOW - timedelta(days=last_day + len(answers) - 1 - i)).isoformat()
        record_word_attempt(conn, word_id, "x", correct, ts=ts)
    return word_id


def order(conn, max_lesson=1):
    return [w["hangul"] for _, w in ranked_words(conn, max_lesson, NOW, random.Random(0))]


def test_only_words_up_to_max_lesson(conn):
    add_word(conn, "a", 1)
    add_word(conn, "b", 2)
    add_word(conn, "c", 3)
    lessons = {w["lesson"] for _, w in ranked_words(conn, 2, NOW)}
    assert lessons == {1, 2}
    for seed in range(50):
        assert next_word(conn, 2, NOW, random.Random(seed))["lesson"] <= 2


def test_no_words_returns_none(conn):
    add_word(conn, "a", 5)
    assert next_word(conn, 1, NOW) is None


def test_priority_is_one_minus_confidence(conn):
    add_word(conn, "new", 1)
    add_word(conn, "once", 1, [True])
    pairs = {w["hangul"]: (p, w["confidence"]) for p, w in ranked_words(conn, 1, NOW)}
    assert pairs["new"] == (1.0, 0.0)
    assert pairs["once"][0] == pytest.approx(1 - pairs["once"][1])


def test_ranking_order(conn):
    add_word(conn, "known", 1, [True] * 20, last_day=7)  # long streak, fades slowly
    add_word(conn, "missed", 1, [False], last_day=0)  # 33% right after a miss
    add_word(conn, "fading", 1, [True], last_day=7)  # one correct answer, a week ago
    add_word(conn, "new", 1)
    assert order(conn) == ["new", "fading", "missed", "known"]


def test_streak_slows_forgetting(conn):
    # Both perfect and last seen 7 days ago; the old formula gave them the same score.
    add_word(conn, "streak", 1, [True] * 20, last_day=7)
    add_word(conn, "once", 1, [True], last_day=7)
    assert order(conn) == ["once", "streak"]


def test_recent_miss_resets_streak(conn):
    add_word(conn, "relapsed", 1, [True] * 5 + [False], last_day=1)
    add_word(conn, "steady", 1, [True] * 5 + [False] + [True], last_day=1)
    assert order(conn) == ["relapsed", "steady"]


def test_picks_only_from_top_5(conn):
    top = {add_word(conn, f"new{i}", 1) for i in range(5)}
    for i in range(5):
        add_word(conn, f"known{i}", 1, [True] * 10)
    picked = {next_word(conn, 1, NOW, random.Random(seed))["id"] for seed in range(200)}
    assert picked == top


def test_ties_do_not_always_favor_low_ids(conn):
    ids = [add_word(conn, f"new{i}", 1) for i in range(50)]
    picked = {next_word(conn, 1, NOW, random.Random(seed))["id"] for seed in range(200)}
    assert picked - set(ids[:5])


def test_exclude_skips_last_word(conn):
    first = add_word(conn, "a", 1)
    add_word(conn, "b", 1)
    for seed in range(50):
        assert next_word(conn, 1, NOW, random.Random(seed), exclude=first)["id"] != first


def test_exclude_falls_back_when_only_word(conn):
    only = add_word(conn, "a", 1)
    assert next_word(conn, 1, NOW, exclude=only)["id"] == only
