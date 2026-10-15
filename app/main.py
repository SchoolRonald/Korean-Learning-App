from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.db import connect, init_db
from app.drill import grade_word, record_word_attempt
from app.llm import LLMError, usage_summary
from app.scheduler import next_word
from app.sentences import get_sentence, grade_sentence
from app.stats import summary

STATIC = Path(__file__).resolve().parent.parent / "static"

conn = connect()


@asynccontextmanager
async def lifespan(app):
    init_db(conn)
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class WordAnswer(BaseModel):
    word_id: int
    answer: str


class SentenceAnswer(BaseModel):
    sentence_id: int
    answer: str


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


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
    return [r[0] for r in conn.execute("SELECT DISTINCT lesson FROM words ORDER BY lesson")]


@app.get("/api/next")
def api_next(lesson: int, exclude: int | None = None):
    word = next_word(conn, lesson, exclude=exclude)
    if word is None:
        raise HTTPException(404, f"No words at lesson {lesson} or below")
    return {"id": word["id"], "english": word["english"], "lesson": word["lesson"]}


@app.post("/api/answer")
def api_answer(body: WordAnswer):
    result = grade_word(conn, body.word_id, body.answer)
    if result is None:
        raise HTTPException(404, "Unknown word")
    record_word_attempt(conn, body.word_id, body.answer, result["correct"])
    return result


@app.get("/api/sentence")
def api_sentence(lesson: int, exclude: int | None = None):
    try:
        sentence = get_sentence(conn, lesson, exclude)
    except LLMError as e:
        raise HTTPException(503, str(e))
    return {**sentence, "llm": usage_summary()}


@app.post("/api/sentence/answer")
def api_sentence_answer(body: SentenceAnswer):
    result = grade_sentence(conn, body.sentence_id, body.answer)
    if result is None:
        raise HTTPException(404, "Unknown sentence")
    return {**result, "llm": usage_summary()}


@app.get("/api/stats")
def api_stats(lesson: int):
    return summary(conn, lesson)
