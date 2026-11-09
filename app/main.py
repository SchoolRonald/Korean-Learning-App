import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.db import DB_PATH, connect, init_db
from app.drill import grade_word, record_word_attempt
from app import grammar, jev, practice, profile
from app.checker import answer_variants
from app.learn import HANGUL, batch, cloze_check, english_ok, get_word, mark_learned
from app.llm import LLMError, usage_summary
from app.memory import ANSWERS_PER_DAY, in_scope, word_stats
from app.scheduler import TOP_K, next_word, pick_pool
from app.sentences import FOCUS_COUNT, NotReady, explain_sentence, focus_pool, get_sentence, grade_sentence, prefetch
from app.stats import summary
from app.topics import TopicError, resolve, topic_word_ids

STATIC = Path(__file__).resolve().parent.parent / "static"

db_path = DB_PATH  # tests point this at a temporary file
_local = threading.local()


def db():
    """This thread's database connection.

    FastAPI runs requests and background tasks on a pool of threads, and one sqlite3
    connection must never be used by two threads at once, so each thread gets its own.
    """
    conns = _local.__dict__.setdefault("conns", {})
    if db_path not in conns:
        conns[db_path] = connect(db_path)
    return conns[db_path]


def prefetch_in_background(lesson, topic_ids):
    prefetch(db(), lesson, topic_ids)


def prefetch_grammar(point_id, lesson):
    grammar.prefetch_after(db(), point_id, lesson)


def prefetch_items(point_id, lesson):
    practice.prefetch_items(db(), point_id, lesson)


def scope_ids(topic):
    """The word ids of a topic (None for no topic). 404 for an unknown topic."""
    if topic is None:
        return None
    ids = topic_word_ids(db(), topic)
    if ids is None:
        raise HTTPException(404, "Unknown topic. Apply it again.")
    return ids


@asynccontextmanager
async def lifespan(app):
    init_db(db())
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def revalidate(request, call_next):
    # Without this, browsers reuse old pages and scripts after an update (a new page
    # calling a function an old cached common.js does not have). no-cache still lets
    # the browser keep a copy; it only checks with the server before using it.
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


class WordAnswer(BaseModel):
    word_id: int
    answer: str


class LearnCheck(BaseModel):
    word_id: int
    step: Literal["english", "cloze"]
    answer: str
    index: int | None = None


class LearnDone(BaseModel):
    word_id: int


class TopicRequest(BaseModel):
    name: str
    lesson: int


class SentenceAnswer(BaseModel):
    sentence_id: int
    answer: str


class GrammarPoint(BaseModel):
    point: str


class GrammarRequest(BaseModel):
    point: str
    lesson: int
    request: str = ""


class GrammarAnswer(BaseModel):
    item_id: int
    answer: str
    source: Literal["practice", "review"] = "practice"
    shown: str | None = None


class ProfileChange(BaseModel):
    add: str | None = None
    remove: int | None = None


class SentenceWhy(BaseModel):
    sentence_id: int
    answer: str


class GrammarWhy(BaseModel):
    item_id: int
    answer: str


class GrammarQuestion(BaseModel):
    point: str
    lesson: int
    question: str
    explanation_id: int | None = None


@app.get("/")
def learn_page():
    return FileResponse(STATIC / "learn.html")


@app.get("/basics")
def basics_page():
    return FileResponse(STATIC / "basics.html")


@app.get("/grammar")
def grammar_page():
    return FileResponse(STATIC / "grammar.html")


@app.get("/words")
def words_page():
    return FileResponse(STATIC / "words.html")


@app.get("/sentences")
def sentences_page():
    return FileResponse(STATIC / "sentences.html")


@app.get("/stats")
def stats_page():
    return FileResponse(STATIC / "stats.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/lessons")
def api_lessons():
    return [r[0] for r in db().execute("SELECT DISTINCT lesson FROM words ORDER BY lesson")]


@app.get("/api/next")
def api_next(lesson: int, exclude: int | None = None, topic: int | None = None):
    word = next_word(db(), lesson, exclude=exclude, topic_ids=scope_ids(topic))
    if word is None:
        where = "in this topic " if topic is not None else ""
        raise HTTPException(404, f"No learned words {where}up to lesson {lesson}. Learn some first in the Learn tab.")
    return {"id": word["id"], "english": word["english"], "lesson": word["lesson"]}


