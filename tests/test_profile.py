import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import grammar, practice, profile
from tests.test_grammar import FakeAI as LessonAI
from tests.test_practice import FakeAI as ItemAI


class NotesAI:
    def __init__(self, notes):
        self.notes = notes
        self.prompts = []

    def __call__(self, purpose, system, prompt, schema, **kwargs):
        self.prompts.append(prompt)
        return {"notes": self.notes}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "db_path", tmp_path / "test.db")
    monkeypatch.setattr(grammar, "call_json", LessonAI())
    monkeypatch.setattr(practice, "call_json", ItemAI())
    with TestClient(main.app) as c:
        yield c


POINT = grammar.points()[0]["id"]


def explain_like(client, request):
    return client.post("/api/grammar/explain", json={"point": POINT, "lesson": 1, "request": request})


def test_requests_become_notes_after_three_records(client, monkeypatch):
    ai = NotesAI(["Use food examples"])
    monkeypatch.setattr(profile, "call_json", ai)
    explain_like(client, "with food examples")
    explain_like(client, "with food")
    assert ai.prompts == []
    client.post("/api/grammar/explain", json={"point": POINT, "lesson": 1})
    assert len(ai.prompts) == 1 and "with food examples" in ai.prompts[0]
    assert [n["text"] for n in client.get("/api/grammar/profile").json()["notes"]] == ["Use food examples"]


def test_notes_go_into_new_lesson_prompts(client, monkeypatch):
    lesson_ai = LessonAI()
    monkeypatch.setattr(grammar, "call_json", lesson_ai)
    client.post("/api/grammar/profile", json={"add": "Always compare with English"})
    client.get(f"/api/grammar/explain?point={POINT}&lesson=1")
    assert "Always compare with English" in lesson_ai.prompts[0][1]


def test_learner_notes_survive_updates_and_removed_notes_stay_removed(client, monkeypatch):
    client.post("/api/grammar/profile", json={"add": "Short sentences please"})
    monkeypatch.setattr(profile, "call_json", NotesAI(["Use food examples"]))
    for i in range(3):
        explain_like(client, f"food {i}")
    notes = client.get("/api/grammar/profile").json()["notes"]
    food = next(n for n in notes if n["text"] == "Use food examples")
    client.post("/api/grammar/profile", json={"remove": food["id"]})
    ai = NotesAI(["Use food examples", "Show tables"])
    monkeypatch.setattr(profile, "call_json", ai)
    for i in range(3):
        explain_like(client, f"more {i}")
    texts = [n["text"] for n in client.get("/api/grammar/profile").json()["notes"]]
    assert "Short sentences please" in texts and "Show tables" in texts and "Use food examples" not in texts
    assert "Use food examples" in ai.prompts[0]


def test_first_practice_answer_records_the_explanation_on_screen(client):
    item = client.get(f"/api/grammar/item?point={POINT}&type=fill&lesson=1").json()
    client.post("/api/grammar/answer", json={"item_id": item["id"], "answer": "는", "shown": "the main lesson"})
    records = client.get("/api/grammar/profile").json()["records"]
    assert records == [f"Answered the first practice item of {POINT} right after reading: the main lesson."]
    client.post("/api/grammar/answer", json={"item_id": item["id"], "answer": "는"})
    assert len(client.get("/api/grammar/profile").json()["records"]) == 1


def test_failed_notes_update_keeps_records_for_next_time(client):
    for i in range(3):
        explain_like(client, f"food {i}")
    summary = client.get("/api/grammar/profile").json()
    assert summary["notes"] == [] and summary["records_until_update"] == 0


def test_stats_show_grammar_in_scope_and_notes(client):
    client.post("/api/grammar/done", json={"point": POINT})
    client.post("/api/grammar/done", json={"point": "past-tense"})
    client.post("/api/grammar/profile", json={"add": "Short sentences"})
    main.db().execute("INSERT INTO words (hangul, english, lesson) VALUES ('물', 'water', 1)")
    main.db().commit()
    stats = client.get("/api/stats?lesson=1").json()
    lesson_one = sum(1 for p in grammar.points() if p["lesson"] == 1)
    assert stats["grammar"]["total"] == lesson_one and stats["grammar"]["learned"] == 1
    assert [p["id"] for p in stats["grammar"]["weakest"]] == [POINT]
    assert [n["text"] for n in stats["notes"]] == ["Short sentences"]
    assert "Grammar" in client.get("/stats").text


def test_bad_profile_changes_are_rejected(client):
    assert client.post("/api/grammar/profile", json={"add": " "}).status_code == 400
    assert client.post("/api/grammar/profile", json={"remove": 99}).status_code == 400
    assert client.post("/api/grammar/profile", json={"add": "x" * 200}).status_code == 400
