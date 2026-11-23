import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import grammar
from app.llm import TEACHING_MODEL, LLMError

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


def quiz(correct="저는 학생이에요", wrong=("저가 학생이에요", "저 학생이에요")):
    return {"question": "Which is right?", "choices": [{"text": correct, "correct": True, "why": "Topic."}] +
            [{"text": w, "correct": False, "why": "No."} for w in wrong]}


def section(count=4, heading="The rule", quizzes=None, nuances=("First point.", "Second point."), highlight="는"):
    return {
        "heading": heading, "body": "은/는 marks the topic.",
        "table": [{"when": "after a vowel", "form": "는", "example": "저는"}],
        "examples": [example(highlight=highlight) for _ in range(count)],
        "nuances": list(nuances), "quizzes": [quiz()] if quizzes is None else quizzes,
    }


def explanation_data(count=8, highlight="는"):
    half = count // 2
    return {
        "intro": "Look at these.",
        "sections": [section(half, "The rule", highlight=highlight),
                     section(count - half, "More uses", highlight=highlight)],
        "worked_example": {"task": "Say I am a student.", "steps": ["Pick 저는.", "Add 학생이에요."], "answer": "저는 학생이에요."},
        "mistakes": [{"wrong": "저은", "right": "저는", "why": "vowel"}],
        "summary": ["은/는 marks the topic."],
    }


class FakeAI:
    def __init__(self, data=None):
        self.data = data or explanation_data()
        self.prompts = []
        self.models = []

    def __call__(self, purpose, system, prompt, schema, **kwargs):
        self.prompts.append((purpose, prompt))
        self.models.append(kwargs.get("model"))
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


def test_lesson_is_saved_after_first_use(client, ai):
    first = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    assert len(grammar.all_examples(first)) == 8 and first["style"] == "lesson"
    again = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    assert again["id"] == first["id"]
    assert len(ai.prompts) == 1


def test_lesson_prompt_is_grounded_and_uses_sonnet(client, ai):
    point = next(p for p in grammar.points() if p["sources"])
    client.get(f"/api/grammar/explain?point={point['id']}&lesson=25")
    prompt = ai.prompts[0][1]
    assert point["summary"] in prompt and "krdict.korean.go.kr" in prompt
    assert "Write the main lesson" in prompt
    assert ai.models == [TEACHING_MODEL]


def test_next_point_writes_the_following_lesson_ahead(client, ai):
    second = grammar.points()[1]
    client.get("/api/grammar/next?lesson=1")
    assert len(ai.prompts) == 1 and second["title"] in ai.prompts[0][1]
    client.get(f"/api/grammar/explain?point={second['id']}&lesson=1")
    assert len(ai.prompts) == 1


def test_too_few_examples_is_a_friendly_error(client, monkeypatch):
    monkeypatch.setattr(grammar, "call_json", FakeAI(explanation_data(count=3)))
    r = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1")
    assert r.status_code == 503 and "unusable" in r.json()["detail"]


def test_misspelled_examples_are_dropped(client, monkeypatch):
    data = explanation_data(count=9)
    data["sections"][0]["examples"][0] = {**example(), "korean": "이것은 뭐에요?"}
    data["mistakes"].append({"wrong": "x", "right": "학생 이에요", "why": "y"})
    monkeypatch.setattr(grammar, "call_json", FakeAI(data))
    lesson = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    examples = grammar.all_examples(lesson)
    assert len(examples) == 8 and all("뭐에요" not in ex["korean"] for ex in examples)
    assert all(m["right"] != "학생 이에요" for m in lesson["mistakes"])


def test_lesson_left_with_too_few_examples_is_refused(client, monkeypatch):
    data = explanation_data(count=grammar.MIN_EXAMPLES)
    data["sections"][0]["examples"][0] = {**example(), "korean": "이것은 뭐에요?"}
    monkeypatch.setattr(grammar, "call_json", FakeAI(data))
    assert client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").status_code == 503


def test_highlight_not_in_sentence_is_dropped(client, monkeypatch):
    monkeypatch.setattr(grammar, "call_json", FakeAI(explanation_data(highlight="을")))
    data = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    assert grammar.all_examples(data)[0]["highlight"] == ""


def test_unlearned_words_are_flagged(client, ai):
    client.execute("INSERT INTO words (hangul, english, lesson) VALUES ('학생', 'student', 1)")
    client.execute("INSERT INTO words (hangul, english, lesson) VALUES ('저', 'I, me', 1)")
    client.execute("INSERT INTO learned (word_id, learned_at) SELECT id, 'now' FROM words WHERE hangul = '저'")
    main.db().commit()
    data = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    tokens = grammar.all_examples(data)[0]["tokens"]
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
    assert ai.models == [TEACHING_MODEL]
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
    assert set(data) == {"calls", "cap", "jev_calls"}


def lesson_of(client, data, monkeypatch):
    monkeypatch.setattr(grammar, "call_json", FakeAI(data))
    return client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()