@app.post("/api/answer")
def api_answer(body: WordAnswer):
    result = grade_word(db(), body.word_id, body.answer)
    if result is None:
        raise HTTPException(404, "Unknown word")
    record_word_attempt(db(), body.word_id, body.answer, result["correct"])
    return result


@app.get("/api/learn/batch")
def api_learn_batch(lesson: int, topic: int | None = None):
    return batch(db(), lesson, scope_ids(topic))


@app.post("/api/learn/check")
def api_learn_check(body: LearnCheck):
    word = get_word(db(), body.word_id)
    if word is None:
        raise HTTPException(404, "Unknown word")
    if body.step == "english":
        return {"correct": english_ok(word[1], body.answer), "expected": word[1]}
    form = answer_variants(word[0])[0]
    if body.index is None or not 0 <= body.index < len(form) or not HANGUL.match(form[body.index]):
        raise HTTPException(400, "Bad cloze index")
    return cloze_check(form, body.index, body.answer)


@app.post("/api/learn/done")
def api_learn_done(body: LearnDone):
    if get_word(db(), body.word_id) is None:
        raise HTTPException(404, "Unknown word")
    mark_learned(db(), body.word_id)
    return {"ok": True}


@app.get("/api/sentence")
def api_sentence(lesson: int, background: BackgroundTasks, exclude: int | None = None, topic: int | None = None):
    topic_ids = scope_ids(topic)
    try:
        sentence = get_sentence(db(), lesson, exclude, topic_ids)
    except NotReady as e:
        raise HTTPException(404, str(e))
    except LLMError as e:
        raise HTTPException(503, str(e))
    # Runs after the response is sent.
    background.add_task(prefetch_in_background, lesson, topic_ids)
    return {**sentence, "llm": usage_summary()}


@app.post("/api/sentence/answer")
def api_sentence_answer(body: SentenceAnswer):
    result = grade_sentence(db(), body.sentence_id, body.answer)
    if result is None:
        raise HTTPException(404, "Unknown sentence")
    return {**result, "llm": usage_summary()}


@app.post("/api/sentence/why")
def api_sentence_why(body: SentenceWhy):
    try:
        result = explain_sentence(db(), body.sentence_id, body.answer)
    except LLMError as e:
        raise HTTPException(503, str(e))
    if result is None:
        raise HTTPException(404, "Unknown sentence")
    return {**result, "llm": usage_summary()}


@app.get("/api/stats")
def api_stats(lesson: int, topic: int | None = None):
    return {**summary(db(), lesson, topic_ids=scope_ids(topic)),
            "grammar": practice.grammar_summary(db(), lesson), "notes": profile.notes(db())}


@app.post("/api/topics")
def api_topics(body: TopicRequest):
    try:
        return {**resolve(db(), body.name, body.lesson), "llm": usage_summary()}
    except TopicError as e:
        raise HTTPException(404, str(e))
    except LLMError as e:
        raise HTTPException(503, str(e))


@app.get("/api/usage")
def api_usage():
    return {**usage_summary(), "jev_calls": jev.usage_summary()["calls"]}


def grammar_call(fn, *args):
    """Runs a grammar function, turning its errors into HTTP errors with safe messages."""
    try:
        return fn(*args)
    except grammar.GrammarError as e:
        raise HTTPException(404, str(e))
    except LLMError as e:
        raise HTTPException(503, str(e))


def present_with_plan(point):
    return {**grammar.present_point(db(), point), "practice_plan": practice.practice_plan(point)}


@app.get("/api/grammar/next")
def api_grammar_next(lesson: int, background: BackgroundTasks):
    point = grammar.next_point(db(), lesson)
    if point:
        # Writes the following point's lesson while the learner studies this one.
        background.add_task(prefetch_grammar, point["id"], lesson)
    return {"point": present_with_plan(point) if point else None,
            "outline": grammar.outline(db(), lesson)}


@app.get("/api/grammar/point")
def api_grammar_point(id: str, lesson: int, background: BackgroundTasks):
    point = grammar_call(grammar.get_point, id)
    background.add_task(prefetch_grammar, id, lesson)
    return {"point": present_with_plan(point), "outline": grammar.outline(db(), lesson),
            "custom": grammar.custom_explanations(db(), id)}


