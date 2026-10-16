from datetime import datetime, timezone


def days_since(last_seen, now):
    seen = datetime.fromisoformat(last_seen)
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return max((now - seen).total_seconds() / 86400, 0)


MAX_HALF_LIFE_DAYS = 64


def confidence(attempts, fails, streak, last_seen, now):
    """Estimated chance (0 to 1) that you know the word right now: accuracy x memory."""
    if not attempts or last_seen is None:
        return 0.0
    # Smoothed accuracy: one lucky answer is not certainty (1/1 -> 0.67, 10/10 -> 0.92).
    accuracy = (attempts - fails + 1) / (attempts + 2)
    # Memory halves every half_life days; each correct answer in a row doubles the half-life.
    half_life = min(2 ** streak, MAX_HALF_LIFE_DAYS)
    return accuracy * 0.5 ** (days_since(last_seen, now) / half_life)


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
        words.append({
            "id": word_id, "hangul": hangul, "english": english, "lesson": lesson,
            "attempts": attempts, "fails": fails,
            "fail_rate": fails / attempts if attempts else None,
            "last_seen": last_seen,
            "days_since": days_since(last_seen, now) if last_seen else None,
            "streak": streak,
            "confidence": confidence(attempts, fails, streak, last_seen, now),
            "learned": bool(learned),
        })
    return words


def in_scope(words, topic_ids=None, learned_only=False):
    """Narrow word_stats() output to a topic's words and/or to learned words."""
    return [
        w for w in words
        if (topic_ids is None or w["id"] in topic_ids) and (w["learned"] or not learned_only)
    ]
