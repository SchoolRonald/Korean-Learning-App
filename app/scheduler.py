import random

from app.memory import in_scope, word_stats

TOP_K = 5


def ranked_words(conn, max_lesson, now=None, rng=random, topic_ids=None):
    """Learned words in scope as (priority, word) pairs, least confident first.

    Priority is 1 - confidence, so words not yet drilled (confidence 0) come first.
    """
    words = in_scope(word_stats(conn, max_lesson, now), topic_ids, learned_only=True)
    # Shuffle first so ties (e.g. many unseen words) are not always broken by id.
    rng.shuffle(words)
    ranked = [(1 - w["confidence"], w) for w in words]
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked


def next_word(conn, max_lesson, now=None, rng=random, exclude=None, topic_ids=None):
    ranked = ranked_words(conn, max_lesson, now, rng, topic_ids)
    # Skip the word just answered, unless it is the only one available.
    others = [pair for pair in ranked if pair[1]["id"] != exclude]
    ranked = others or ranked
    if not ranked:
        return None
    return rng.choice(ranked[:TOP_K])[1]
