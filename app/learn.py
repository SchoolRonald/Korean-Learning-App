import difflib
import random
import re

from app.checker import answer_variants, check, normalize
from app.drill import now_iso

BATCH_SIZE = 5
TYPO_RATIO = 0.85
HANGUL = re.compile(r"[가-힣]")


def cloze(form, rng=random):
    """Mask one syllable of a word with 2+ syllables, e.g. 선생님 -> 선_님. None for 1 syllable."""
    positions = [i for i, ch in enumerate(form) if HANGUL.match(ch)]
    if len(positions) < 2:
        return None
    i = rng.choice(positions)
    return {"index": i, "masked": form[:i] + "_" + form[i + 1:]}


def batch(conn, max_lesson, topic_ids=None, size=BATCH_SIZE, rng=random):
    """The next words to learn: not yet learned, at or below the lesson, in list order."""
    rows = conn.execute(
        """SELECT w.id, w.hangul, w.english, w.lesson FROM words w
           WHERE w.lesson <= ? AND NOT EXISTS (SELECT 1 FROM learned l WHERE l.word_id = w.id)
           ORDER BY w.lesson, w.id""",
        (max_lesson,),
    ).fetchall()
    if topic_ids is not None:
        rows = [r for r in rows if r[0] in topic_ids]
    words = []
    for word_id, hangul, english, lesson in rows[:size]:
        form = answer_variants(hangul)[0]
        words.append({
            "id": word_id, "hangul": hangul, "english": english, "lesson": lesson,
            "form": form, "cloze": cloze(form, rng),
        })
    return words


def normalize_english(text):
    text = re.sub(r"['’]", "", text.lower())  # mother’s, mother's -> mothers
    words = re.sub(r"[^\w\s]", " ", text).split()
    return " ".join(w for w in words if w not in ("a", "an", "the"))


def split_meanings(text, keep_notes=False):
    """Separate meanings on , / ; and drop asterisks. Bracketed notes are dropped, or with
    keep_notes kept as plain words ("that (thing)" -> "that thing")."""
    text = re.sub(r"[()]", " ", text) if keep_notes else re.sub(r"\([^)]*\)", "", text)
    parts = re.split(r"[,/;]", text.replace("*", ""))
    return [m for m in (normalize_english(p) for p in parts) if m]


def meanings(english):
    """Accepted English answers: "to be interested in" also accepts "be interested in" and "interested in",
    and "that (thing)" accepts "that" and "that thing"."""
    accepted = set()
    for meaning in split_meanings(english) + split_meanings(english, keep_notes=True):
        accepted.add(meaning)
        for prefix in ("to be ", "to "):
            if meaning.startswith(prefix):
                accepted.add(meaning[len(prefix):])
    return accepted


def english_ok(english, answer):
    """Lenient check of a typed English meaning, allowing a small typo.
    An answer listing several meanings ("I, me") is accepted when each one is right.
    """
    accepted = meanings(english)

    def close(typed):
        return typed in accepted or len(typed) >= 4 and any(
            difflib.SequenceMatcher(None, typed, m).ratio() >= TYPO_RATIO for m in accepted
        )

    typed = split_meanings(answer)
    return bool(typed) and all(close(t) for t in typed)


def cloze_check(form, index, answer):
    """Check a filled-in blank: either just the missing syllable, or the whole word typed over."""
    if len(normalize(answer).replace(" ", "")) <= 1:
        return {**check(form[index], answer), "expected": form}
    return check(form, answer)


def get_word(conn, word_id):
    return conn.execute("SELECT hangul, english FROM words WHERE id = ?", (word_id,)).fetchone()


def mark_learned(conn, word_id, ts=None):
    conn.execute("INSERT OR IGNORE INTO learned (word_id, learned_at) VALUES (?, ?)", (word_id, ts or now_iso()))
    conn.commit()
