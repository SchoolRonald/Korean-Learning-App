from datetime import datetime, timezone


def days_since(last_seen, now):
    seen = datetime.fromisoformat(last_seen)
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return max((now - seen).total_seconds() / 86400, 0)


MAX_HALF_LIFE = 64  # cap on the streak multiplier: 64 days, 640 answers
ANSWERS_PER_DAY = 10  # half-life in answers per day of half-life: a miss means 1 day or 10 answers


def confidence_parts(attempts, fails, streak, last_correct, now, gap=0):
    """The pieces of confidence: accuracy x time decay x answer decay.

    Smoothed accuracy: one lucky answer is not certainty (1/1 -> 0.67, 10/10 -> 0.92).
    Both decays count from the last *correct* answer, since only a correct answer shows the word
    is remembered: time decay halves every half_life days since then, and answer decay every
    half_life * ANSWERS_PER_DAY drill answers since then (gap, including misses of this word).
    Each correct answer in a row doubles the half-life. So a wrong answer (lower accuracy,
    streak reset, one more answer) can never raise confidence, and a right one never lowers it.
    A word never answered correctly is 0.
    """
    if not attempts or last_correct is None:
        accuracy = (attempts - fails + 1) / (attempts + 2) if attempts else 0.0
        return {"accuracy": accuracy, "time_decay": 0.0, "answer_decay": 0.0, "half_life": 1, "confidence": 0.0}
    accuracy = (attempts - fails + 1) / (attempts + 2)
    half_life = min(2 ** streak, MAX_HALF_LIFE)
    time_decay = 0.5 ** (days_since(last_correct, now) / half_life)
    answer_decay = 0.5 ** (gap / (half_life * ANSWERS_PER_DAY))
    return {"accuracy": accuracy, "time_decay": time_decay, "answer_decay": answer_decay,
            "half_life": half_life, "confidence": accuracy * time_decay * answer_decay}


def confidence(attempts, fails, streak, last_correct, now, gap=0):
    """Estimated chance (0 to 1) that you know the word right now."""
    return confidence_parts(attempts, fails, streak, last_correct, now, gap)["confidence"]


def since_correct(conn):
    """For each word answered correctly at least once: when it last was, and how many drill
    answers (to any word, including misses of this one) came after it."""
    rows = conn.execute(
        """SELECT a.ref_id, a.ts, (SELECT count(*) FROM attempts b WHERE b.kind = 'word' AND b.id > a.id)
           FROM attempts a
           JOIN (SELECT max(id) AS id FROM attempts WHERE kind = 'word' AND correct = 1 GROUP BY ref_id) last
             ON a.id = last.id"""
    )
    return {word_id: (ts, gap) for word_id, ts, gap in rows}


def streaks(conn):
    """Number of correct answers in a row, counting back from the latest, per word id."""
    result, finished = {}, set()
    rows = conn.execute(
        "SELECT ref_id, correct FROM attempts WHERE kind = 'word' ORDER BY ref_id, ts DESC, id DESC"
    )
    for word_id, correct in rows:
        if word_id in finished:
            continue
        if correct:
            result[word_id] = result.get(word_id, 0) + 1
        else:
            result.setdefault(word_id, 0)
            finished.add(word_id)
    return result


def word_stats(conn, max_lesson, now=None):
    now = now or datetime.now(timezone.utc)
    streak_by_id = streaks(conn)
    correct_by_id = since_correct(conn)
    rows = conn.execute(
        """SELECT w.id, w.hangul, w.english, w.lesson,
                  coalesce(s.attempts, 0), coalesce(s.fails, 0), s.last_seen, l.word_id IS NOT NULL
           FROM words w LEFT JOIN stats s ON s.word_id = w.id LEFT JOIN learned l ON l.word_id = w.id
           WHERE w.lesson <= ? ORDER BY w.lesson, w.id""",
        (max_lesson,),
    ).fetchall()
    words = []
    for word_id, hangul, english, lesson, attempts, fails, last_seen, learned in rows:
        streak = streak_by_id.get(word_id, 0)
        last_correct, gap = correct_by_id.get(word_id, (None, 0))
        parts = confidence_parts(attempts, fails, streak, last_correct, now, gap)
        words.append({
            "id": word_id, "hangul": hangul, "english": english, "lesson": lesson,
            "attempts": attempts, "fails": fails,
            "fail_rate": fails / attempts if attempts else None,
            "last_seen": last_seen,
            "days_since": days_since(last_seen, now) if last_seen else None,
            "streak": streak,
            "last_correct": last_correct,
            "gap": gap,
            **parts,
            "learned": bool(learned),
        })
    return words


def in_scope(words, topic_ids=None, learned_only=False):
    """Narrow word_stats() output to a topic's words and/or to learned words."""
    return [
        w for w in words
        if (topic_ids is None or w["id"] in topic_ids) and (w["learned"] or not learned_only)
    ]