@app.get("/api/grammar/explain")
def api_grammar_explain(point: str, lesson: int, background: BackgroundTasks):
    result = grammar_call(grammar.lesson, db(), point, lesson)
    # The practice items are written while the learner reads the lesson.
    background.add_task(prefetch_items, point, lesson)
    return {**result, "llm": usage_summary()}


@app.post("/api/grammar/explain")
def api_grammar_explain_custom(body: GrammarRequest, background: BackgroundTasks):
    result = grammar_call(grammar.custom_explanation, db(), body.point, body.lesson, body.request)
    kind = "like" if result["request"] else "differently"
    note_behavior(background, kind, body.point, result["request"] or "")
    return {**result, "llm": usage_summary()}


def update_profile():
    profile.update_in_background(db())


def note_behavior(background, kind, point_id, detail="", correct=None):
    """Saves what the learner did, and refreshes the profile notes in the background when enough has built up."""
    if profile.record(db(), kind, point_id, detail, correct):
        background.add_task(update_profile)


@app.post("/api/grammar/ask")
def api_grammar_ask(body: GrammarQuestion):
    result = grammar_call(grammar.ask, db(), body.point, body.lesson, body.question, body.explanation_id)
    return {**result, "llm": usage_summary()}


@app.get("/api/grammar/item")
def api_grammar_item(point: str, type: str, lesson: int):
    return {**grammar_call(practice.get_item, db(), point, type, lesson), "llm": usage_summary()}


@app.get("/api/grammar/review")
def api_grammar_review(lesson: int, exclude: str | None = None, below: float | None = None):
    item = grammar_call(practice.review_item, db(), lesson, exclude, below)
    if item is None:
        raise HTTPException(404, "No learned grammar points to review yet." if below is None else "Nothing needs review.")
    return {**item, "llm": usage_summary()}


@app.post("/api/grammar/answer")
def api_grammar_answer(body: GrammarAnswer, background: BackgroundTasks):
    result = grammar_call(practice.grade, db(), body.item_id, body.answer, body.source)
    if result is None:
        raise HTTPException(404, "Unknown practice item")
    if body.shown is not None and result["verdict"] != "ungraded":
        # The first practice item of a new point: did the explanation on screen work?
        point_id = db().execute("SELECT point_id FROM grammar_items WHERE id = ?", (body.item_id,)).fetchone()[0]
        note_behavior(background, "practice", point_id, body.shown, result["correct"])
    return {**result, "llm": usage_summary()}


@app.get("/api/grammar/profile")
def api_profile():
    return profile.summary(db())


@app.post("/api/grammar/profile")
def api_profile_change(body: ProfileChange):
    try:
        if body.add is not None:
            profile.add_note(db(), body.add)
        if body.remove is not None:
            profile.remove_note(db(), body.remove)
    except profile.ProfileError as e:
        raise HTTPException(400, str(e))
    return profile.summary(db())


@app.post("/api/grammar/why")
def api_grammar_why(body: GrammarWhy):
    result = grammar_call(practice.explain_answer, db(), body.item_id, body.answer)
    if result is None:
        raise HTTPException(404, "Unknown practice item")
    return {**result, "llm": usage_summary()}


@app.get("/api/grammar/debug")
def api_grammar_debug(lesson: int, exclude: str | None = None):
    return {**practice.debug(db(), lesson, exclude), "profile": profile.summary(db())}


@app.post("/api/grammar/done")
def api_grammar_done(body: GrammarPoint):
    grammar_call(grammar.mark_learned, db(), body.point)
    return {"ok": True}


@app.get("/api/debug")
def api_debug(lesson: int, topic: int | None = None, exclude: int | None = None):
    """For the demo's debug panel: every learned word in scope with its confidence broken down,
    least confident first, and which words the next pick (or sentence focus) can come from."""
    conn = db()
    topic_ids = scope_ids(topic)
    words = sorted(in_scope(word_stats(conn, lesson), topic_ids, learned_only=True),
                   key=lambda w: (w["confidence"], w["lesson"], w["id"]))
    return {
        "words": words,
        "next_pool": pick_pool(words, exclude),
        "focus_pool": [w[0] for w in focus_pool(conn, lesson, topic_ids)],
        "top_k": TOP_K,
        "focus_count": FOCUS_COUNT,
        "answers_per_day": ANSWERS_PER_DAY,
    }
