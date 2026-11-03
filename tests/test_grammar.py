import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import grammar
from app.llm import LLMError

FIRST = grammar.points()[0]


def example(highlight="는"):
    return {
        "korean": "저는 학생이에요.", "english": "I am a student.", "highlight": highlight, "note": "Topic.",
        "parts": [{"text": "저", "label": "I"}, {"text": "는", "label": "topic particle"}],
        "tokens": [
            {"korean": "저는", "base": "저", "english": "I", "english_text": "", "is_name": False},
            {"korean": "학생이에요", "base": "학생", "english": "student", "english_text": "", "is_name": False},
        ],
    }


def explanation_data(count=8, highlight="는"):
    return {
        "intro": "Look at these.", "examples": [example(highlight=highlight) for _ in range(count)],
        "rule": "은/는 marks the topic.", "table": [{"when": "after a vowel", "form": "는", "example": "저는"}],
        "nuance": "Contrast.", "mistakes": [{"wrong": "저은", "right": "저는", "why": "vowel"}],
    }


class FakeAI:
    def __init__(self, data=None):
        self.data = data or explanation_data()
        self.prompts = []

    def __call__(self, purpose, system, prompt, schema, **kwargs):
        self.prompts.append((purpose, prompt))
        if purpose == "grammar-ask":
            return {"answer": "Because 를 marks the object.", "examples": [{"korean": "밥을 먹어요.", "english": "I eat rice."}]}
        return self.data


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(grammar, "call_json", fake)
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "db_path", tmp_path / "test.db")
    with TestClient(main.app) as c:
        c.execute = lambda sql, args=(): main.db().execute(sql, args)
        yield c


def test_grammar_page_served_and_linked_from_every_tab(client):
    assert "Learn grammar" in client.get("/grammar").text
    for page in ["/", "/basics", "/grammar", "/words", "/sentences", "/stats"]:
        nav = client.get(page).text.split("<body>")[1].split("</p>")[0]
        assert "Learn Words" in nav and "Learn Grammar" in nav, page
        assert nav.index("Learn Words") < nav.index("Learn Grammar") < nav.index('>Words<'), page


def test_next_point_follows_curriculum_and_lesson(client):
    data = client.get("/api/grammar/next?lesson=1").json()
    assert data["point"]["id"] == FIRST["id"]
    assert {p["lesson"] for p in data["outline"]} == {1}
    assert client.post("/api/grammar/done", json={"point": FIRST["id"]}).json() == {"ok": True}
    data = client.get("/api/grammar/next?lesson=1").json()
    assert data["point"]["id"] == grammar.points()[1]["id"]
    assert data["outline"][0]["learned"] is True


def test_next_is_none_when_all_learned(client):
    for p in grammar.points():
        if p["lesson"] == 1:
            client.post("/api/grammar/done", json={"point": p["id"]})
    assert client.get("/api/grammar/next?lesson=1").json()["point"] is None


def test_unknown_point_is_404(client):
    assert client.post("/api/grammar/done", json={"point": "nope"}).status_code == 404
    assert client.get("/api/grammar/point?id=nope&lesson=1").status_code == 404


def test_point_shows_sources_with_license(client):
    point = next(p for p in grammar.points() if p["sources"])
    data = client.get(f"/api/grammar/point?id={point['id']}&lesson=25").json()["point"]
    assert data["sources"]["license"] == "CC BY-SA 2.0 KR"
    assert data["sources"]["entries"][0]["url"].startswith("https://krdict.korean.go.kr/")


def test_explanation_is_saved_after_first_use(client, ai):
    first = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1&style=examples").json()
    assert len(first["examples"]) == 8 and first["style_name"] == "Examples first"
    again = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1&style=examples").json()
    assert again["id"] == first["id"]
    assert len(ai.prompts) == 1
    client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1&style=rules")
    assert len(ai.prompts) == 2


def test_explanation_prompt_is_grounded(client, ai):
    point = next(p for p in grammar.points() if p["sources"])
    client.get(f"/api/grammar/explain?point={point['id']}&lesson=25&style=english")
    prompt = ai.prompts[0][1]
    assert point["summary"] in prompt and "krdict.korean.go.kr" in prompt
    assert "Start from English" in prompt


def test_unknown_style_is_404(client, ai):
    assert client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1&style=poem").status_code == 404


def test_too_few_examples_is_a_friendly_error(client, monkeypatch):
    monkeypatch.setattr(grammar, "call_json", FakeAI(explanation_data(count=3)))
    r = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1")
    assert r.status_code == 503 and "unusable" in r.json()["detail"]


def test_highlight_not_in_sentence_is_dropped(client, monkeypatch):
    monkeypatch.setattr(grammar, "call_json", FakeAI(explanation_data(highlight="을")))
    data = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    assert data["examples"][0]["highlight"] == ""


def test_unlearned_words_are_flagged(client, ai):
    client.execute("INSERT INTO words (hangul, english, lesson) VALUES ('학생', 'student', 1)")
    client.execute("INSERT INTO words (hangul, english, lesson) VALUES ('저', 'I, me', 1)")
    client.execute("INSERT INTO learned (word_id, learned_at) SELECT id, 'now' FROM words WHERE hangul = '저'")
    main.db().commit()
    data = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    tokens = data["examples"][0]["tokens"]
    assert [t["new"] for t in tokens] == [False, True]


def test_custom_explanations_are_saved_and_listed(client, ai):
    r = client.post("/api/grammar/explain", json={"point": FIRST["id"], "lesson": 1, "request": "with food examples"})
    assert r.json()["style"] == "request" and r.json()["request"] == "with food examples"
    assert "with food examples" in ai.prompts[-1][1]
    client.post("/api/grammar/explain", json={"point": FIRST["id"], "lesson": 1})
    assert "different angle" in ai.prompts[-1][1]
    custom = client.get(f"/api/grammar/point?id={FIRST['id']}&lesson=1").json()["custom"]
    assert [c["style"] for c in custom] == ["request", "angle"]


def test_long_request_is_rejected(client, ai):
    r = client.post("/api/grammar/explain", json={"point": FIRST["id"], "lesson": 1, "request": "x" * 300})
    assert r.status_code == 404


def test_questions_are_answered_and_kept(client, ai):
    r = client.post("/api/grammar/ask", json={"point": FIRST["id"], "lesson": 1, "question": "Why 를?"})
    assert r.json()["answer"].startswith("Because")
    data = client.get(f"/api/grammar/point?id={FIRST['id']}&lesson=1").json()["point"]
    assert data["questions"][0]["question"] == "Why 를?"
    assert client.post("/api/grammar/ask", json={"point": FIRST["id"], "lesson": 1, "question": " "}).status_code == 404


def test_ai_errors_become_503(client, monkeypatch):
    def fail(*args, **kwargs):
        raise LLMError("LLM call limit (500) reached for this session.")
    monkeypatch.setattr(grammar, "call_json", fail)
    r = client.post("/api/grammar/ask", json={"point": FIRST["id"], "lesson": 1, "question": "Why?"})
    assert r.status_code == 503 and "limit" in r.json()["detail"]


def test_pages_and_scripts_are_revalidated(client):
    for path in ["/grammar", "/static/common.js", "/static/style.css"]:
        assert client.get(path).headers["cache-control"] == "no-cache", path


def test_usage_endpoint(client):
    data = client.get("/api/usage").json()
    assert set(data) == {"calls", "cap"}
