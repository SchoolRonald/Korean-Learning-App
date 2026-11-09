import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import jev, practice, sentences
from tests.test_practice import POINT, FakeAI, answer, item


class Response:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, str(data)

    def json(self):
        return self._data


@pytest.fixture
def jev_api(monkeypatch):
    """A fake Jev HTTP endpoint that answers every question with the given probabilities."""
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    sent = {"bodies": [], "probabilities": {}}

    def post(url, json, timeout, headers):
        sent["bodies"].append(json)
        sent["headers"] = headers
        answers = {name: {"type": "noul", "noul": sent["probabilities"].get(name, 0.95)} for name in json["questions"]}
        return Response(200, {"model": jev.MODEL, "answers": answers, "usage": {"input_tokens": 100}})
    monkeypatch.setattr(httpx, "post", post)
    return sent


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "db_path", tmp_path / "test.db")
    monkeypatch.setattr(practice, "call_json", FakeAI())
    with TestClient(main.app) as c:
        yield c


def test_request_is_pinned_and_authorized(jev_api):
    correct, probabilities = jev.judge("Translate", "I am a student.", ["저는 학생이에요."], "제가 학생이에요.")
    body = jev_api["bodies"][0]
    assert body["model"] == "jev-1.14.0" and jev_api["headers"]["Authorization"] == "Bearer test-key"
    assert set(body["questions"]) == {"meaning", "correct"}
    assert all(q["type"] == "noul" and q["criteria"] for q in body["questions"].values())
    assert body["state"]["learner_answer"] == "제가 학생이에요."
    assert correct is True and set(probabilities) == {"meaning", "correct"}


def test_every_question_must_pass_the_threshold(jev_api):
    jev_api["probabilities"] = {"correct": 0.69}
    assert jev.judge("Translate", "x", ["y"], "z")[0] is False
    jev_api["probabilities"] = {"correct": 0.7}
    assert jev.judge("Translate", "x", ["y"], "z")[0] is True


def test_grammar_practice_also_asks_about_the_point(jev_api):
    jev.judge("Translate", "x", ["y"], "z", point="Topic particle 은/는")
    assert "uses_point" in jev_api["bodies"][0]["questions"]


def test_missing_key_or_bad_status_raises(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    with pytest.raises(jev.JevError):
        jev.ask("s", {"q": {"instructions": "i"}})
    monkeypatch.setenv("JEV_API_KEY", "k")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response(429, {"detail": "slow down"}))
    with pytest.raises(jev.JevError, match="429"):
        jev.ask("s", {"q": {"instructions": "i"}})


def test_practice_free_answers_are_graded_by_jev(client, jev_api):
    right = answer(client, item(client, item_type="translate")["id"], "제가 학생이에요")
    assert right["verdict"] == "correct" and right["graded_by"] == "jev"
    jev_api["probabilities"] = {"correct": 0.2}
    wrong = answer(client, item(client, item_type="spot")["id"], "저는 학상이에요.")
    assert wrong["verdict"] == "incorrect" and wrong["graded_by"] == "jev"


def test_fill_sends_the_finished_sentence(client, jev_api):
    first = item(client)
    answer(client, first["id"], "이")
    assert jev_api["bodies"][0]["state"]["learner_answer"] == first["sentence"].replace("___", "이")


def test_jev_failure_falls_back_to_haiku(client):
    result = answer(client, item(client, item_type="translate")["id"], "제가 학생이에요")
    assert result["graded_by"] == "llm"


def test_why_explains_without_changing_the_grade(client, jev_api):
    jev_api["probabilities"] = {"meaning": 0.1}
    first = item(client, item_type="translate")
    answer(client, first["id"], "저는 의사예요")
    why = client.post("/api/grammar/why", json={"item_id": first["id"], "answer": "저는 의사예요"}).json()
    assert why["verdict"] == "almost" and why["reason"]
    rows = main.db().execute("SELECT verdict FROM grammar_attempts").fetchall()
    assert [r[0] for r in rows] == ["incorrect"]


def test_sentences_use_jev_for_non_exact_answers(client, jev_api, monkeypatch):
    conn = main.db()
    cur = conn.execute("INSERT INTO sentences (english, korean_ref, word_ids, created_at) VALUES (?, ?, '[]', 'now')",
                       ("I am a student.", "저는 학생이에요."))
    conn.commit()
    result = client.post("/api/sentence/answer", json={"sentence_id": cur.lastrowid, "answer": "제가 학생이에요."}).json()
    assert result["verdict"] == "correct" and result["graded_by"] == "jev"
    monkeypatch.setattr(sentences, "call_json", lambda *a, **k: {"verdict": "incorrect", "reason": "Use 저는."})
    why = client.post("/api/sentence/why", json={"sentence_id": cur.lastrowid, "answer": "제가 학생이에요."}).json()
    assert why == {"verdict": "incorrect", "reason": "Use 저는.", "llm": why["llm"]}
