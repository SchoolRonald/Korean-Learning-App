from datetime import datetime, timezone

from app.checker import check_entry


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def grade_word(conn, word_id, answer):
    """Check an answer for a word. Returns None if the word does not exist."""
    word = conn.execute("SELECT hangul, english FROM words WHERE id = ?", (word_id,)).fetchone()
    if word is None:
        return None
    result = check_entry(word[0], answer)
    if not result["correct"]:
        # Another word with the same English meaning is also a right answer.
        others = conn.execute(
            "SELECT hangul FROM words WHERE lower(english) = lower(?) AND id != ?", (word[1], word_id)
        ).fetchall()
        if any(check_entry(o[0], answer)["correct"] for o in others):
            result.update(correct=True, note=f"Also correct. This card's word is {word[0]}.")
    return result


def record_word_attempt(conn, word_id, answer, correct, ts=None):
    ts = ts or now_iso()
    conn.execute(
        "INSERT INTO attempts (kind, ref_id, answer, correct, ts) VALUES ('word', ?, ?, ?, ?)",
        (word_id, answer, int(correct), ts),
    )
    conn.execute(
        """INSERT INTO stats (word_id, attempts, fails, last_seen) VALUES (?, 1, ?, ?)
           ON CONFLICT (word_id) DO UPDATE SET
             attempts = attempts + 1, fails = fails + excluded.fails, last_seen = excluded.last_seen""",
        (word_id, int(not correct), ts),
    )
    conn.commit()
