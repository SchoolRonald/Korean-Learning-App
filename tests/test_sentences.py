import json
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import llm
from app.db import connect, init_db
from app.drill import record_word_attempt
from app.sentences import focus_words, get_sentence, grade_sentence


class FakeClient:
    """Stands in for anthropic.Anthropic(); returns queued replies in order."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text, stop = (reply, "end_turn") if isinstance(reply, str) else reply
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            stop_reason=stop,
        )


def sentence_json(english="I drink water.", korean="저는 물을 마셔요.", used=("물", "마시다")):
    return json.dumps({"english": english, "korean": korean, "words_used": list(used)})


def verdict_json(verdict="almost", reason="Particle 을 is missing."):
    return json.dumps({"verdict": verdict, "reason": reason})


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    c.executemany(
        "INSERT INTO words (hangul, english, lesson) VALUES (?, ?, ?)",
        [("물", "water", 1), ("마시다", "to drink", 1), ("책", "book", 1), ("학교", "school", 2)],
    )
    return c


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(llm, "usage", {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    # Separate logger so tests do not write to llm_usage.log.
    monkeypatch.setattr(llm, "log", llm.logging.getLogger("gongbu_test_llm"))

    def install(*replies):
        client = FakeClient(*replies)
        monkeypatch.setattr(llm, "_client", client)
        return client

    return install


def word_id(conn, hangul):
    return conn.execute("SELECT id FROM words WHERE hangul = ?", (hangul,)).fetchone()[0]


def test_generate_stores_sentence_with_known_word_ids(conn, fake):
    client = fake(sentence_json(used=["물", "마시다", "커피"]))
    s = get_sentence(conn, 1)
    assert s["source"] == "new" and s["english"] == "I drink water."
    row = conn.execute("SELECT korean_ref, word_ids FROM sentences WHERE id = ?", (s["id"],)).fetchone()
    # 커피 is not in the word list, so it is dropped.
    assert row[0] == "저는 물을 마셔요."
    assert json.loads(row[1]) == sorted([word_id(conn, "물"), word_id(conn, "마시다")])
    request = client.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    assert "학교" not in request["messages"][0]["content"]  # lesson 2 word not offered


def test_generate_rejects_sentence_with_no_known_words(conn, fake):
    fake(sentence_json(used=["커피"]))
    with pytest.raises(llm.LLMError, match="unusable"):
        get_sentence(conn, 1)


def test_cached_unattempted_sentence_is_reused(conn, fake):
    client = fake(sentence_json())
    first = get_sentence(conn, 1)
    second = get_sentence(conn, 1)
    assert second == {"id": first["id"], "english": first["english"], "source": "cache"}
    assert len(client.requests) == 1


def test_cached_sentence_needs_all_words_in_lesson(conn, fake):
    conn.execute(
        "INSERT INTO sentences (english, korean_ref, word_ids, created_at) VALUES (?, ?, ?, ?)",
        ("I go to school.", "학교에 가요.", json.dumps([word_id(conn, "학교")]), "2026-10-01"),
    )
    fake(sentence_json())
    assert get_sentence(conn, 1)["source"] == "new"
    assert get_sentence(conn, 2)["english"] == "I go to school."


def test_falls_back_to_cache_when_llm_fails(conn, fake):
    fake(sentence_json(), anthropic.AnthropicError("boom"))
    first = get_sentence(conn, 1)
    grade_sentence(conn, first["id"], "저는 물을 마셔요")
    s = get_sentence(conn, 1)
    assert s["id"] == first["id"] and "Reusing a saved sentence" in s["note"]


def test_llm_failure_with_empty_cache_raises(conn, fake):
    fake(anthropic.AnthropicError("no key"))
    with pytest.raises(llm.LLMError, match="LLM unavailable"):
        get_sentence(conn, 1)


def test_missing_api_key_is_friendly_error(conn, fake, monkeypatch):
    no_key = SimpleNamespace(api_key=None, auth_token=None, credentials=None)
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm.anthropic, "Anthropic", lambda: no_key)
    with pytest.raises(llm.LLMError, match="ANTHROPIC_API_KEY"):
        get_sentence(conn, 1)


def test_exact_match_skips_llm(conn, fake):
    client = fake(sentence_json())
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "저는  물을 마셔요")
    assert (r["verdict"], r["graded_by"]) == ("correct", "exact")
    assert len(client.requests) == 1
    assert tuple(conn.execute("SELECT kind, correct FROM attempts").fetchone()) == ("sentence", 1)


def test_llm_grade_recorded(conn, fake):
    fake(sentence_json(), verdict_json("almost", "Particle 을 is missing."))
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "저는 물 마셔요")
    assert r == {"verdict": "almost", "reason": "Particle 을 is missing.",
                 "reference": "저는 물을 마셔요.", "graded_by": "llm"}
    assert tuple(conn.execute("SELECT answer, correct FROM attempts").fetchone()) == ("저는 물 마셔요", 0)


@pytest.mark.parametrize("reply", [
    "this is not json",
    '{"verdict": "great", "reason": "x"}',
    '{"verdict": "correct"}',
    '["correct", "fine"]',
    ('{"verdict": "corr', "max_tokens"),
    ("", "refusal"),
])
def test_bad_grader_output_is_ungraded_and_not_recorded(conn, fake, reply):
    fake(sentence_json(), reply)
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "물")
    assert r["verdict"] == "ungraded" and r["graded_by"] is None and "reference" not in r
    assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0


def test_call_cap(conn, fake, monkeypatch):
    monkeypatch.setattr(llm, "CALL_CAP", 1)
    client = fake(sentence_json())
    s = get_sentence(conn, 1)
    r = grade_sentence(conn, s["id"], "물")
    assert r["verdict"] == "ungraded" and "limit" in r["reason"]
    assert len(client.requests) == 1


def test_usage_is_counted(conn, fake):
    fake(sentence_json())
    get_sentence(conn, 1)
    assert llm.usage == {"calls": 1, "input_tokens": 100, "output_tokens": 20}


def test_focus_prefers_highest_fail_rate(conn):
    record_word_attempt(conn, word_id(conn, "책"), "x", False)
    record_word_attempt(conn, word_id(conn, "물"), "x", False)
    record_word_attempt(conn, word_id(conn, "물"), "물", True)
    focus = [f[1] for f in focus_words(conn, 1)]
    assert focus[:2] == ["책", "물"] and len(focus) == 3


@pytest.fixture
def client(conn, monkeypatch):
    monkeypatch.setattr(main, "conn", conn)
    with TestClient(main.app) as c:
        yield c


def test_api_sentence_flow(client, fake):
    fake(sentence_json(), verdict_json("incorrect", "Wrong verb."))
    s = client.get("/api/sentence", params={"lesson": 1}).json()
    assert "korean_ref" not in s and s["llm"] == {"calls": 1, "cap": llm.CALL_CAP}
    r = client.post("/api/sentence/answer", json={"sentence_id": s["id"], "answer": "물을 먹어요"}).json()
    assert r["verdict"] == "incorrect" and r["graded_by"] == "llm"


def test_api_sentence_llm_error_is_503(client, fake):
    fake(anthropic.AnthropicError("no key"))
    res = client.get("/api/sentence", params={"lesson": 1})
    assert res.status_code == 503 and "LLM unavailable" in res.json()["detail"]


def test_sentences_page_served(client):
    assert "Sentence practice" in client.get("/sentences").text
    assert client.get("/static/common.js").status_code == 200
