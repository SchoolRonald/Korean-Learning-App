import random

from app.memory import word_stats

TOP_K = 5


def ranked_words(conn, max_lesson, now=None, rng=random):
    """Words with lesson <= max_lesson as (priority, word) pairs, least confident first.

    Priority is 1 - confidence, so unpracticed words (confidence 0) come first.
    """
    words = word_stats(conn, max_lesson, now)
    # Shuffle first so ties (e.g. many unseen words) are not always broken by id.
    rng.shuffle(words)
    ranked = [(1 - w["confidence"], w) for w in words]
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked


def next_word(conn, max_lesson, now=None, rng=random, exclude=None):
    ranked = ranked_words(conn, max_lesson, now, rng)
    # Skip the word just answered, unless it is the only one available.
    others = [pair for pair in ranked if pair[1]["id"] != exclude]
    ranked = others or ranked
    if not ranked:
        return None
    return rng.choice(ranked[:TOP_K])[1]
