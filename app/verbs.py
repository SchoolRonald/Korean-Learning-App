import os
import random
import re
import time

from app import krdict
from app.checker import answer_variants
from app.conjugate import detect_class
from app.drill import now_iso

NEW_LOOKUPS = 6
LOOKUP_TIMEOUT = 5
PAUSE_AFTER_FAILURE = 600
_paused_until = 0.0


def quick_fetch(endpoint, params):
    return krdict.fetch(endpoint, params, timeout=LOOKUP_TIMEOUT)

# Verbs with known classes, so every irregular class has something to drill even before
# the learner's own vocabulary includes one.
SEED = [
    ("가다", "to go", "regular", False), ("먹다", "to eat", "regular", False), ("보다", "to see", "regular", False),
    ("마시다", "to drink", "regular", False), ("읽다", "to read", "regular", False), ("하다", "to do", "하다", False),
    ("공부하다", "to study", "하다", False), ("좋다", "to be good", "regular", True), ("작다", "to be small", "regular", True),
    ("듣다", "to listen", "ㄷ", False), ("걷다", "to walk", "ㄷ", False),
    ("돕다", "to help", "ㅂ", False), ("덥다", "to be hot", "ㅂ", True), ("춥다", "to be cold", "ㅂ", True),
    ("쉽다", "to be easy", "ㅂ", True), ("어렵다", "to be difficult", "ㅂ", True),
    ("짓다", "to build", "ㅅ", False), ("낫다", "to get better", "ㅅ", False),
    ("빨갛다", "to be red", "ㅎ", True), ("파랗다", "to be blue", "ㅎ", True), ("어떻다", "to be how", "ㅎ", True),
    ("모르다", "to not know", "르", False), ("부르다", "to call, to sing", "르", False),
    ("다르다", "to be different", "르", True), ("빠르다", "to be fast", "르", True),
    ("쓰다", "to write", "으", False), ("크다", "to be big", "으", True), ("바쁘다", "to be busy", "으", True),
    ("아프다", "to be sick", "으", True), ("예쁘다", "to be pretty", "으", True),
    ("알다", "to know", "ㄹ", False), ("살다", "to live", "ㄹ", False), ("만들다", "to make", "ㄹ", False),
    ("길다", "to be long", "ㄹ", True), ("멀다", "to be far", "ㄹ", True),
]


def english_words(text):
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in {"to", "be", "a", "an", "the", "of", "something"}}


def choose_class(entries, english):
    """The class of the entry that means what the word list says. None when it stays unclear
    (묻다 is "to ask" (ㄷ) and "to bury" (regular); the meaning decides)."""
    classified = [(e, detect_class(e["word"], e["forms"])) for e in entries]
    classified = [(e, c) for e, c in classified if c]
    wanted = english_words(english)
    meaning = [(e, c) for e, c in classified if wanted & set().union(*(english_words(t) for t in e["english"]))]
    for pool in (meaning, classified):
        classes = {c for _, c in pool}
        if len(classes) == 1:
            entry = pool[0][0]
            return classes.pop(), entry["pos"] == "형용사"
        if pool:
            return None, None
    return None, None


def classify(conn, hangul, english, get=quick_fetch):
    """Looks a word up in krdict once and saves its class (or that it is unclear).
    Raises KrdictError when krdict cannot be reached, and then saves nothing."""
    entries = [{**e, "word": hangul} for e in krdict.verb_entries(hangul, get)]
    cls, adjective = choose_class(entries, english)
    conn.execute(
        "INSERT OR REPLACE INTO verb_classes (hangul, english, adjective, class, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (hangul, english, None if adjective is None else int(adjective), cls, "krdict", now_iso()),
    )
    conn.commit()
    return cls


def word_list_verbs(conn, max_lesson):
    """Words in scope that are verbs or adjectives, as (dictionary form, english, learned), learned first."""
    rows = conn.execute(
        """SELECT w.hangul, w.english, l.word_id IS NOT NULL FROM words w LEFT JOIN learned l ON l.word_id = w.id
           WHERE w.lesson <= ? AND lower(w.english) LIKE 'to %' ORDER BY l.word_id IS NULL, w.lesson, w.id""",
        (max_lesson,),
    ).fetchall()
    verbs = []
    for hangul, english, learned in rows:
        form = answer_variants(hangul)[0]
        if form.endswith("다") and " " not in form and len(form) >= 2:
            verbs.append((form, english, bool(learned)))
    return verbs


def drill_verbs(conn, max_lesson, classes=None, adjective=None, rng=random, get=quick_fetch):
    """Verbs to drill: from the learner's words where their class is known (learned words first),
    otherwise from the built-in list. Looks up a few unknown words per call. When krdict cannot be
    reached, it is not asked again for a while, so practice never waits on it."""
    global _paused_until
    known = {(r[0], r[1]): (r[2], r[3]) for r in conn.execute("SELECT hangul, english, class, adjective FROM verb_classes")}
    lookups = NEW_LOOKUPS if os.environ.get("KRDICT_API_KEY") and time.time() >= _paused_until else 0
    result = []
    for form, english, learned in word_list_verbs(conn, max_lesson):
        if (form, english) not in known:
            if lookups <= 0:
                continue
            lookups -= 1
            try:
                classify(conn, form, english, get)
            except krdict.KrdictError:
                _paused_until = time.time() + PAUSE_AFTER_FAILURE
                lookups = 0
                continue
            row = conn.execute("SELECT class, adjective FROM verb_classes WHERE hangul = ? AND english = ?",
                               (form, english)).fetchone()
            known[(form, english)] = (row[0], row[1]) if row else (None, None)
        cls, adj = known[(form, english)]
        if cls and fits(cls, bool(adj), classes, adjective):
            result.append({"hangul": form, "english": english, "class": cls, "adjective": bool(adj), "learned": learned})
    if len(result) < 3:
        own = {v["hangul"] for v in result}
        result += [{"hangul": h, "english": e, "class": c, "adjective": a, "learned": False}
                   for h, e, c, a in SEED if h not in own and fits(c, a, classes, adjective)]
    return result


def fits(cls, adjective, classes, want_adjective):
    return (classes is None or cls in classes) and (want_adjective is None or adjective == want_adjective)
