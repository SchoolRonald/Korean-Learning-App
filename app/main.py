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
from app import grammar
from app.checker import answer_variants
from app.learn import HANGUL, batch, cloze_check, english_ok, get_word, mark_learned
from app.llm import LLMError, usage_summary
from app.memory import ANSWERS_PER_DAY, in_scope, word_stats
from app.scheduler import TOP_K, next_word, pick_pool
from app.sentences import FOCUS_COUNT, NotReady, focus_pool, get_sentence, grade_sentence, prefetch
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


@app.get("/api/stats")
def api_stats(lesson: int, topic: int | None = None):
    return summary(db(), lesson, topic_ids=scope_ids(topic))


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
    return usage_summary()


def grammar_call(fn, *args):
    """Runs a grammar function, turning its errors into HTTP errors with safe messages."""
    try:
        return fn(*args)
    except grammar.GrammarError as e:
        raise HTTPException(404, str(e))
    except LLMError as e:
        raise HTTPException(503, str(e))


@app.get("/api/grammar/next")
def api_grammar_next(lesson: int):
    point = grammar.next_point(db(), lesson)
    return {"point": grammar.present_point(db(), point) if point else None,
            "outline": grammar.outline(db(), lesson)}


@app.get("/api/grammar/point")
def api_grammar_point(id: str, lesson: int):
    point = grammar_call(grammar.get_point, id)
    return {"point": grammar.present_point(db(), point), "outline": grammar.outline(db(), lesson),
            "custom": grammar.custom_explanations(db(), id)}


@app.get("/api/grammar/explain")
def api_grammar_explain(point: str, lesson: int, style: str = grammar.DEFAULT_STYLE):
    return {**grammar_call(grammar.explanation, db(), point, lesson, style), "llm": usage_summary()}


@app.post("/api/grammar/explain")
def api_grammar_explain_custom(body: GrammarRequest):
    result = grammar_call(grammar.custom_explanation, db(), body.point, body.lesson, body.request)
    return {**result, "llm": usage_summary()}


@app.post("/api/grammar/ask")
def api_grammar_ask(body: GrammarQuestion):
    result = grammar_call(grammar.ask, db(), body.point, body.lesson, body.question, body.explanation_id)
    return {**result, "llm": usage_summary()}


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