def test_sections_keep_their_nuances_and_quizzes(client, ai):
    lesson = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    assert [s["heading"] for s in lesson["sections"]] == ["The rule", "More uses"]
    assert lesson["sections"][0]["nuances"] == ["First point.", "Second point."]
    assert all(len(s["quizzes"]) == 1 for s in lesson["sections"])
    assert lesson["worked_example"]["answer"] == "저는 학생이에요."
    assert lesson["summary"] == ["은/는 marks the topic."]


def test_quiz_choices_are_shuffled_but_keep_one_right_answer(client, monkeypatch):
    seen = set()
    for _ in range(40):
        q = grammar.clean_quiz(quiz())
        assert [c["correct"] for c in q["choices"]].count(True) == 1
        seen.add([c["correct"] for c in q["choices"]].index(True))
    assert len(seen) > 1


@pytest.mark.parametrize("bad", [
    {"question": "q", "choices": [{"text": "a", "correct": False, "why": ""}, {"text": "b", "correct": False, "why": ""}]},
    {"question": "q", "choices": [{"text": "a", "correct": True, "why": ""}, {"text": "b", "correct": True, "why": ""}]},
    {"question": "q", "choices": [{"text": "a", "correct": True, "why": ""}]},
    {"question": "q", "choices": [{"text": "a", "correct": True, "why": ""}, {"text": "a", "correct": False, "why": ""}]},
    {"question": " ", "choices": [{"text": "a", "correct": True, "why": ""}, {"text": "b", "correct": False, "why": ""}]},
    {"question": "q", "choices": [{"text": "학생 이에요", "correct": True, "why": ""}, {"text": "b", "correct": False, "why": ""}]},
])
def test_broken_quizzes_are_dropped(bad):
    assert grammar.clean_quiz(bad) is None


def test_a_wrong_choice_may_be_misspelled_on_purpose():
    q = grammar.clean_quiz(quiz(correct="학생이에요", wrong=("학생 이에요", "학생에요")))
    assert len(q["choices"]) == 3


def test_lesson_with_a_broken_quiz_keeps_the_rest(client, monkeypatch):
    data = explanation_data()
    data["sections"][0]["quizzes"] = [{"question": "q", "choices": []}]
    lesson = lesson_of(client, data, monkeypatch)
    assert lesson["sections"][0]["quizzes"] == [] and len(lesson["sections"][1]["quizzes"]) == 1


def test_section_without_heading_or_body_is_dropped(client, monkeypatch):
    data = explanation_data(count=10)
    data["sections"].append({**section(2), "heading": " "})
    data["sections"].append({**section(2), "body": ""})
    lesson = lesson_of(client, data, monkeypatch)
    assert len(lesson["sections"]) == 2


def test_missing_worked_example_is_none(client, monkeypatch):
    data = explanation_data()
    data["worked_example"] = {"task": "", "steps": [], "answer": ""}
    assert lesson_of(client, data, monkeypatch)["worked_example"] is None


OLD_LESSON = {
    "intro": "Old intro.", "rule": "Old rule.", "nuance": "Old nuance.",
    "table": [{"when": "w", "form": "f", "example": "e"}],
    "examples": [{**example(), "tokens": []} for _ in range(8)],
    "mistakes": [],
}


def save_old_lesson(client):
    import json
    client.execute(
        "INSERT INTO grammar_explanations (point_id, style, request, content, created_at) VALUES (?, 'lesson', NULL, ?, 'now')",
        (FIRST["id"], json.dumps(OLD_LESSON, ensure_ascii=False)))
    main.db().commit()


def test_old_saved_lessons_read_as_sections(client, ai):
    save_old_lesson(client)
    lesson = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    assert [s["heading"] for s in lesson["sections"]] == ["The rule", "Examples", "Nuance"]
    assert lesson["sections"][0]["body"] == "Old rule." and len(lesson["sections"][1]["examples"]) == 8
    assert lesson["sections"][2]["body"] == "Old nuance."
    assert lesson["worked_example"] is None and lesson["summary"] == []
    assert not ai.prompts


def test_questions_work_on_an_old_saved_lesson(client, ai):
    save_old_lesson(client)
    row = client.execute("SELECT id FROM grammar_explanations").fetchone()
    client.post("/api/grammar/ask", json={"point": FIRST["id"], "lesson": 1, "question": "Why?", "explanation_id": row[0]})
    prompt = ai.prompts[-1][1]
    assert "Old intro." in prompt and "Old rule." in prompt and "Old nuance." in prompt


def test_questions_see_numbered_nuances_of_a_new_lesson(client, ai):
    lesson = client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1").json()
    client.post("/api/grammar/ask", json={"point": FIRST["id"], "lesson": 1, "question": "Why?", "explanation_id": lesson["id"]})
    assert "Nuance 2: Second point." in ai.prompts[-1][1]


def test_lesson_prompt_asks_for_nuances_and_quizzes(client, ai):
    client.get(f"/api/grammar/explain?point={FIRST['id']}&lesson=1")
    assert "nuances" in ai.prompts[0][1] and "quiz" in ai.prompts[0][1]
