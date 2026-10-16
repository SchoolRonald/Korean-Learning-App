import json
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import llm, sentences
from app.db import connect, init_db
from app.learn import batch, mark_learned
from app.sentences import NotReady, get_sentence
from app.stats import summary
from app.topics import TopicError, resolve, topic_word_ids


class FakeClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=reply)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            stop_reason="end_turn",
        )


@pytest.fixture
def db_file(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_file):
    c = connect(db_file)
    init_db(c)
    c.executemany(
        "INSERT INTO words (hangul, english, lesson) VALUES (?, ?, ?)",
        [("밥", "rice, meal", 1), ("물", "water", 1), ("학교", "school", 1), ("사과", "apple", 2), ("비빔밥", "bibimbap", 9)],
    )
    c.commit()
    return c


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(llm, "usage", {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    monkeypatch.setattr(llm, "log", llm.logging.getLogger("gongbu_test_llm"))

    def install(*replies):
        client = FakeClient(*replies)
        monkeypatch.setattr(llm, "_client", client)
        return client

    return install


def wid(conn, hangul):
    return conn.execute("SELECT id FROM words WHERE hangul = ?", (hangul,)).fetchone()[0]


LINES = {"밥": "밥 = rice, meal", "물": "물 = water", "학교": "학교 = school", "사과": "사과 = apple", "비빔밥": "비빔밥 = bibimbap"}


def topic_json(*words, interpretation="foods and drinks"):
    return json.dumps({"interpretation": interpretation, "words": [LINES.get(w, w) for w in words]})


def test_resolve_filters_to_scope_and_saves(conn, fake):
    # The model also returns 비빔밥 (lesson 9, not offered), a made-up line, and an altered meaning.
    client = fake(topic_json("밥", "물", "비빔밥", "라면 = ramen", "물 = drinking water"))
    topic = resolve(conn, "  Food ", 1)
    assert (topic["name"], topic["lesson"], topic["count"], topic["interpretation"]) == ("food", 1, 2, "foods and drinks")
    assert topic_word_ids(conn, topic["id"]) == {wid(conn, "밥"), wid(conn, "물")}
    prompt = client.requests[0]["messages"][0]["content"]
    assert "Topic: food" in prompt and "비빔밥" not in prompt and "사과" not in prompt  # capped at lesson 1


def test_resolve_is_cached_per_topic_and_lesson(conn, fake):
    client = fake(topic_json("밥"), topic_json("밥", "사과"))
    first = resolve(conn, "food", 1)
    assert resolve(conn, "FOOD", 1) == first  # same name, same lesson: no call
    assert len(client.requests) == 1
    assert resolve(conn, "food", 2)["count"] == 2  # a higher lesson asks again
    assert len(client.requests) == 2


def test_resolve_no_matches_is_saved(conn, fake):
    client = fake(topic_json())
    for _ in range(2):
        with pytest.raises(TopicError, match='No "space" words up to lesson 1'):
            resolve(conn, "space", 1)
    assert len(client.requests) == 1


@pytest.mark.parametrize("reply", [
    "not json",
    '{"interpretation": "food", "words": "밥 = rice, meal"}',
    '{"interpretation": "", "words": ["물 = water"]}',
])
def test_resolve_bad_output(conn, fake, reply):
    fake(reply)
    with pytest.raises(llm.LLMError):
        resolve(conn, "food", 1)
    assert conn.execute("SELECT count(*) FROM topics").fetchone()[0] == 0


@pytest.mark.parametrize("name", ["", "   ", "x" * 61])
def test_resolve_bad_name(conn, name):
    with pytest.raises(TopicError):
        resolve(conn, name, 1)


def test_scope_in_learn_and_stats(conn, fake):
    fake(topic_json("밥", "물"))
    ids = topic_word_ids(conn, resolve(conn, "food", 1)["id"])
    assert [w["hangul"] for w in batch(conn, 1, ids)] == ["밥", "물"]
    mark_learned(conn, wid(conn, "밥"))
    mark_learned(conn, wid(conn, "학교"))
    s = summary(conn, 1, topic_ids=ids)
    assert (s["total"], s["learned"]) == (2, 1)


def test_sentences_need_a_learned_topic_word(conn, fake, monkeypatch):
    monkeypatch.setattr(sentences, "MIN_LEARNED", 1)
    mark_learned(conn, wid(conn, "학교"))
    fake(topic_json("밥"))
    ids = topic_word_ids(conn, resolve(conn, "food", 1)["id"])
    with pytest.raises(NotReady, match="from this topic"):
        get_sentence(conn, 1, topic_ids=ids)


def sentence_json(english, korean, tokens):
    return json.dumps({"english": english, "korean": korean, "tokens": [
        {"korean": k, "base": b, "english": b, "english_text": "", "is_name": False} for k, b in tokens
    ]})


def test_topic_sentences(conn, fake, monkeypatch):
    monkeypatch.setattr(sentences, "MIN_LEARNED", 1)
    for w in ("밥", "물", "학교"):
        mark_learned(conn, wid(conn, w))
    client = fake(
        topic_json("밥", "물"),
        sentence_json("I go to school.", "학교에 가요.", [("학교에", "학교"), ("가요", "가다")]),  # no topic word
        sentence_json("I eat rice.", "밥을 먹어요.", [("밥을", "밥"), ("먹어요", "먹다")]),
    )
    ids = topic_word_ids(conn, resolve(conn, "food", 1)["id"])
    with pytest.raises(llm.LLMError, match="word from the topic"):
        get_sentence(conn, 1, topic_ids=ids)
    s = get_sentence(conn, 1, topic_ids=ids)
    assert s["english"] == "I eat rice."
    # The focus words offered to the model were topic words.
    focus = client.requests[2]["messages"][0]["content"].split("Focus words: ")[1].split("\n")[0]
    assert set(focus.split(", ")) <= {"밥", "물"}
    # A saved sentence without a topic word is not served for the topic.
    conn.execute(
        "INSERT INTO sentences (english, korean_ref, word_ids, created_at) VALUES ('School.', '학교요.', ?, '2026-10-01')",
        (json.dumps([wid(conn, "학교")]),),
    )
    assert get_sentence(conn, 1, topic_ids=ids)["english"] == "I eat rice."


@pytest.fixture
def client(conn, db_file, monkeypatch):
    monkeypatch.setattr(main, "db_path", db_file)
    with TestClient(main.app) as c:
        yield c


def test_api_topics(client, conn, fake):
    fake(topic_json("밥", "물"), anthropic.AnthropicError("down"))
    topic = client.post("/api/topics", json={"name": "food", "lesson": 1}).json()
    assert topic["count"] == 2 and topic["llm"]["calls"] == 1
    words = client.get("/api/learn/batch", params={"lesson": 1, "topic": topic["id"]}).json()
    assert [w["hangul"] for w in words] == ["밥", "물"]
    mark_learned(conn, wid(conn, "학교"))
    res = client.get("/api/next", params={"lesson": 1, "topic": topic["id"]})
    assert res.status_code == 404 and "in this topic" in res.json()["detail"]
    assert client.get("/api/stats", params={"lesson": 1, "topic": 999}).status_code == 404
    assert client.post("/api/topics", json={"name": "music", "lesson": 1}).status_code == 503
    assert client.post("/api/topics", json={"name": "", "lesson": 1}).status_code == 404
